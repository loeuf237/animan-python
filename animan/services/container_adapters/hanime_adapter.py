from animan.services.source_http import source_http, VerificationRequired
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from animan.config import settings
from animan.models.anime import AnimeDetail, AnimeResult, Episode
from animan.services.container_adapters.base import BaseSourceAdapter
from animan.services.proxy_service import proxy_service

logger = logging.getLogger(__name__)

_catalog_cache: List[Dict[str, Any]] = []
_catalog_time: float = 0.0

async def get_hanime_catalog() -> List[Dict[str, Any]]:
    global _catalog_cache, _catalog_time
    # Si monkey-patché par aniyomi_container ou un test unitaire
    from animan.services import aniyomi_container
    if hasattr(aniyomi_container, "_get_hanime_catalog") and aniyomi_container._get_hanime_catalog != get_hanime_catalog:
        try:
            res = await aniyomi_container._get_hanime_catalog()
            if res:
                return res
        except VerificationRequired:
            raise
        except Exception:
            pass

    now = asyncio.get_event_loop().time()
    if _catalog_cache and (now - _catalog_time) < 3600:
        return _catalog_cache

    url = "https://guest.freeanimehentai.net/api/v11/search_hvs"
    headers = {
        "User-Agent": settings.DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://hanime.tv",
        "Referer": "https://hanime.tv/",
    }
    proxy = proxy_service.get_active_proxy()
    try:
        async with source_http.async_client(timeout=12.0, verify=settings.SSL_VERIFY, proxy=proxy) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                if items:
                    _catalog_cache = items
                    _catalog_time = now
                    return _catalog_cache
    except VerificationRequired:
        raise
    except Exception as e:
        logger.warning("[hanime_adapter] Erreur lors de la récupération du catalogue Hanime: %s", e)

    return _catalog_cache

class HanimeAdapter(BaseSourceAdapter):
    name = "Hanime"
    pkg_prefixes = ["eu.kanade.tachiyomi.animeextension.all.hanime", "eu.kanade.tachiyomi.animeextension.en.hanime", "hanime"]
    domains = ["hanime.tv"]

    async def search_anime(self, query: str, container: Any) -> List[AnimeResult]:
        clean_q = query.strip()
        if not clean_q:
            return []

        catalog = await get_hanime_catalog()
        q_lower = clean_q.lower()
        results: List[AnimeResult] = []

        for item in catalog:
            name = item.get("name", "")
            slug = item.get("slug", "")
            search_titles = str(item.get("search_titles", ""))
            tags = [str(t).lower() for t in item.get("tags", [])]
            if (
                q_lower in name.lower()
                or q_lower in slug.lower()
                or q_lower in search_titles.lower()
                or any(q_lower == t for t in tags)
            ):
                img_url = item.get("poster_url") or item.get("cover_url", "")
                results.append(
                    AnimeResult(
                        id=str(item.get("id")) if item.get("id") else str(hash(slug))[-8:],
                        title=name,
                        imageUrl=img_url,
                        url=f"https://hanime.tv/videos/hentai/{slug}",
                        version="EN",
                        type="Anime",
                        episodeInfo=item.get("brand") or container.name,
                        source=container.source_id,
                    )
                )
                if len(results) >= 50:
                    break

        logger.info("[hanime_adapter] Trouvé %d résultat(s) pour '%s'", len(results), clean_q)
        return results

    async def get_latest_releases(self, container: Any) -> List[AnimeResult]:
        catalog = await get_hanime_catalog()
        sorted_items = sorted(
            catalog,
            key=lambda x: x.get("created_at_unix", 0) or x.get("released_at_unix", 0),
            reverse=True,
        )
        results: List[AnimeResult] = []
        for item in sorted_items[:24]:
            slug = item.get("slug", "")
            results.append(
                AnimeResult(
                    id=str(item.get("id")) if item.get("id") else str(hash(slug))[-8:],
                    title=item.get("name", "Sans titre"),
                    imageUrl=item.get("poster_url") or item.get("cover_url", ""),
                    url=f"https://hanime.tv/videos/hentai/{slug}",
                    version="EN",
                    type="Anime",
                    episodeInfo="Récents",
                    source=container.source_id,
                )
            )
        return results

    async def get_anime_detail(self, anime_url: str, container: Any) -> Optional[AnimeDetail]:
        catalog = await get_hanime_catalog()
        slug = anime_url.rstrip("/").split("/")[-1]
        found_item = None
        for item in catalog:
            if item.get("slug") == slug:
                found_item = item
                break

        if not found_item:
            return None

        title = found_item.get("name", "Anime")
        img_url = found_item.get("poster_url") or found_item.get("cover_url", "")
        raw_desc = found_item.get("description", "")
        desc = re.sub(r"<[^>]+>", "", raw_desc).strip()
        genres = found_item.get("tags", [])
        episodes = [
            Episode(
                number=1,
                title=title,
                url=anime_url,
                downloadPageUrl=anime_url,
                playerUrl=anime_url,
                thumbnailUrl=img_url,
                version="EN",
                animeId=str(found_item.get("id", ""))[-8:],
            )
        ]
        return AnimeDetail(
            id=str(found_item.get("id", hash(anime_url)))[-8:],
            title=title,
            imageUrl=img_url,
            synopsis=desc,
            genres=genres[:6] if isinstance(genres, list) else [],
            episodes=episodes,
            source=container.source_id,
            url=anime_url,
            version="EN",
        )

    async def get_episode_sources(self, play_url: str, container: Any) -> List[Dict[str, Any]]:
        slug = play_url.rstrip("/").split("/")[-1]
        api_url = f"https://hanime.tv/api/v8/video?id={slug}"
        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Origin": "https://hanime.tv",
            "Referer": play_url,
        }
        try:
            proxy = proxy_service.get_active_proxy()
            async with source_http.async_client(timeout=10.0, proxy=proxy, headers=headers) as client:
                resp = await client.get(api_url)
                if resp.status_code == 200:
                    data = resp.json()
                    servers = data.get("videos_manifest", {}).get("servers", [])
                    sources: List[Dict[str, Any]] = []
                    for s in servers:
                        s_name = s.get("name", "Hanime")
                        for stream in s.get("streams", []):
                            u = stream.get("url")
                            h = stream.get("height", "HD")
                            if u:
                                sources.append({
                                    "name": f"{s_name} {h}p",
                                    "server": s_name,
                                    "url": u,
                                    "quality": f"{h}p" if str(h).isdigit() else str(h),
                                    "format": "hls" if ".m3u8" in u else "mp4",
                                })
                    if sources:
                        return sources
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[hanime_adapter] Erreur extraction streams Hanime: %s", e)

        return [{
            "name": f"{container.name} - Hanime",
            "server": "Hanime",
            "url": play_url,
            "quality": "HD",
            "format": "embed",
        }]
