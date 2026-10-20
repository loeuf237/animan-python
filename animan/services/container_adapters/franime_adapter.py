"""FRAnime's catalogue and players are API data, absent from its SPA HTML."""
import asyncio
import json
import re
import time
from urllib.parse import urlparse, parse_qs, urlencode
from animan.models.anime import AnimeResult, AnimeDetail, Episode
from .base import BaseSourceAdapter


class FrAnimeAdapter(BaseSourceAdapter):
    name = "FRAnime"
    pkg_prefixes = ["animeextension.fr.franime"]
    domains = ["franime.fr"]

    def __init__(self):
        self._catalogues = {}
        self._locks = {}

    def _api(self, container):
        parsed = urlparse(container.base_url)
        return f"{parsed.scheme}://api.{parsed.hostname.removeprefix('www.')}/api"

    async def _catalogue(self, container):
        # The upstream catalogue is ~11 MB. Share one download between the
        # home feed, search and detail requests, and cache only validated data.
        lock = self._locks.setdefault(container.base_url, asyncio.Lock())
        async with lock:
            cached = self._catalogues.get(container.base_url)
            if cached and time.monotonic() - cached[0] < 300:
                return cached[1]
            data = json.loads(await container._fetch_html(self._api(container) + "/animes/", timeout=40))
            if not isinstance(data, list):
                raise ValueError("FRAnime: format de catalogue inattendu")
            rows = [self._normalize(row) for row in data if isinstance(row, dict) and row.get("title")]
            self._catalogues[container.base_url] = (time.monotonic(), rows)
            return rows

    @staticmethod
    def _normalize(row):
        # Kotlin property names are not JSON field names (@SerialName).
        anime = dict(row)
        for target, wire in (("originalTitle", "titleO"), ("titlesAlt", "titles"),
                             ("poster", "affiche"), ("genres", "themes")):
            anime[target] = row.get(wire, row.get(target))
        anime["seasons"] = []
        for season in row.get("saisons", row.get("seasons", [])) or []:
            episodes = []
            for ep in season.get("episodes", []) or []:
                languages = {}
                for lang, value in (ep.get("lang", ep.get("languages", {})) or {}).items():
                    value = value or {}
                    languages[lang] = {**value, "players": value.get("lecteurs", value.get("players", [])) or []}
                episodes.append({**ep, "languages": languages})
            anime["seasons"].append({**season, "episodes": episodes})
        return anime

    def _slug(self, anime):
        return re.sub(r"[^A-Za-z0-9 ]", "", anime.get("originalTitle") or anime["title"]).replace(" ", "-").lower()

    def _entries(self, rows, container):
        entries = []
        for anime in rows:
            for season, data in enumerate(anime.get("seasons", []), 1):
                for lang, version in (("vo", "VOSTFR"), ("vf", "VF")):
                    if not any(ep.get("languages", {}).get(lang, {}).get("players") for ep in data.get("episodes", [])):
                        continue
                    url = f"{container.base_url}/anime/{self._slug(anime)}?" + urlencode({"lang": lang, "s": season})
                    entries.append(AnimeResult(id=f"{anime.get('id')}-{season}-{lang}",
                        title=f"{anime['title']} S{season} ({version})", imageUrl=anime.get("poster") or "",
                        url=url, version=version, source=container.pkg))
        return entries

    async def search_anime(self, query, container):
        query = query.casefold()
        rows = await self._catalogue(container)
        return self._entries([a for a in rows if query in " ".join([a.get("title", ""), (a.get("originalTitle") or ""), *[v or "" for v in (a.get("titlesAlt") or {}).values()]]).casefold()], container)[:50]

    async def get_latest_releases(self, container):
        return self._entries(list(reversed(await self._catalogue(container)))[:18], container)

    async def _find(self, url, container):
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        return next((a for a in await self._catalogue(container) if self._slug(a) == slug), None)

    async def get_anime_detail(self, anime_url, container):
        anime = await self._find(anime_url, container)
        if not anime:
            return None
        params = parse_qs(urlparse(anime_url).query)
        try:
            season = int(params.get("s", ["1"])[0])
            if season < 1:
                return None
            rows = anime["seasons"][season - 1]["episodes"]
        except (ValueError, IndexError, KeyError):
            return None
        lang = params.get("lang", ["vo"])[0]
        version = "VF" if lang == "vf" else "VOSTFR"
        episodes = []
        for number, ep in enumerate(rows, 1):
            if ep.get("languages", {}).get(lang, {}).get("players"):
                url = anime_url.split("?", 1)[0] + "?" + urlencode({"lang": lang, "s": season, "ep": number})
                episodes.append(Episode(number=number, title=ep.get("title") or f"Épisode {number}", version=version, playerUrl=url, downloadPageUrl=url))
        return AnimeDetail(title=f"{anime['title']} S{season}", url=anime_url, source=container.pkg,
            imageUrl=anime.get("poster") or "", synopsis=anime.get("description"), genres=anime.get("genres") or [], version=version, episodes=episodes)

    async def get_episode_sources(self, play_url, container):
        anime = await self._find(play_url, container)
        if not anime:
            return []
        params = parse_qs(urlparse(play_url).query)
        lang = params.get("lang", ["vo"])[0]
        try:
            season = int(params.get("s", ["1"])[0]) - 1
            number = int(params.get("ep", ["1"])[0]) - 1
            if min(season, number) < 0:
                return []
            players = anime["seasons"][season]["episodes"][number]["languages"][lang]["players"]
        except (ValueError, KeyError, IndexError):
            return []
        sources = []
        for index, name in enumerate(players):
            raw = await container._fetch_html(f"{self._api(container)}/anime/{anime['id']}/{season}/{number}/{lang}/{index}")
            try:
                link = json.loads(raw)
            except ValueError:
                link = raw.strip()
            if isinstance(link, str) and link.startswith(("https://", "http://")):
                sources.append({"url": link, "server": name, "name": name, "quality": "HD", "format": "embed"})
        return sources
