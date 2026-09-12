import logging
from typing import Optional, List
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from animan.config import settings
from animan.models.anime import AnimeResult
from animan.security import is_safe_url
from animan.services.library_service import library_service
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.templates_config import templates

logger = logging.getLogger("animan.router.anime")
router = APIRouter()

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
    logger.info("Recherche [%s]: %s", source, q)
    if source == "voir-anime":
        results = await voiranime_service.search_anime(q)
    else:
        results = await scraping_service.search_anime(q)
        if not results:
            logger.info("Aucun résultat sur french-manga, fallback vers voir-anime...")
            results = await voiranime_service.search_anime(q)
            if results:
                source = "voir-anime"

    favorites = library_service.get_all_favorites()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "results": results,
            "query": q,
            "source": source,
            "favorites": favorites,
            "latestFrenchManga": [],
            "latestVoirAnime": [],
        }
    )

@router.get("/api/search", response_model=List[AnimeResult])
async def search_api(
    q: str = Query(..., alias="q"),
    source: str = Query("french-manga", alias="source")
):
    if source == "voir-anime":
        return await voiranime_service.search_anime(q)
    results = await scraping_service.search_anime(q)
    if not results:
        results = await voiranime_service.search_anime(q)
    return results

@router.get("/anime", response_class=HTMLResponse)
async def anime_detail(
    request: Request,
    url: str = Query(..., alias="url"),
    source: str = Query("french-manga", alias="source")
):
    logger.info("Détail anime [%s]: %s", source, url)
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

    if source == "voir-anime":
        detail = await voiranime_service.get_anime_detail(url)
    else:
        detail = await scraping_service.get_anime_detail(url)

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

    downloaded_episodes = library_service.get_downloaded_episodes_set(url)
    watched_episodes = library_service.get_watched_episodes_set(url)
    is_favorite = library_service.is_favorite(url)

    return templates.TemplateResponse(
        request=request,
        name="anime-detail.html",
        context={
            "anime": detail,
            "source": source,
            "isFavorite": is_favorite,
            "downloadedEpisodes": downloaded_episodes,
            "watchedEpisodes": watched_episodes,
        }
    )
