"""Shared source transport: domain sessions, bounded retries and explicit challenges.

The synchronous transport is also used from async callers through worker threads.
Each curl handle is leased exclusively; no curl handle crosses concurrent requests.
"""
import asyncio
import copy
import hashlib
import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from http.cookiejar import Cookie, CookieJar, MozillaCookieJar
from urllib.parse import urljoin, urlparse

import httpx
from curl_cffi.requests import Session
from curl_cffi.requests.impersonate import DEFAULT_CHROME

from animan.config import settings
from animan.security import is_safe_url

PROFILE = DEFAULT_CHROME
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              f"(KHTML, like Gecko) Chrome/{PROFILE.removeprefix('chrome')}.0.0.0 Safari/537.36")


class VerificationRequired(RuntimeError):
    def __init__(self, url):
        self.url = str(url)
        self.domain = urlparse(self.url).hostname or ""
        super().__init__(f"Vérification nécessaire pour {self.domain}")

    def to_dict(self):
        return {"error": str(self), "code": "verification_required", "domain": self.domain}


class SourceNetworkError(httpx.ConnectError):
    """A network failure with a machine-readable DNS/TLS/timeout category."""
    def __init__(self, message, kind, url):
        self.kind = kind
        super().__init__(message, request=httpx.Request("GET", url))


class RateLimited(httpx.HTTPStatusError):
    def __init__(self, response, delay):
        self.retry_after = delay
        super().__init__("Limitation de débit du serveur", request=response.request, response=response)


def retry_delay(value, attempt=0):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return min(8.0, 0.5 * 2 ** attempt)


def response_headers(raw):
    headers = httpx.Headers(raw.headers.multi_items())
    # curl has already decompressed the body. Leaving Content-Encoding here
    # would make httpx (and downstream clients) decompress it a second time.
    if headers.get("content-encoding", "identity").lower() != "identity":
        headers.pop("content-encoding", None)
        headers.pop("content-length", None)
    return headers


@dataclass
class DomainSession:
    domain: str
    proxy: str | None
    cookies: MozillaCookieJar
    condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.RLock()))
    clients: list = field(default_factory=list)
    leased: int = 0
    next_request: float = 0.0
    cooldown: float = 0.0
    blocked_url: str | None = None
    last_error: str | None = None
    generation: int = 0
    last_used: float = field(default_factory=time.monotonic)


class SourceHTTPService:
    def __init__(self, storage=None, min_interval=0.15, max_connections=3, cache_ttl=20.0,
                 session_factory=Session):
        self.storage = storage or settings.CACHE_DIR / "http_sessions"
        self.min_interval = min_interval
        self.max_connections = max_connections
        self.cache_ttl = cache_ttl
        self.session_factory = session_factory
        self._lock = threading.RLock()
        self._domains = {}
        self._cache = {}
        self._inflight = {}
        # Metadata waiting for a domain lease must not occupy the workers needed
        # to read/close active media streams and release those leases.
        self.executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="source-http")
        self.closed = False

    def start(self):
        if self.closed:
            self.executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="source-http")
            self.closed = False

    def state(self, url):
        domain = (urlparse(str(url)).hostname or "").lower()
        if not domain:
            raise ValueError("URL source invalide")
        with self._lock:
            if domain not in self._domains:
                from animan.services.proxy_service import proxy_service
                path = self.storage / (hashlib.sha256(domain.encode()).hexdigest() + ".cookies")
                jar = MozillaCookieJar(str(path))
                try:
                    jar.load(ignore_discard=False, ignore_expires=False)
                except (OSError, ValueError):
                    pass
                self._domains[domain] = DomainSession(domain, proxy_service.get_random_proxy(), jar)
            return self._domains[domain]

    def _save(self, state):
        try:
            self.storage.mkdir(parents=True, exist_ok=True, mode=0o700)
            state.cookies.clear_expired_cookies()
            # Session cookies stay in memory; only cookies with an expiry survive restart.
            path = str(state.cookies.filename)
            temp = path + ".tmp"
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.close(fd)
            state.cookies.save(temp, ignore_discard=False, ignore_expires=False)
            os.replace(temp, path)
            os.chmod(path, 0o600)
        except OSError:
            # Read-only deployments retain their cookie jar in memory.
            pass

    @contextmanager
    def lease(self, state):
        with state.condition:
            while state.leased >= self.max_connections:
                if self.closed:
                    raise RuntimeError("Transport source arrêté")
                state.condition.wait()
            if self.closed:
                raise RuntimeError("Transport source arrêté")
            state.leased += 1
            state.last_used = time.monotonic()
            client = state.clients.pop() if state.clients else None
        try:
            if client is None:
                client = self.session_factory(impersonate=PROFILE, use_thread_local_curl=False,
                                              trust_env=False, verify=settings.SSL_VERIFY,
                                              proxy=state.proxy)
            with state.condition:
                state.cookies.clear_expired_cookies()
                generation = state.generation
                initial = {(c.domain, c.path, c.name): copy.deepcopy(c) for c in state.cookies}
                jar = CookieJar()
                for cookie in state.cookies:
                    jar.set_cookie(copy.copy(cookie))
                client.cookies.clear()
                client.cookies.update(jar)
            yield client
        finally:
            with state.condition:
                if client is not None:
                    if state.generation == locals().get("generation"):
                        current = {(c.domain, c.path, c.name): c for c in client.cookies.jar}
                        for cookie in list(state.cookies):
                            key = (cookie.domain, cookie.path, cookie.name)
                            if key in initial and key not in current and vars(cookie) == vars(initial[key]):
                                state.cookies.clear(*key)
                        for cookie in current.values():
                            key = (cookie.domain, cookie.path, cookie.name)
                            changed = key not in initial or vars(cookie) != vars(initial[key])
                            if changed and not cookie.is_expired():
                                state.cookies.set_cookie(copy.copy(cookie))
                        self._save(state)
                    if self.closed:
                        client.close()
                    else:
                        state.clients.append(client)
                state.leased -= 1
                state.last_used = time.monotonic()
                state.condition.notify_all()

    def pace(self, state):
        while True:
            with state.condition:
                now = time.monotonic()
                delay = max(state.next_request, state.cooldown) - now
                if state.cooldown - now > 8:
                    response = httpx.Response(429, request=httpx.Request("GET", "https://" + state.domain))
                    raise RateLimited(response, state.cooldown - now)
                if delay <= 0:
                    state.next_request = now + self.min_interval
                    return
            time.sleep(min(delay, 0.5))

    def classify(self, state, response, url, streaming=False):
        html = "text/html" in response.headers.get("content-type", "").lower()
        body = response.text[:65536].lower() if html and not streaming else ""
        challenge = response.headers.get("cf-mitigated", "").lower() == "challenge"
        # Do not treat every 403/503 or every Cloudflare-served response as a challenge.
        challenge = challenge or (html and ("/cdn-cgi/challenge-platform/" in body)
                                  and ("cf-chl-" in body or "just a moment" in body))
        if challenge:
            with state.condition:
                state.blocked_url = str(url)
                state.last_error = "challenge"
            raise VerificationRequired(url)

    def _key(self, state, method, url, headers, kwargs):
        payload = json.dumps([state.domain, state.generation, method, str(url), sorted(headers.items()),
                              kwargs.get("params"), [(c.domain, c.path, c.name, c.value) for c in state.cookies
                                                     if not c.is_expired()]], sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def request(self, method, url, *, headers=None, timeout=30.0, follow_redirects=True,
                bypass_cache=False, verify_challenge=False, **kwargs):
        method = method.upper()
        state = self.state(url)
        if state.blocked_url and not verify_challenge:
            raise VerificationRequired(state.blocked_url)
        headers = dict(httpx.Headers(headers or {}))
        headers["user-agent"] = USER_AGENT
        kwargs.pop("impersonate", None)
        kwargs.pop("verify", None)
        kwargs.pop("proxy", None)
        kwargs.pop("proxies", None)
        cookies = kwargs.pop("cookies", None)
        if cookies:
            with state.condition:
                for name, value in dict(cookies).items():
                    # Legacy configured cookies must never overwrite refreshed clearance.
                    if not any(c.name == name and not c.is_expired() for c in state.cookies):
                        state.cookies.set_cookie(self.cookie(state.domain, name, value))
        cacheable = method == "GET" and not bypass_cache and not verify_challenge and not any(
            k in headers for k in ("range", "authorization", "cookie")) and not any(
            x in urlparse(str(url)).path.lower() for x in (".m3u8", ".mpd", ".ts", ".mp4", ".m4s", ".key"))
        key = self._key(state, method, url, headers, kwargs)
        leader = True
        with self._lock:
            if cacheable:
                cached = self._cache.get(key)
                if cached and cached[0] > time.monotonic():
                    return copy.deepcopy(cached[1])
                future = self._inflight.get(key)
                if future:
                    leader = False
                else:
                    future = self._inflight[key] = Future()
        if not leader:
            return copy.deepcopy(future.result())
        try:
            response = self._request(method, str(url), headers, timeout, follow_redirects,
                                     verify_challenge, kwargs)
            if cacheable and response.status_code == 200 and len(response.content) <= 1024 * 1024:
                control = response.headers.get("cache-control", "").lower()
                if not any(x in control for x in ("no-store", "no-cache", "private")) and not response.headers.get("set-cookie"):
                    with self._lock:
                        # Bounded cache, including stale entries.
                        if len(self._cache) >= 256:
                            self._cache.pop(next(iter(self._cache)))
                        self._cache[key] = (time.monotonic() + self.cache_ttl, copy.deepcopy(response))
            if cacheable:
                future.set_result(response)
            return response
        except BaseException as exc:
            if cacheable:
                future.set_exception(exc)
            raise
        finally:
            if cacheable:
                with self._lock:
                    self._inflight.pop(key, None)

    def _request(self, method, url, headers, timeout, follow, verifying, kwargs):
        for redirect in range(7):
            if not is_safe_url(url):
                raise ValueError("URL source non autorisée")
            state = self.state(url)
            if state.blocked_url and not verifying:
                raise VerificationRequired(state.blocked_url)
            for attempt in range(3):
                self.pace(state)
                try:
                    with self.lease(state) as client:
                        raw = client.request(method, url, headers=headers, timeout=self.timeout(timeout),
                                             allow_redirects=False, **kwargs)
                        response = httpx.Response(raw.status_code, headers=response_headers(raw),
                                                  content=raw.content, request=httpx.Request(method, raw.url))
                except Exception as exc:
                    if isinstance(exc, (VerificationRequired, ValueError)):
                        raise
                    message = str(exc).lower()
                    kind = "tls" if any(x in message for x in ("certificate", "ssl", "tls")) else (
                        "dns" if "resolve" in message else ("timeout" if "timed out" in message or "timeout" in message else "network"))
                    state.last_error = kind
                    if kind == "tls" or attempt == 2 or method not in ("GET", "HEAD"):
                        raise SourceNetworkError(f"Erreur réseau ({kind}) pour {state.domain}", kind, url) from exc
                    time.sleep(retry_delay(None, attempt))
                    continue
                self.classify(state, response, url)
                state.last_error = None if response.status_code < 400 else f"http_{response.status_code}"
                if response.status_code == 429 or response.status_code in (502, 503, 504):
                    delay = retry_delay(response.headers.get("retry-after"), attempt)
                    with state.condition:
                        state.cooldown = max(state.cooldown, time.monotonic() + delay)
                    if delay <= 8 and attempt < 2 and method in ("GET", "HEAD"):
                        continue
                    if response.status_code == 429:
                        state.last_error = "rate_limit"
                        raise RateLimited(response, delay)
                break
            if not follow or response.status_code not in (301, 302, 303, 307, 308) or not response.headers.get("location"):
                return response
            target = urljoin(url, response.headers["location"])
            if urlparse(target).netloc != urlparse(url).netloc:
                headers = {k: v for k, v in headers.items() if k not in ("authorization", "cookie", "origin")}
            if response.status_code == 303 or (method == "POST" and response.status_code in (301, 302)):
                method = "GET"
                kwargs = {k: v for k, v in kwargs.items() if k not in ("data", "json", "content")}
            kwargs.pop("params", None)
            url = target
        raise ValueError("Trop de redirections")

    @staticmethod
    def timeout(value):
        if isinstance(value, httpx.Timeout):
            return (value.connect or 15.0, value.read or 300.0)
        return value

    @staticmethod
    def cookie(domain, name, value, path="/", secure=True, expires=None):
        return Cookie(0, name, value, None, False, domain, domain.startswith("."), domain.startswith("."),
                      path, True, secure, expires, expires is None, None, None, {}, False)

    def import_cookies(self, url, cookies):
        state = self.state(url)
        with state.condition:
            for item in cookies:
                domain = str(item.get("domain", state.domain)).lower()
                if state.domain != domain.lstrip(".") and not (domain.startswith(".") and state.domain.endswith(domain)):
                    continue
                expires = item.get("expires")
                if expires and expires > 0 and expires <= time.time():
                    continue
                state.cookies.set_cookie(self.cookie(domain, item["name"], item["value"],
                                                     item.get("path", "/"), item.get("secure", True),
                                                     int(expires) if expires and expires > 0 else None))
            state.generation += 1
            self._save(state)

    def diagnostics(self):
        with self._lock:
            states = list(self._domains.values())
        result = []
        for state in states:
            with state.condition:
                state.cookies.clear_expired_cookies()
                result.append({"domain": state.domain, "profile": PROFILE, "usesProxy": bool(state.proxy),
                               "cookieCount": len(state.cookies), "verificationRequired": bool(state.blocked_url),
                               "lastError": state.last_error})
        return result

    def close(self):
        with self._lock:
            self.closed = True
            for state in self._domains.values():
                with state.condition:
                    for client in state.clients:
                        client.close()
                    state.clients.clear()
                    state.condition.notify_all()
            self._cache.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def close_idle(self, max_idle=300):
        with self._lock:
            states = list(self._domains.values())
        for state in states:
            with state.condition:
                if not state.leased and time.monotonic() - state.last_used > max_idle:
                    for client in state.clients:
                        client.close()
                    state.clients.clear()

    def client(self, **options):
        return SourceClient(self, **options)

    def async_client(self, **options):
        return AsyncSourceClient(self, **options)


class SourceClient:
    def __init__(self, service, headers=None, timeout=30.0, follow_redirects=True, cookies=None, **options):
        self.service = service
        self.headers = dict(headers or {})
        self.cookies = cookies or {}
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.event_hooks = options.get("event_hooks") or {}

    def request(self, method, url, **kwargs):
        headers = {**self.headers, **dict(kwargs.pop("headers", {}) or {})}
        follow = kwargs.pop("follow_redirects", kwargs.pop("allow_redirects", self.follow_redirects))
        return self.service.request(method, url, headers=headers, cookies=kwargs.pop("cookies", self.cookies),
                                    timeout=kwargs.pop("timeout", self.timeout),
                                    follow_redirects=follow, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def head(self, url, **kwargs):
        return self.request("HEAD", url, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass  # The service, rather than the short-lived facade, owns connections.


class AsyncSourceClient(SourceClient):
    async def request(self, method, url, **kwargs):
        # Hooks remain supported for callers with additional URL checks.
        for hook in self.event_hooks.get("request", []):
            await hook(httpx.Request(method, url))
        call = partial(super().request, method, url, **kwargs)
        return await asyncio.get_running_loop().run_in_executor(self.service.executor, call)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aclose(self):
        pass

    def build_request(self, method, url, **kwargs):
        return httpx.Request(method, url, headers={**self.headers, **kwargs.pop("headers", {})}, **kwargs)

    async def send(self, request, stream=False):
        if stream:
            context = SourceStream(self, request.method, str(request.url), dict(request.headers))
            response = await context.__aenter__()
            response._context = context
            return response
        return await self.request(request.method, str(request.url), headers=dict(request.headers))

    def stream(self, method, url, headers=None, **kwargs):
        return SourceStream(self, method, url, {**self.headers, **dict(headers or {})}, kwargs)


class SourceStream:
    def __init__(self, client, method, url, headers, kwargs=None):
        self.client, self.method, self.url = client, method, str(url)
        self.headers = dict(httpx.Headers(headers))
        self.headers["user-agent"] = USER_AGENT
        self.kwargs = kwargs or {}
        self.lease = None
        self.raw = None

    def open(self):
        service = self.client.service
        url = self.url
        verifying = self.kwargs.pop("verify_challenge", False)
        for _ in range(7):
            if not is_safe_url(url):
                raise ValueError("URL source non autorisée")
            state = service.state(url)
            if state.blocked_url and not verifying:
                raise VerificationRequired(state.blocked_url)
            service.pace(state)
            self.lease = service.lease(state)
            transport = self.lease.__enter__()
            try:
                self.raw = transport.request(self.method, url, headers=self.headers, stream=True,
                                             allow_redirects=False, timeout=service.timeout(self.client.timeout), **self.kwargs)
                response = httpx.Response(self.raw.status_code, headers=response_headers(self.raw),
                                          request=httpx.Request(self.method, self.raw.url))
                service.classify(state, response, url, streaming=True)
                if self.client.follow_redirects and response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                    target = urljoin(url, response.headers["location"])
                    if urlparse(target).netloc != urlparse(url).netloc:
                        self.headers.pop("authorization", None)
                        self.headers.pop("cookie", None)
                    self.close()
                    url = target
                    continue
                # HTML is never a media stream; inspect its small body for challenge markers.
                if "text/html" in response.headers.get("content-type", "").lower():
                    body = bytearray()
                    for chunk in self.raw.iter_content():
                        body.extend(chunk)
                        if len(body) >= 65536:
                            break
                    response = httpx.Response(response.status_code, headers=response.headers, content=bytes(body), request=response.request)
                    service.classify(state, response, url)
                    raise httpx.HTTPStatusError("Réponse HTML reçue à la place du média", request=response.request, response=response)
                if response.status_code == 429:
                    delay = retry_delay(response.headers.get("retry-after"))
                    with state.condition:
                        state.cooldown = max(state.cooldown, time.monotonic() + delay)
                    raise RateLimited(response, delay)
                self.response = SourceStreamResponse(self, response)
                return self.response
            except BaseException:
                self.close()
                raise
        raise ValueError("Trop de redirections")

    def close(self):
        try:
            if self.raw is not None:
                self.raw.close()
                self.raw = None
        finally:
            if self.lease is not None:
                lease, self.lease = self.lease, None
                lease.__exit__(None, None, None)

    async def __aenter__(self):
        for hook in self.client.event_hooks.get("request", []):
            await hook(httpx.Request(self.method, self.url))
        # Shield initialization so cancellation cannot abandon an acquired lease.
        opening = asyncio.ensure_future(asyncio.get_running_loop().run_in_executor(self.client.service.executor, self.open))
        try:
            return await asyncio.shield(opening)
        except asyncio.CancelledError:
            await opening
            await asyncio.to_thread(self.close)
            raise

    async def __aexit__(self, *args):
        await asyncio.to_thread(self.close)


class SourceStreamResponse:
    def __init__(self, context, response):
        self._context, self._response = context, response
        self.status_code, self.headers, self.url = response.status_code, response.headers, response.url
        self.request = response.request

    def raise_for_status(self):
        self._response.raise_for_status()

    async def aiter_bytes(self, chunk_size=65536):
        iterator = iter(self._context.raw.iter_content())
        sentinel = object()
        while True:
            chunk = await asyncio.to_thread(next, iterator, sentinel)
            if chunk is sentinel:
                return
            for offset in range(0, len(chunk), chunk_size):
                yield chunk[offset:offset + chunk_size]

    async def aiter_raw(self, chunk_size=65536):
        async for chunk in self.aiter_bytes(chunk_size):
            yield chunk

    async def aclose(self):
        await asyncio.to_thread(self._context.close)


source_http = SourceHTTPService()
