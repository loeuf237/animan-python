"""AniWorld's JSON search and season/hoster pages (not generic HTML search)."""
import hashlib
import json
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from animan.models.anime import AnimeResult, AnimeDetail, Episode
from animan.services.source_http import source_http
from .base import BaseSourceAdapter


class AniWorldAdapter(BaseSourceAdapter):
    name = "AniWorld"
    pkg_prefixes = ["animeextension.de.aniworld"]
    domains = ["aniworld.to"]

    async def search_anime(self, query, container):
        url = container.base_url + "/ajax/seriesSearch?" + urlencode({"keyword": query.strip()})
        rows = json.loads(await container._fetch_html(url))
        if not isinstance(rows, list):
            raise ValueError("AniWorld: format de recherche inattendu")
        results = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("name") or not row.get("link"):
                continue
            link = row["link"]
            url = urljoin(container.base_url, link if link.startswith(("/", "http")) else "/anime/stream/" + link)
            results.append(AnimeResult(id=hashlib.sha256(url.encode()).hexdigest()[:16],
                title=BeautifulSoup(row["name"], "html.parser").get_text(), url=url,
                imageUrl=urljoin(container.base_url, (row.get("cover") or "").replace("150x225", "220x330")),
                source=container.source_id, version="DE"))
        return results

    async def get_latest_releases(self, container):
        return await container._latest_html()

    async def get_anime_detail(self, anime_url, container):
        soup = BeautifulSoup(await container._fetch_html(anime_url), "html.parser")
        title = soup.select_one(".series-title h1 span, h1")
        cover = soup.select_one(".seriesCoverBox img")
        synopsis = soup.select_one("p.seri_des")
        seasons = list(dict.fromkeys(urljoin(anime_url, a["href"]) for a in soup.select("#stream > ul:first-child > li > a[href]")))
        episodes, seen = [], set()
        for url in seasons or [anime_url]:
            page = soup if url == anime_url else BeautifulSoup(await container._fetch_html(url), "html.parser")
            for row in page.select("table.seasonEpisodesList tbody tr"):
                link = row.select_one("td.seasonEpisodeTitle a[href]")
                if not link:
                    continue
                href = urljoin(url, link["href"])
                if href in seen:
                    continue
                seen.add(href)
                meta = row.select_one("td meta[content]")
                try:
                    number = int(float(meta["content"] if meta else row.get("data-episode-season-id", len(episodes) + 1)))
                except (ValueError, TypeError):
                    number = len(episodes) + 1
                episodes.append(Episode(number=number, title=link.get_text(" ", strip=True) or f"Episode {number}",
                    downloadPageUrl=href, playerUrl=href, version="DE"))
        return AnimeDetail(title=title.get_text(strip=True) if title else container.name, url=anime_url,
            imageUrl=urljoin(anime_url, cover.get("data-src") or cover.get("src", "")) if cover else "",
            synopsis=(synopsis.get("data-full-description") or synopsis.get_text()) if synopsis else "",
            genres=[g.get_text(strip=True) for g in soup.select(".genres ul li")],
            episodes=episodes, source=container.source_id, version="DE")

    async def get_episode_sources(self, play_url, container):
        soup = BeautifulSoup(await container._fetch_html(play_url), "html.parser")
        sources = []
        for item in soup.select("ul.row li[data-lang-key]"):
            link = item.select_one("a.watchEpisode[href]")
            if not link:
                continue
            async with source_http.async_client(headers=container._get_headers(), timeout=12, follow_redirects=True) as client:
                response = await client.get(urljoin(play_url, link["href"]))
                response.raise_for_status()
            hoster = item.select_one("h4")
            name = hoster.get_text(strip=True) if hoster else "Player"
            language = {"1": "DE", "2": "EN-SUB", "3": "DE-SUB"}.get(item["data-lang-key"], "")
            sources.append({"url": str(response.url), "server": name, "name": f"{name} ({language})",
                            "quality": "HD", "format": "embed"})
        return sources
