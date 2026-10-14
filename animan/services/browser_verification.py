"""User-assisted verification in an installed browser; no browser downloads."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
from urllib.parse import urlparse

import httpx
import websockets

from animan.config import settings
from animan.security import is_safe_url
from animan.services.source_http import source_http, USER_AGENT, VerificationRequired


class BrowserVerificationService:
    def __init__(self, transport=source_http):
        self.transport = transport
        self.jobs = {}
        self.webview_opener = None
        self._lock = asyncio.Lock()

    def installed_browsers(self):
        candidates = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                      "microsoft-edge", "microsoft-edge-stable", "brave-browser", "chrome", "msedge"]
        if os.name == "nt":
            for root in [os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("LOCALAPPDATA")]:
                if root:
                    candidates += [str(Path(root) / p) for p in ["Google/Chrome/Application/chrome.exe",
                                    "Microsoft/Edge/Application/msedge.exe", "Chromium/Application/chrome.exe"]]
        candidates += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                       "/Applications/Chromium.app/Contents/MacOS/Chromium",
                       "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
        found = []
        for candidate in candidates:
            path = shutil.which(candidate)
            if path and path not in [b["path"] for b in found]:
                found.append({"name": Path(candidate).name, "path": path})
        return found

    def options(self):
        return {"browsers": [{"name": b["name"]} for b in self.installed_browsers()],
                "webviewAvailable": self.webview_opener is not None,
                "sessions": self.transport.diagnostics()}

    async def start(self, domain, browser=None, mode="browser"):
        domain = domain.strip().lower()
        state = self.transport.state("https://" + domain)
        if not state.blocked_url:
            raise ValueError("Aucune vérification en attente pour ce domaine")
        url = state.blocked_url
        if not await asyncio.to_thread(is_safe_url, url):
            raise ValueError("URL de vérification non autorisée")
        async with self._lock:
            await self.expire()
            for job in list(self.jobs.values()):
                if job["domain"] == domain:
                    process = job.get('process')
                    if process and process.poll() is not None:
                        await self.cancel(job['id'])
                        continue
                    return {"id": job["id"], "domain": domain, "mode": job["mode"]}
            if len(self.jobs) >= 3:
                raise ValueError("Fermez une vérification avant d’en ouvrir une autre")
            job = {"id": uuid.uuid4().hex, "domain": domain, "url": url, "created": time.monotonic(),
                   "mode": mode, "process": None, "window": None}
            # Verification must use the same network route as the HTTP session.
            if mode == "webview":
                if self.webview_opener is None:
                    raise ValueError("WebView disponible uniquement dans les applications natives Animan")
                if state.proxy:
                    raise ValueError("Utilisez le navigateur installé pour vérifier avec ce proxy")
                job["window"] = await asyncio.to_thread(self.webview_opener, url)
            elif mode == "browser":
                installed = self.installed_browsers()
                selected = next((b for b in installed if b["name"] == browser), None) if browser else next(iter(installed), None)
                if not selected:
                    raise ValueError("Aucun Chrome, Chromium, Edge ou Brave installé n’a été trouvé")
                if os.name != "nt" and not os.getenv("DISPLAY") and not os.getenv("WAYLAND_DISPLAY") and sys.platform != 'darwin':
                    raise ValueError("Cette machine ne dispose pas d’une session graphique")
                profile = settings.CACHE_DIR / "verification_profiles" / hashlib.sha256(domain.encode()).hexdigest()
                profile.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(profile, 0o700)
                port_file = profile / "DevToolsActivePort"
                port_file.unlink(missing_ok=True)
                args = [selected["path"], f"--user-data-dir={profile}", "--remote-debugging-address=127.0.0.1",
                        "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
                        "--disable-background-mode", f"--user-agent={USER_AGENT}", "--new-window", url]
                if state.proxy:
                    parsed = urlparse(state.proxy)
                    if parsed.username or parsed.password:
                        raise ValueError("La vérification intégrée nécessite un proxy sans authentification")
                    args.insert(-2, "--proxy-server=" + state.proxy)
                job["process"] = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                job["port_file"] = port_file
            else:
                raise ValueError("Mode de vérification inconnu")
            self.jobs[job["id"]] = job
            return {"id": job["id"], "domain": domain, "mode": mode}

    async def _cdp(self, job, command, params=None):
        process = job["process"]
        if process.poll() is not None:
            raise ValueError("Le navigateur de vérification a été fermé")
        lines = []
        for _ in range(40):
            try:
                lines = job["port_file"].read_text().splitlines()
                if len(lines) >= 2:
                    break
            except OSError:
                pass
            await asyncio.sleep(0.1)
        if len(lines) < 2:
            raise ValueError("Le navigateur n’a pas encore démarré ; réessayez")
        port = int(lines[0])
        if not 0 < port < 65536 or not lines[1].startswith("/devtools/browser/"):
            raise ValueError("Point de connexion navigateur invalide")
        async with websockets.connect(f"ws://127.0.0.1:{port}{lines[1]}", proxy=None, open_timeout=5) as ws:
            await ws.send(json.dumps({"id": 1, "method": command, "params": params or {}}))
            async with asyncio.timeout(8):
                while True:
                    message = json.loads(await ws.recv())
                    if message.get("id") == 1:
                        if "error" in message:
                            raise ValueError("Impossible de lire les cookies du navigateur")
                        return message.get("result", {})

    async def complete(self, job_id):
        await self.expire()
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError("Vérification expirée ou introuvable")
        if job["mode"] == "webview":
            window = job["window"]
            cookies = []
            for jar in await asyncio.to_thread(window.get_cookies):
                for name, morsel in jar.items():
                    expiry = morsel["expires"]
                    if expiry:
                        from email.utils import parsedate_to_datetime
                        expiry = parsedate_to_datetime(expiry).timestamp()
                    cookies.append({"name": name, "value": morsel.value,
                                    "domain": morsel["domain"] or job["domain"],
                                    "path": morsel["path"] or "/", "secure": bool(morsel["secure"]),
                                    "expires": expiry or None})
        else:
            cookies = (await self._cdp(job, "Storage.getCookies")).get("cookies", [])
        await asyncio.to_thread(self.transport.import_cookies, job["url"], cookies)
        state = self.transport.state(job["url"])
        # Check the upstream response, rather than trusting a user's confirmation.
        media = any(x in urlparse(job["url"]).path.lower() for x in (".mp4", ".m3u8", ".ts", ".m4s"))
        method = "HEAD" if media else "GET"
        try:
            response = await asyncio.to_thread(self.transport.request, method, job["url"],
                                               bypass_cache=True, verify_challenge=True)
            if media and response.status_code in (403, 405, 501):
                async with self.transport.async_client().stream("GET", job["url"], headers={"Range": "bytes=0-1023"}, verify_challenge=True) as upstream:
                    upstream.raise_for_status()
            else:
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"La source refuse encore l’accès (HTTP {exc.response.status_code}) ; la vérification reste en attente") from exc
        except httpx.RequestError as exc:
            raise ValueError("La source est injoignable ; réessayez la validation lorsque la connexion sera rétablie") from exc
        with state.condition:
            state.blocked_url = None
            state.last_error = None
            state.generation += 1
        await self.cancel(job_id)
        return {"success": True, "domain": job["domain"]}

    async def cancel(self, job_id):
        job = self.jobs.pop(job_id, None)
        if job:
            if job["window"]:
                await asyncio.to_thread(job["window"].destroy)
            process = job["process"]
            if process and process.poll() is None:
                process.terminate()
                try:
                    await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=3)
                except asyncio.TimeoutError:
                    process.kill()
                    await asyncio.to_thread(process.wait)

    async def expire(self):
        for job_id, job in list(self.jobs.items()):
            if time.monotonic() - job["created"] > 600:
                await self.cancel(job_id)

    async def watch(self):
        while True:
            await asyncio.sleep(30)
            await self.expire()
            await asyncio.to_thread(self.transport.close_idle)

    async def close(self):
        for job_id in list(self.jobs):
            await self.cancel(job_id)


browser_verification = BrowserVerificationService()
