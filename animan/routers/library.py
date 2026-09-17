import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse

from animan.config import settings
from animan.services.download_manager import download_manager
from animan.services.library_service import library_service
from animan.services.voiranime_service import voiranime_service
from animan.services.watchdog_service import watchdog_service
from animan.security import anonymize_path, is_safe_url
from animan.templates_config import templates

logger = logging.getLogger("animan.router.library")
router = APIRouter()

# -------------------------------------------------------------------------
# Pages HTML
# -------------------------------------------------------------------------

@router.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="library.html",
        context={
            "favorites": library_service.get_all_favorites(),
            "history": library_service.get_history(),
            "source": "all",
        }
    )

@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "tasks": library_service.get_history(),
            "source": "all",
        }
    )

@router.get("/voiranime", response_class=HTMLResponse)
async def voiranime_detail_page(request: Request, url: str = Query(...)):
    if not is_safe_url(url):
        logger.warning("[voiranime] SSRF bloqué pour l'URL: %s", url)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "URL d'animé invalide ou non sécurisée",
                "favorites": library_service.get_all_favorites(),
                "results": None,
                "latestFrenchManga": [],
                "latestVoirAnime": [],
            }
        )
    logger.info("Détail voir-anime page: %s", url)
    detail = await voiranime_service.get_anime_detail(url)
    if not detail:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "Impossible de charger cet animé depuis voir-anime.to",
                "favorites": library_service.get_all_favorites(),
                "results": None,
                "latestFrenchManga": [],
                "latestVoirAnime": [],
            }
        )

    downloaded = library_service.get_downloaded_episodes_set(url)
    watched = library_service.get_watched_episodes_set(url)
    is_fav = library_service.is_favorite(url)

    return templates.TemplateResponse(
        request=request,
        name="anime-detail.html",
        context={
            "anime": detail,
            "source": "voir-anime",
            "isFavorite": is_fav,
            "downloadedEpisodes": downloaded,
            "watchedEpisodes": watched,
        }
    )

# -------------------------------------------------------------------------
# Favoris API
# -------------------------------------------------------------------------

@router.post("/api/favorites")
async def add_favorite(request: Request):
    body = await request.json()
    url = body.get("url")
    title = body.get("title", "")
    image_url = body.get("imageUrl", "")
    source = body.get("source", "french-manga")

    if not url:
        return JSONResponse(status_code=400, content={"error": "URL manquante"})

    fav = library_service.add_favorite(url, title, image_url, source)
    return {"success": True, "id": fav.id, "message": f"Ajouté aux favoris: {title}"}

@router.delete("/api/favorites")
async def remove_favorite(request: Request):
    body = await request.json()
    url = body.get("url")
    if url:
        library_service.remove_favorite(url)
    return {"success": True}

@router.get("/api/favorites/check")
async def check_favorite(url: str = Query(...)):
    return {"isFavorite": library_service.is_favorite(url)}

@router.get("/api/favorites")
async def get_favorites():
    return [f.to_dict() for f in library_service.get_all_favorites()]

@router.patch("/api/favorites/auto-download")
async def toggle_auto_download(request: Request):
    body = await request.json()
    url = body.get("url")
    auto = bool(body.get("autoDownload", False))
    if not url:
        return JSONResponse(status_code=400, content={"error": "URL manquante"})
    library_service.update_auto_download(url, auto)
    return {"success": True}

@router.delete("/api/favorites/all")
async def clear_all_favorites():
    library_service.remove_all_favorites()
    return {"success": True, "message": "Bibliothèque vidée"}

# -------------------------------------------------------------------------
# Progression API
# -------------------------------------------------------------------------

@router.post("/api/progress/watched")
async def mark_watched(request: Request):
    body = await request.json()
    anime_url = body.get("animeUrl")
    anime_name = body.get("animeName", "")
    ep_num = int(body.get("episodeNumber", 0))
    version = body.get("version", "")
    if anime_url:
        library_service.mark_as_watched(anime_url, anime_name, ep_num, version)
    return {"success": True}

@router.get("/api/progress")
async def get_progress(animeUrl: str = Query(...)):
    return [p.to_dict() for p in library_service.get_progress_for_anime(animeUrl)]

@router.get("/api/progress/downloaded")
async def get_downloaded_set(animeUrl: str = Query(...)):
    return list(library_service.get_downloaded_episodes_set(animeUrl))

# -------------------------------------------------------------------------
# Historique API
# -------------------------------------------------------------------------

@router.get("/api/history")
async def get_history(animeName: Optional[str] = Query(None)):
    tasks = library_service.get_history(animeName)
    return [t.to_task().to_dict() for t in tasks]

@router.delete("/api/history/{task_id}")
async def delete_history_entry(task_id: str):
    success = library_service.delete_task_entity(task_id)
    if success:
        return {"success": True}
    return JSONResponse(status_code=400, content={"error": "Entrée introuvable"})

@router.delete("/api/history")
async def clear_history(
    status: Optional[str] = Query(None),
    animeName: Optional[str] = Query(None)
):
    library_service.clear_history(status=status, anime_name=animeName)
    download_manager.clear_history_tasks(status=status, anime_name=animeName)
    return {"success": True, "message": "Historique nettoyé"}

# -------------------------------------------------------------------------
# voir-anime.to API
# -------------------------------------------------------------------------

@router.get("/api/voiranime/search")
async def search_voiranime(q: str = Query(...)):
    return await voiranime_service.search_anime(q)

@router.get("/api/voiranime/anime")
async def get_voiranime_detail(url: str = Query(...)):
    return await voiranime_service.get_anime_detail(url)

@router.get("/api/voiranime/download-info")
async def get_voiranime_download_info(
    episodeUrl: str = Query(...),
    server: Optional[str] = Query(None),
    quality: Optional[str] = Query(None),
):
    return await asyncio.to_thread(
        voiranime_service.extract_download_info,
        episodeUrl,
        preferred_server=server,
        preferred_quality=quality,
    )

@router.get("/api/voiranime/qualities")
async def get_voiranime_qualities(episodeUrl: str = Query(...)):
    return await asyncio.to_thread(voiranime_service.extract_video_qualities, episodeUrl)

# -------------------------------------------------------------------------
# Système & Stockage API
# -------------------------------------------------------------------------

@router.get("/api/system/storage")
async def get_system_storage():
    download_dir = Path(settings.DOWNLOAD_DIR)
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        total, used, free = shutil.disk_usage(download_dir)
        percent = round((used / total) * 100, 1) if total > 0 else 0
        return {
            "totalBytes": total,
            "usedBytes": used,
            "freeBytes": free,
            "usedPercent": percent,
            "downloadDir": anonymize_path(str(download_dir))
        }
    except Exception as e:
        logger.error("Error reading disk usage: %s", e)
        return {
            "totalBytes": 1024**4,
            "usedBytes": 300 * (1024**3),
            "freeBytes": 700 * (1024**3),
            "usedPercent": 30.0,
            "downloadDir": anonymize_path(str(download_dir))
        }

@router.post("/api/watchdog/check")
async def trigger_watchdog_check():
    try:
        new_count = await watchdog_service.check_new_episodes()
        return {"success": True, "newEpisodes": new_count}
    except Exception as e:
        logger.error("Error running manual watchdog check: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
