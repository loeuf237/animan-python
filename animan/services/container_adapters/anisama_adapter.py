"""AniSama exposes episodes and players through JSON AJAX endpoints."""
import json
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from bs4 import BeautifulSoup
from animan.models.anime import AnimeDetail, Episode
from .base import BaseSourceAdapter


class AniSamaAdapter(BaseSourceAdapter):
    name = "AniSama"
    pkg_prefixes = ["animeextension.fr.anisama"]
    domains = ["animesz.xyz"]

    async def search_anime(self, query, container):
        return await container._search_anime_html(query)

    async def get_latest_releases(self, container):
        return await container._latest_html()

    async def get_anime_detail(self, anime_url, container):
        page = await container._fetch_html(anime_url)
        if not page:
            return None
        soup = BeautifulSoup(page, "html.parser")
        canonical = soup.select_one('link[rel="canonical"]')
        path = urlparse(canonical.get("href") if canonical else anime_url).path.rstrip("/")
        anime_id = path.rsplit("-", 1)[-1]
        payload = await container._fetch_html(urljoin(container.base_url, f"/ajax/episode/list/{anime_id}"))
        try:
            items = BeautifulSoup(json.loads(payload)["html"], "html.parser").select(".ep-item")
        except (ValueError, KeyError, TypeError):
            return None
        title = soup.select_one(".anime-detail .dynamic-name, h1")
        poster = soup.select_one(".film-poster-img")
        synopsis = soup.select_one(".shorting")
        episodes = []
        for item in items:
            ep_id = parse_qs(urlparse(item.get("href", "")).query).get("ep", [None])[0]
            ep_id = ep_id or item.get("href", "").rsplit("=", 1)[-1]
            try:
                number = int(float(item["data-number"]))
            except (KeyError, ValueError):
                continue
            if not ep_id:
                continue
            url = urljoin(container.base_url, "/ajax/episode/servers?" + urlencode({"episodeId": ep_id}))
            episodes.append(Episode(number=number, title=item.get("title") or f"Épisode {number}",
                                    version="VOSTFR", playerUrl=url, downloadPageUrl=url))
        return AnimeDetail(title=title.get_text(strip=True) if title else container.name,
                           url=anime_url, source=container.pkg, episodes=sorted(episodes, key=lambda e: e.number),
                           imageUrl=urljoin(container.base_url, poster.get("src", "")) if poster else "",
                           synopsis=synopsis.get_text(strip=True) if synopsis else "")

    async def get_episode_sources(self, play_url, container):
        payload = await container._fetch_html(play_url)
        try:
            soup = BeautifulSoup(json.loads(payload)["html"], "html.parser")
        except (ValueError, KeyError, TypeError):
            return []
        episode_id = parse_qs(urlparse(play_url).query).get("episodeId", [""])[0]
        sources = []
        for server in soup.select(".server-item[data-id]"):
            endpoint = urljoin(container.base_url, "/ajax/episode/sources?") + "?" + urlencode({"id": server["data-id"], "epid": episode_id})
            try:
                link = json.loads(await container._fetch_html(endpoint))["link"]
            except (ValueError, KeyError, TypeError):
                continue
            if link:
                sources.append({"url": urljoin(play_url, link), "server": server.get_text(strip=True),
                                "name": server.get_text(strip=True), "quality": "HD", "format": "embed"})
        return sources
