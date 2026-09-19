import asyncio
import json
import logging
import re
import time
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup
import httpx
from curl_cffi.requests import AsyncSession

from animan.config import settings
from animan.models.anime import AnimeResult, AnimeDetail, Episode
from animan.security import is_safe_url
from animan.services.proxy_service import proxy_service
from animan.services.unpacking import try_unpack

logger = logging.getLogger("animan.animepahe")


class CurlClientWrapper:
    """Wrapper asynchrone autour de curl_cffi pour bypasser Cloudflare avec impersonation Chrome/Edge."""

    def __init__(self, headers: dict, cookies: dict, timeout: float = 10.0):
        self.headers = headers
        self.cookies = cookies
        self.timeout = timeout
        self.session = None

    async def __aenter__(self):
        try:
            self.session = AsyncSession(impersonate="chrome124")
        except Exception as e:
            logger.debug("[animepahe] Erreur instanciation AsyncSession: %s", e)
            self.session = None
        return self

    async def __aexit__(self, *args):
        if self.session:
            try:
                await self.session.close()
            except Exception:
                pass

    async def get(self, url: str, headers: Optional[dict] = None, **kwargs):
        req_headers = dict(self.headers)
        if headers:
            req_headers.update(headers)
        timeout = kwargs.get("timeout", self.timeout)
        if self.session:
            return await self.session.get(
                url,
                headers=req_headers,
                cookies=self.cookies,
                timeout=timeout,
            )
        async with httpx.AsyncClient(timeout=timeout, verify=settings.SSL_VERIFY, follow_redirects=True) as client:
            return await client.get(url, headers=req_headers, cookies=self.cookies)


class AnimepaheService:
    def __init__(self):
        self.base_url = settings.ANIMEPAHE_URL.rstrip("/")
        self.backup_urls = [u.rstrip("/") for u in settings.ANIMEPAHE_BACKUP_URLS]
        self.cookie = settings.ANIMEPAHE_COOKIE
        self.latest_cache: List[AnimeResult] = []
        self.last_cache_time: float = 0.0
        self._cookies_cache: Optional[Dict[str, str]] = None
        self._cookies_cache_time: float = 0.0

    def _extract_browser_cookies(self, domain: str = "animepahe") -> Dict[str, str]:
        """Tente d'extraire automatiquement les cookies (cf_clearance, animepahe_session) depuis Edge/Chrome."""
        if self.cookie:
            parsed = {}
            for item in self.cookie.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    parsed[k.strip()] = v.strip()
            if parsed:
                return parsed

        try:
            import dbus
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives import hashes, padding
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

            bus = dbus.SessionBus()
            service = bus.get_object("org.freedesktop.secrets", "/org/freedesktop/secrets")
            ss = dbus.Interface(service, "org.freedesktop.Secret.Service")
            session_path = ss.OpenSession("plain", "")[1]

            unlocked, _ = ss.SearchItems({"application": "chromium", "xdg:schema": "chrome_libsecret_os_crypt_password_v2"})
            if not unlocked:
                unlocked, _ = ss.SearchItems({"application": "chrome", "xdg:schema": "chrome_libsecret_os_crypt_password_v2"})
            if not unlocked:
                return {}

            item = bus.get_object("org.freedesktop.secrets", unlocked[0])
            secret_struct = item.GetSecret(session_path, dbus_interface="org.freedesktop.Secret.Item")
            raw_secret = bytes(secret_struct[2])
            kdf = PBKDF2HMAC(hashes.SHA1(), 16, b"saltysalt", 1)
            key = kdf.derive(raw_secret)

            cookie_paths = [
                Path.home() / ".config/microsoft-edge/Default/Cookies",
                Path.home() / ".config/google-chrome/Default/Cookies",
                Path.home() / ".config/chromium/Default/Cookies",
            ]

            cookies = {}
            for p in cookie_paths:
                if not p.exists():
                    continue
                try:
                    conn = sqlite3.connect(f"file:{p}?immutable=1", uri=True)
                    cursor = conn.cursor()
                    cursor.execute("SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE ?", (f"%{domain}%",))
                    for host, name, enc in cursor.fetchall():
                        if enc.startswith(b"v11") or enc.startswith(b"v10"):
                            data = enc[3:]
                            cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
                            decryptor = cipher.decryptor()
                            try:
                                padded = decryptor.update(data) + decryptor.finalize()
                                unpadder = padding.PKCS7(128).unpadder()
                                val = unpadder.update(padded) + unpadder.finalize()
                                # Cookie value follows 32-byte integrity header in Chromium
                                cookies[name] = val[32:].decode("utf-8", errors="replace")
                            except Exception:
                                pass
                    conn.close()
                except Exception as e:
                    logger.debug("[animepahe] Erreur lecture cookie db %s: %s", p, e)

                if cookies:
                    break

            if cookies:
                logger.info("[animepahe] %d cookie(s) extraits automatiquement depuis le navigateur", len(cookies))
            return cookies
        except Exception as e:
            logger.debug("[animepahe] Impossible d'extraire les cookies navigateur: %s", e)
            return {}

    def _get_cookies(self) -> Dict[str, str]:
        now = time.time()
        if self._cookies_cache is None or (now - self._cookies_cache_time > 600):
            self._cookies_cache = self._extract_browser_cookies()
            self._cookies_cache_time = now
        return self._cookies_cache or {}

    def _get_candidate_bases(self) -> List[str]:
        candidates = [self.base_url]
        for b in self.backup_urls:
            if b not in candidates:
                candidates.append(b)
        return candidates

    def _get_async_client(self, base: Optional[str] = None, timeout: float = 10.0):
        headers = {
            "User-Agent": settings.ANIMEPAHE_USER_AGENT,
            "Accept": "application/json, text/html, application/xhtml+xml, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{base or self.base_url}/",
        }
        cookies = self._get_cookies()
        try:
            return CurlClientWrapper(headers=headers, cookies=cookies, timeout=timeout)
        except Exception as e:
            logger.warning("[animepahe] Erreur client HTTP: %s, repli httpx", e)
            return httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                verify=settings.SSL_VERIFY,
                headers=headers,
                cookies=cookies,
            )

    async def fetch_media_bytes(self, url: str, referer: Optional[str] = None) -> Optional[tuple[bytes, str]]:
        """Télécharge les images distantes (notamment i.animepahe.pw) avec bypass Cloudflare."""
        if not is_safe_url(url):
            return None
        cookies = self._get_cookies()
        headers = {
            "User-Agent": settings.ANIMEPAHE_USER_AGENT,
            "Referer": referer or f"{self.base_url}/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        try:
            async with AsyncSession(impersonate="chrome124") as session:
                resp = await session.get(url, headers=headers, cookies=cookies, timeout=10)
                if resp.status_code == 200:
                    ctype = resp.headers.get("content-type", "image/webp")
                    return resp.content, ctype
        except Exception as e:
            logger.debug("[animepahe] Erreur fetch_media_bytes curl_cffi: %s, repli httpx", e)

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=settings.SSL_VERIFY, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers, cookies=cookies)
                if resp.status_code == 200:
                    ctype = resp.headers.get("content-type", "image/webp")
                    return resp.content, ctype
        except Exception as e:
            logger.warning("[animepahe] Erreur fetch_media_bytes: %s", e)
        return None

    async def _fetch_api(self, path: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
        """Interroge l'API AnimePahe avec rotation automatique des miroirs en cas de 403 / panne."""
        for base in self._get_candidate_bases():
            url = f"{base}{path}"
            try:
                async with self._get_async_client(base=base, timeout=timeout) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        content_type = resp.headers.get("content-type", "")
                        if "application/json" in content_type or resp.text.strip().startswith(("{", "[")):
                            data = resp.json()
                            if base != self.base_url:
                                logger.info("[animepahe] Miroir actif basculé sur: %s", base)
                                self.base_url = base
                            return data
                    elif resp.status_code in (403, 502, 503):
                        logger.debug("[animepahe] Miroir %s a renvoyé %d pour %s", base, resp.status_code, path)
            except Exception as e:
                logger.debug("[animepahe] Erreur sur miroir %s pour %s: %s", base, path, e)
        return None

    # -------------------------------------------------------------------------
    # Dernières sorties (Airing)
    # -------------------------------------------------------------------------

    async def get_latest_releases(self) -> List[AnimeResult]:
        now = time.time()
        if not self.latest_cache or (now - self.last_cache_time > 15 * 60):
            await self.refresh_cache()
        return list(self.latest_cache)

    async def refresh_cache(self):
        try:
            logger.info("[animepahe] Chargement des dernières sorties depuis %s", self.base_url)
            data = await self._fetch_api("/api?m=airing&page=1", timeout=7.0)
            if data and "data" in data:
                results: List[AnimeResult] = []
                for item in data.get("data", []):
                    anime_session = item.get("anime_session", "")
                    anime_title = item.get("anime_title", "").strip()
                    ep_num = item.get("episode", 1)
                    snapshot = item.get("snapshot", "")
                    anime_id = str(item.get("anime_id", item.get("id", "")))

                    if not anime_title or not anime_session:
                        continue

                    results.append(
                        AnimeResult(
                            id=anime_id,
                            title=anime_title,
                            imageUrl=snapshot,
                            url=f"{self.base_url}/anime/{anime_session}",
                            version="VOST / Sub",
                            type="Anime",
                            episodeInfo=f"Épisode {ep_num}",
                            source="animepahe",
                        )
                    )

                if results:
                    self.latest_cache = results
                    self.last_cache_time = time.time()
                    logger.info("[animepahe] Cache mis à jour (%d animés)", len(results))
        except Exception as e:
            logger.warning("[animepahe] Erreur actualisation cache: %s", e)

    # -------------------------------------------------------------------------
    # Recherche
    # -------------------------------------------------------------------------

    async def search_anime(self, query: str) -> List[AnimeResult]:
        clean_q = query.strip()
        if not clean_q:
            return []

        logger.info("[animepahe] Recherche: '%s'", clean_q)
        results: List[AnimeResult] = []

        try:
            data = await self._fetch_api(f"/api?m=search&q={quote_plus(clean_q)}", timeout=8.0)
            if data and "data" in data:
                for item in data.get("data", []):
                    title = item.get("title", "").strip()
                    session = item.get("session", "")
                    if not title or not session:
                        continue

                    anime_id = str(item.get("id", session))
                    poster = item.get("poster", "")
                    anime_type = item.get("type", "Anime")
                    episodes_count = item.get("episodes")
                    status = item.get("status", "")
                    season = item.get("season", "")
                    year = item.get("year", "")

                    meta_parts = []
                    if season or year:
                        meta_parts.append(f"{season} {year}".strip())
                    if episodes_count:
                        meta_parts.append(f"{episodes_count} ép.")

                    results.append(
                        AnimeResult(
                            id=anime_id,
                            title=title,
                            imageUrl=poster,
                            url=f"{self.base_url}/anime/{session}",
                            version=status or "Sub (VO)",
                            type=anime_type,
                            episodeInfo=" • ".join(meta_parts),
                            source="animepahe",
                        )
                    )
        except Exception as e:
            logger.error("[animepahe] Erreur recherche '%s': %s", clean_q, e)

        logger.info("[animepahe] Trouvé %d résultat(s) pour '%s'", len(results), clean_q)
        return results

    # -------------------------------------------------------------------------
    # Détail d'un animé & Épisodes
    # -------------------------------------------------------------------------

    async def get_anime_detail(self, anime_url: str) -> Optional[AnimeDetail]:
        if not is_safe_url(anime_url):
            logger.warning("[animepahe] SSRF bloqué pour l'URL: %s", anime_url)
            return None

        logger.info("[animepahe] Chargement détails anime: %s", anime_url)
        try:
            # Récupération de la page HTML
            html = ""
            for base in self._get_candidate_bases():
                parsed = urlparse(anime_url)
                target_url = f"{base}{parsed.path}"
                try:
                    async with self._get_async_client(base=base, timeout=8.0) as client:
                        resp = await client.get(target_url)
                        if resp.status_code == 200 and len(resp.text) > 500:
                            html = resp.text
                            self.base_url = base
                            break
                except Exception as e:
                    logger.debug("[animepahe] Échec chargement détail sur %s: %s", base, e)

            if not html:
                logger.warning("[animepahe] Impossible de charger la page détail: %s", anime_url)
                return None

            soup = BeautifulSoup(html, "html.parser")

            # Titre
            title_el = soup.select_one(".title-wrapper h1, h1.anime-title, h1")
            title = title_el.get_text().strip() if title_el else ""
            if not title and soup.title:
                title = soup.title.string.split("::")[0].strip()

            # Affiche
            poster_el = soup.select_one(".anime-poster a img, .poster img, .anime-poster img")
            image_url = ""
            if poster_el:
                image_url = poster_el.get("src") or poster_el.get("data-src", "")

            # Synopsis
            syn_el = soup.select_one(".anime-summary, .anime-synopsis")
            synopsis = syn_el.get_text().strip() if syn_el else ""

            # Métadonnées (Studio, Statut, Saison, Genres)
            studio = None
            for p in soup.select(".anime-info p, .col-sm-4.anime-info p"):
                txt = p.get_text()
                if "Studios:" in txt or "Studio:" in txt:
                    studio = txt.split(":")[-1].strip()
                    break

            genres = list(dict.fromkeys(g.get_text().strip() for g in soup.select(".anime-genre ul li, .anime-genre a") if g.get_text().strip()))

            # Extraction de l'identifiant interne pour l'API releases
            temp_id = ""
            meta_url = soup.find("meta", {"property": "og:url"})
            if meta_url and meta_url.get("content"):
                temp_id = meta_url["content"].rstrip("/").split("/")[-1]

            if not temp_id:
                m = re.search(r"/anime/([a-zA-Z0-9\-]+)", anime_url)
                if m:
                    temp_id = m.group(1)

            # Pagination des épisodes via l'API release
            episodes: List[Episode] = []
            if temp_id:
                episodes = await self._fetch_all_episodes(temp_id, anime_session=temp_id)

            anime_id = temp_id or str(hash(anime_url))[:8]

            return AnimeDetail(
                id=anime_id,
                title=title or "AnimePahe",
                imageUrl=image_url,
                synopsis=synopsis,
                genres=genres,
                episodes=episodes,
                source="animepahe",
                studio=studio,
                url=anime_url,
                version="VOSTFR / Sub",
            )
        except Exception as e:
            logger.error("[animepahe] Erreur get_anime_detail: %s", e)
            return None

    async def _fetch_all_episodes(self, temp_id: str, anime_session: str) -> List[Episode]:
        """Récupère l'ensemble des épisodes disponibles via pagination API."""
        first_page = await self._fetch_api(f"/api?m=release&id={temp_id}&sort=episode_asc&page=1", timeout=8.0)
        if not first_page or "data" not in first_page:
            return []

        all_ep_data = list(first_page.get("data", []))
        last_page = min(first_page.get("last_page", 1), 15)  # Sécurité max 15 pages (450 épisodes)

        if last_page > 1:
            async def fetch_p(page_num: int):
                return await self._fetch_api(f"/api?m=release&id={temp_id}&sort=episode_asc&page={page_num}", timeout=7.0)

            tasks = [fetch_p(p) for p in range(2, last_page + 1)]
            pages = await asyncio.gather(*tasks, return_exceptions=True)
            for p in pages:
                if isinstance(p, dict) and "data" in p:
                    all_ep_data.extend(p["data"])

        episodes: List[Episode] = []
        for e in all_ep_data:
            try:
                ep_num = int(float(e.get("episode", 1)))
            except (ValueError, TypeError):
                ep_num = 1

            ep_session = e.get("session", "")
            snapshot = e.get("snapshot", "")
            ep_title = e.get("title") or f"Épisode {ep_num}"
            play_url = f"{self.base_url}/play/{anime_session}/{ep_session}" if ep_session else ""

            episodes.append(
                Episode(
                    number=ep_num,
                    title=ep_title,
                    url=play_url,
                    version="Sub",
                    downloadPageUrl=play_url,
                    playerUrl=play_url,
                    thumbnailUrl=snapshot,
                    animeId=temp_id,
                )
            )

        episodes.sort(key=lambda x: x.number)
        return episodes

    # -------------------------------------------------------------------------
    # Résolution des sources et des flux Kwik
    # -------------------------------------------------------------------------

    async def get_episode_sources(self, play_url: str) -> List[Dict[str, Any]]:
        """Extrait les lecteurs et qualités disponibles depuis la page de lecture."""
        if not is_safe_url(play_url):
            return []

        sources: List[Dict[str, Any]] = []
        try:
            async with self._get_async_client(timeout=20.0) as client:
                resp = await client.get(play_url)
                if resp.status_code != 200:
                    return []

                html = resp.text
                # Extraction des boutons data-src
                buttons = re.findall(
                    r'<button[^>]+data-src="([^"]+)"[^>]*data-resolution="([^"]+)"[^>]*data-audio="([^"]*)"[^>]*>',
                    html,
                    re.IGNORECASE
                )
                if not buttons:
                    # Alternative regex si l'ordre des attributs change
                    buttons = re.findall(
                        r'<button[^>]+data-resolution="([^"]+)"[^>]*data-src="([^"]+)"[^>]*>',
                        html,
                        re.IGNORECASE
                    )
                    buttons = [(b[1], b[0], "jpn") for b in buttons]

                for item in buttons:
                    src = item[0]
                    res = item[1]
                    audio = item[2] if len(item) > 2 else "jpn"
                    audio_label = "Dub" if "eng" in audio.lower() else "VO (Sub)"
                    sources.append({
                        "name": f"Kwik {res}p ({audio_label})",
                        "server": "kwik",
                        "quality": f"{res}p",
                        "url": src,
                        "audio": audio,
                    })

                # Fallback : liens directs dans #pickDownload
                if not sources:
                    dl_links = re.findall(r'href="(https?://[^"]*(?:kwik|pahe)[^"]*)"[^>]*>([^<]+)</a>', html, re.IGNORECASE)
                    for link, label in dl_links:
                        sources.append({
                            "name": f"Kwik - {label.strip()}",
                            "server": "kwik",
                            "quality": "HD",
                            "url": link,
                        })

        except Exception as e:
            logger.warning("[animepahe] Erreur extraction sources depuis %s: %s", play_url, e)

        return sources

    async def extract_kwik_stream(self, kwik_url: str) -> Optional[str]:
        """
        Dépaquette le JavaScript obfusqué de Kwik pour récupérer le lien direct .mp4 ou .m3u8.
        Utilise curl_cffi avec impersonation Chrome pour contourner les protections Cloudflare.
        """
        if not kwik_url or not is_safe_url(kwik_url):
            return None

        logger.info("[animepahe] Résolution flux Kwik: %s", kwik_url)
        try:
            headers = {
                "User-Agent": settings.ANIMEPAHE_USER_AGENT,
                "Referer": f"{self.base_url}/",
            }
            html = ""

            # 1. Tentative avec httpx (compatible avec les mocks unitaires)
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers, verify=settings.SSL_VERIFY) as client:
                    resp = await client.get(kwik_url)
                    if resp.status_code == 200:
                        html = resp.text
                    elif resp.status_code in (403, 503):
                        logger.debug("[animepahe] Kwik bloqué par Cloudflare (%d), bascule curl_cffi", resp.status_code)
            except Exception as e:
                logger.debug("[animepahe] httpx exception sur %s: %s, bascule curl_cffi", kwik_url, e)

            # 2. Contournement Cloudflare via curl_cffi impersonate si httpx a échoué / bloqué
            if not html:
                try:
                    async with AsyncSession(impersonate="chrome124") as session:
                        resp = await session.get(kwik_url, headers=headers, timeout=15.0, allow_redirects=True)
                        if resp.status_code == 200:
                            html = resp.text
                        elif resp.status_code == 429:
                            logger.warning("[animepahe] Kwik a répondu avec code 429 (rate limit), pause 1.5s et nouvelle tentative...")
                            await asyncio.sleep(1.5)
                            resp = await session.get(kwik_url, headers=headers, timeout=15.0, allow_redirects=True)
                            if resp.status_code == 200:
                                html = resp.text
                            else:
                                logger.warning("[animepahe] Kwik a encore répondu avec code %d après retry", resp.status_code)
                                return None
                        else:
                            logger.warning("[animepahe] Kwik a répondu avec code %d", resp.status_code)
                            return None
                except Exception as e:
                    logger.warning("[animepahe] Échec curl_cffi sur %s: %s", kwik_url, e)
                    return None

            # 3. Vérification si URL .mp4 ou .m3u8 en clair
            direct_match = re.search(r"https?://[^'\"\s<>]+\.(?:m3u8|mp4)[^'\"\s<>]*", html)
            if direct_match:
                return direct_match.group(0).rstrip("\\'\"")

            # 4. Dépaquetage de tous les scripts Dean Edwards packer
            from animan.services.unpacking import unpack_all
            unpacked_list = unpack_all(html)
            if not unpacked_list:
                unpacked_list = [try_unpack(html)]

            for unpacked in unpacked_list:
                stream_match = re.search(r"https?://[^'\"\s<>]+\.(?:m3u8|mp4)[^'\"\s<>]*", unpacked)
                if stream_match:
                    return stream_match.group(0).rstrip("\\'\"")

                # Détection du formulaire de téléchargement / token POST Kwik
                form_action = re.search(r'<form[^>]+action="([^"]+)"[^>]*method="POST"', unpacked)
                token_val = re.search(r'name="_token"\s+value="([^"]+)"', unpacked)
                if form_action and token_val:
                    post_url = form_action.group(1)
                    token = token_val.group(1)
                    post_headers = {
                        "User-Agent": headers["User-Agent"],
                        "Referer": kwik_url,
                    }
                    try:
                        async with AsyncSession(impersonate="chrome124") as session:
                            post_resp = await session.post(post_url, data={"_token": token}, headers=post_headers, allow_redirects=False)
                            location = post_resp.headers.get("location")
                            if location:
                                return location.rstrip("\\'\"")
                    except Exception:
                        pass

        except Exception as e:
            logger.warning("[animepahe] Échec résolution stream Kwik (%s): %s", kwik_url, e)

        return None


animepahe_service = AnimepaheService()
