import asyncio
import logging
from typing import List, Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from animan.models.anime import AnimeResult
from animan.security import is_safe_url
from animan.services.library_service import library_service
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.tmdb_service import tmdb_service
from animan.templates_config import templates

logger = logging.getLogger("animan.router.anime")
router = APIRouter()

def detect_source_from_url(url: str, fallback: str = "french-manga") -> str:
    """Détecte automatiquement la source légitime d'un anime d'après son URL."""
    if not url:
        return fallback
    u = url.lower()
    if "voir-anime" in u or "voiranime" in u:
        return "voir-anime"
    if "french-manga" in u:
        return "french-manga"
    return fallback

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    favorites = library_service.get_all_favorites()
    latest_fm = await scraping_service.get_latest_releases()
    latest_va = await voiranime_service.get_latest_releases()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "favorites": favorites,
            "latestFrenchManga": latest_fm,
            "latestVoirAnime": latest_va,
            "results": None,
            "query": "",
            "source": "french-manga",
        }
    )

@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query(..., alias="q"),
    source: str = Query("french-manga", alias="source")
):
    norm_source = (source or "french-manga").lower().strip()
    logger.info("Recherche [%s]: %s", norm_source, q)

    results: List[AnimeResult] = []
    if norm_source == "all":
        # Multi-sources ordonnées alphabétiquement: 1) French-Manga, 2) VoirAnime
        fm_task = scraping_service.search_anime(q)
        va_task = voiranime_service.search_anime(q)
        fm_res, va_res = await asyncio.gather(fm_task, va_task, return_exceptions=True)
        if not isinstance(fm_res, Exception) and fm_res:
            for item in fm_res:
                item.source = "french-manga"
            results.extend(fm_res)
        if not isinstance(va_res, Exception) and va_res:
            for item in va_res:
                item.source = "voir-anime"
            results.extend(va_res)
    elif norm_source == "voir-anime":
        va_res = await voiranime_service.search_anime(q)
        for item in va_res:
            item.source = "voir-anime"
        results = va_res
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
            "latestFrenchManga": [],
            "latestVoirAnime": [],
        }
    )

@router.get("/api/search", response_model=List[AnimeResult])
async def search_api(
    q: str = Query(..., alias="q"),
    source: str = Query("all", alias="source")
):
    norm_source = (source or "all").lower().strip()
    if norm_source == "all":
        # Multi-sources ordonnées alphabétiquement: 1) French-Manga, 2) VoirAnime
        fm_task = scraping_service.search_anime(q)
        va_task = voiranime_service.search_anime(q)
        fm_res, va_res = await asyncio.gather(fm_task, va_task, return_exceptions=True)
        results: List[AnimeResult] = []
        if not isinstance(fm_res, Exception) and fm_res:
            for item in fm_res:
                item.source = "french-manga"
            results.extend(fm_res)
        if not isinstance(va_res, Exception) and va_res:
            for item in va_res:
                item.source = "voir-anime"
            results.extend(va_res)
        return results
    elif norm_source == "voir-anime":
        results = await voiranime_service.search_anime(q)
        for item in results:
            item.source = "voir-anime"
        return results
    else:
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
    logger.info("Détail anime demandé [%s]: %s", source, url)
    if not is_safe_url(url):
        logger.warning("SSRF bloqué sur détail anime: %s", url)
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
            }
        )

    # Détection automatique et correction de la source d'après l'URL
    detected_source = detect_source_from_url(url, fallback=source)
    if detected_source != source:
        logger.info("Source d'URL corrigée: [%s -> %s] pour %s", source, detected_source, url)
        source = detected_source

    if source == "voir-anime":
        detail = await voiranime_service.get_anime_detail(url)
    else:
        detail = await scraping_service.get_anime_detail(url)

    # Si le scraper n'a retourné aucun épisode ou a échoué, tentative avec l'autre scraper
    if not detail or not detail.episodes:
        alt_source = "voir-anime" if source != "voir-anime" else "french-manga"
        logger.info("Fiche incomplète ou vide avec %s, tentative de repli sur %s: %s", source, alt_source, url)
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

