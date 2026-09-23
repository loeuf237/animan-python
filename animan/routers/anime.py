import asyncio
import logging
from typing import List, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from animan.models.anime import AnimeResult
from animan.security import is_safe_url
from animan.services.library_service import library_service
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.animepahe_service import animepahe_service
from animan.services.extension_service import extension_service
from animan.services.tmdb_service import tmdb_service
from animan.templates_config import templates

logger = logging.getLogger("animan.router.anime")
router = APIRouter()

def detect_source_from_url(url: str, fallback: str = "french-manga") -> str:
    """Détecte automatiquement la source légitime d'un anime d'après son URL."""
    if not url:
        return fallback
    u = url.lower()
    if "animepahe" in u or "kwik." in u or "pahe." in u:
        return "animepahe"
    if "voir-anime" in u or "voiranime" in u:
        return "voir-anime"
    if "french-manga" in u:
        return "french-manga"
    # Vérifie si l'URL correspond à une extension Aniyomi active
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host:
            for src in extension_service.get_enabled_container_sources():
                if src.base_url and host in src.base_url.lower():
                    return src.pkg
    except Exception:
        pass
    return fallback

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    favorites = library_service.get_all_favorites()
    latest_fm = await scraping_service.get_latest_releases()
    latest_va = await voiranime_service.get_latest_releases()
    latest_ap = await animepahe_service.get_latest_releases()
    enabled_extensions = extension_service.get_enabled_container_sources()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "favorites": favorites,
            "latestFrenchManga": latest_fm,
            "latestVoirAnime": latest_va,
            "latestAnimePahe": latest_ap,
            "enabledExtensions": enabled_extensions,
            "results": None,
            "query": "",
            "source": "french-manga",
        }
    )

@router.get("/api/releases/latest")
async def api_latest_releases(source: Optional[str] = None):
    """Retourne les dernières sorties en JSON pour hydratation dynamique instantanée."""
    norm_source = (source or "all").lower().strip()
    if norm_source == "french-manga":
        releases = await scraping_service.get_latest_releases()
        return {"source": "french-manga", "releases": [r.model_dump() for r in releases]}
    elif norm_source == "voir-anime":
        releases = await voiranime_service.get_latest_releases()
        return {"source": "voir-anime", "releases": [r.model_dump() for r in releases]}
    elif norm_source == "animepahe":
        releases = await animepahe_service.get_latest_releases()
        return {"source": "animepahe", "releases": [r.model_dump() for r in releases]}
    else:
        fm = await scraping_service.get_latest_releases()
        va = await voiranime_service.get_latest_releases()
        ap = await animepahe_service.get_latest_releases()
        return {
            "french-manga": [r.model_dump() for r in fm],
            "voir-anime": [r.model_dump() for r in va],
            "animepahe": [r.model_dump() for r in ap],
        }


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query(..., alias="q"),
    source: str = Query("french-manga", alias="source")
):
    norm_source = (source or "french-manga").lower().strip()
    logger.info("Search [%s]: %s", norm_source, q)

    enabled_exts = extension_service.get_enabled_container_sources()
    results: List[AnimeResult] = []

    if norm_source == "all":
        # Multi-sources ordonnées : 1) French-Manga, 2) VoirAnime, 3) AnimePahe, 4) Extensions actives
        tasks = [
            scraping_service.search_anime(q),
            voiranime_service.search_anime(q),
            animepahe_service.search_anime(q),
        ]
        # Ajouter les recherches des extensions actives
        for ext in enabled_exts:
            tasks.append(ext.search_anime(q))

        all_res = await asyncio.gather(*tasks, return_exceptions=True)
        fm_res, va_res, ap_res = all_res[0], all_res[1], all_res[2]
        ext_res_list = all_res[3:]

        if not isinstance(fm_res, Exception) and fm_res:
            for item in fm_res:
                item.source = "french-manga"
            results.extend(fm_res)
        if not isinstance(va_res, Exception) and va_res:
            for item in va_res:
                item.source = "voir-anime"
            results.extend(va_res)
        if not isinstance(ap_res, Exception) and ap_res:
            for item in ap_res:
                item.source = "animepahe"
            results.extend(ap_res)

        for idx, ext_res in enumerate(ext_res_list):
            if not isinstance(ext_res, Exception) and ext_res:
                ext_pkg = enabled_exts[idx].pkg
                for item in ext_res:
                    item.source = ext_pkg
                results.extend(ext_res)

    elif norm_source == "voir-anime":
        va_res = await voiranime_service.search_anime(q)
        for item in va_res:
            item.source = "voir-anime"
        results = va_res
    elif norm_source == "animepahe":
        ap_res = await animepahe_service.search_anime(q)
        for item in ap_res:
            item.source = "animepahe"
        results = ap_res
    elif norm_source == "french-manga":
        fm_res = await scraping_service.search_anime(q)
        for item in fm_res:
            item.source = "french-manga"
        results = fm_res
    else:
        # Recherche ciblée sur une extension importée
        ext_src = extension_service.get_container_source_by_id(norm_source)
        if ext_src:
            results = await ext_src.search_anime(q)
            for item in results:
                item.source = ext_src.pkg
        else:
            fm_res = await scraping_service.search_anime(q)
            for item in fm_res:
                item.source = "french-manga"
            results = fm_res

    favorites = library_service.get_all_favorites()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "results": results,
            "query": q,
            "source": norm_source,
            "favorites": favorites,
            "enabledExtensions": enabled_exts,
            "latestFrenchManga": [],
            "latestVoirAnime": [],
            "latestAnimePahe": [],
        }
    )

@router.get("/api/search", response_model=List[AnimeResult])
async def search_api(
    q: str = Query(..., alias="q"),
    source: str = Query("all", alias="source")
):
    norm_source = (source or "all").lower().strip()
    enabled_exts = extension_service.get_enabled_container_sources()

    if norm_source == "all":
        tasks = [
            scraping_service.search_anime(q),
            voiranime_service.search_anime(q),
            animepahe_service.search_anime(q),
        ]
        for ext in enabled_exts:
            tasks.append(ext.search_anime(q))

        all_res = await asyncio.gather(*tasks, return_exceptions=True)
        results: List[AnimeResult] = []
        fm_res, va_res, ap_res = all_res[0], all_res[1], all_res[2]
        ext_res_list = all_res[3:]

        if not isinstance(fm_res, Exception) and fm_res:
            for item in fm_res:
                item.source = "french-manga"
            results.extend(fm_res)
        if not isinstance(va_res, Exception) and va_res:
            for item in va_res:
                item.source = "voir-anime"
            results.extend(va_res)
        if not isinstance(ap_res, Exception) and ap_res:
            for item in ap_res:
                item.source = "animepahe"
            results.extend(ap_res)

        for idx, ext_res in enumerate(ext_res_list):
            if not isinstance(ext_res, Exception) and ext_res:
                ext_pkg = enabled_exts[idx].pkg
                for item in ext_res:
                    item.source = ext_pkg
                results.extend(ext_res)

        return results
    elif norm_source == "voir-anime":
        results = await voiranime_service.search_anime(q)
        for item in results:
            item.source = "voir-anime"
        return results
    elif norm_source == "animepahe":
        results = await animepahe_service.search_anime(q)
        for item in results:
            item.source = "animepahe"
        return results
    elif norm_source == "french-manga":
        results = await scraping_service.search_anime(q)
        for item in results:
            item.source = "french-manga"
        return results
    else:
        ext_src = extension_service.get_container_source_by_id(norm_source)
        if ext_src:
            results = await ext_src.search_anime(q)
            for item in results:
                item.source = ext_src.pkg
            return results
        results = await scraping_service.search_anime(q)
        for item in results:
            item.source = "french-manga"
        return results

@router.get("/anime", response_class=HTMLResponse)
async def anime_detail(
    request: Request,
    url: str = Query(..., alias="url"),
    source: str = Query("french-manga", alias="source")
):
    logger.info("Anime detail requested [%s]: %s", source, url)
    if not is_safe_url(url):
        logger.warning("SSRF blocked on anime detail: %s", url)
        favorites = library_service.get_all_favorites()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "URL d'animé invalide ou non sécurisée.",
                "favorites": favorites,
                "results": None,
                "latestFrenchManga": [],
                "latestVoirAnime": [],
                "latestAnimePahe": [],
            }
        )

    # Détection automatique et correction de la source d'après l'URL
    detected_source = detect_source_from_url(url, fallback=source)
    if detected_source != source:
        logger.info("URL source corrected: [%s -> %s] for %s", source, detected_source, url)
        source = detected_source

    container_source = extension_service.get_container_source_by_id(source)
    if container_source:
        detail = await container_source.get_anime_detail(url)
    elif source == "animepahe":
        detail = await animepahe_service.get_anime_detail(url)
    elif source == "voir-anime":
        detail = await voiranime_service.get_anime_detail(url)
    else:
        detail = await scraping_service.get_anime_detail(url)

    # Si le scraper n'a retourné aucun épisode ou a échoué, tentative de repli pour les sources natives
    if not detail or not detail.episodes:
        if source not in ("animepahe",) and not container_source:
            alt_source = "voir-anime" if source != "voir-anime" else "french-manga"
            logger.info("Incomplete or empty sheet with %s, attempting fallback to %s: %s", source, alt_source, url)
            if alt_source == "voir-anime":
                alt_detail = await voiranime_service.get_anime_detail(url)
            else:
                alt_detail = await scraping_service.get_anime_detail(url)
            if alt_detail and alt_detail.episodes:
                detail = alt_detail
                source = alt_source

    if not detail:
        favorites = library_service.get_all_favorites()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "Impossible de charger cet anime.",
                "favorites": favorites,
                "results": None,
                "latestFrenchManga": [],
                "latestVoirAnime": [],
                "latestAnimePahe": [],
            }
        )

    detail.source = source
    detail = await tmdb_service.enrich_anime_detail(detail)
    downloaded_episodes = library_service.get_downloaded_episodes_set(url)
    watched_episodes = library_service.get_watched_episodes_set(url)
    fav = library_service.get_favorite(url)
    is_favorite = fav is not None
    auto_download = fav.autoDownload if fav else False

    return templates.TemplateResponse(
        request=request,
        name="anime-detail.html",
        context={
            "anime": detail,
            "source": source,
            "isFavorite": is_favorite,
            "autoDownload": auto_download,
            "downloadedEpisodes": downloaded_episodes,
            "watchedEpisodes": watched_episodes,
        }
    )

