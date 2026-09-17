import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request, Header, HTTPException, Response, Query
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse

import httpx
from animan.config import settings
from animan.security import is_safe_url, is_safe_path
from animan.services.download_manager import download_manager
from animan.services.proxy_service import proxy_service
from animan.services.library_service import library_service
from animan.services.voiranime_service import voiranime_service
from animan.services.scraping_service import scraping_service

logger = logging.getLogger("animan.router.media")
router = APIRouter()

IMAGE_CACHE: Dict[str, tuple[bytes, str]] = {}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 Mo max pour prévenir les attaques OOM

def _get_media_async_client(timeout: float = 10.0) -> httpx.AsyncClient:
    try:
        return httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=settings.SSL_VERIFY)
    except Exception as e:
        logger.warning("[media] Erreur client HTTP proxy: %s - repli trust_env=False", e)
        return httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=settings.SSL_VERIFY, trust_env=False)

@router.get("/api/media/image-proxy")
async def proxy_image(url: str):
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL d'image invalide")

    # Protection SSRF
    if not is_safe_url(url):
        logger.warning("SSRF bloqué sur image-proxy pour l'URL: %s", url)
        raise HTTPException(status_code=400, detail="URL d'image non autorisée ou non sécurisée")

    # Cache mémoire simple (évite de retélécharger à chaque requête)
    if url in IMAGE_CACHE:
        content, ctype = IMAGE_CACHE[url]
        return Response(content=content, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})

    try:
        if "themoviedb.org" in url or "tmdb.org" in url:
            referer = "https://www.themoviedb.org/"
        elif any(d in url for d in ["voir-anime", "voembed", "vidmoly"]):
            referer = "https://voir-anime.to/"
        else:
            referer = "https://french-manga.net/"
        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        async with _get_media_async_client(timeout=10.0) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    raise HTTPException(status_code=resp.status_code, detail="Image inaccessible")

                ctype = resp.headers.get("content-type", "image/jpeg")
                if not (ctype.startswith("image/") or ctype == "application/octet-stream"):
                    raise HTTPException(status_code=400, detail="Le contenu distant n'est pas une image valide")

                clength = resp.headers.get("content-length")
                if clength and int(clength) > MAX_IMAGE_SIZE:
                    raise HTTPException(status_code=413, detail="Image trop volumineuse (max 10 Mo)")

                content = bytearray()
                async for chunk in resp.aiter_bytes(65536):
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_SIZE:
                        raise HTTPException(status_code=413, detail="Image trop volumineuse (max 10 Mo)")

                final_bytes = bytes(content)
                if len(IMAGE_CACHE) > 100:
                    IMAGE_CACHE.pop(next(iter(IMAGE_CACHE)))
                IMAGE_CACHE[url] = (final_bytes, ctype)

                return Response(content=final_bytes, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})
    except HTTPException:
        raise
    except Exception as e:
        logger.debug("Erreur image-proxy: %s", e)
        raise HTTPException(status_code=502, detail="Erreur proxy image")

def parse_subtitle_paths(path_field: Optional[str]) -> List[str]:
    if not path_field:
        return []
    if path_field.startswith("[") and path_field.endswith("]"):
        try:
            return json.loads(path_field)
        except Exception:
            pass
    return [path_field]

@router.get("/api/media/stream/resolve")
async def resolve_stream(
    animeName: str = Query(...),
    episodeNumber: int = Query(...),
    episodeUrl: str = Query(...),
    animeUrl: Optional[str] = Query(""),
    version: Optional[str] = Query(""),
    source: Optional[str] = Query("voir-anime"),
    server: Optional[str] = Query(None),
    quality: Optional[str] = Query(None),
):
    """
    Résout le flux de lecture pour un épisode :
    1. Si l'épisode est déjà téléchargé sur le disque dur, renvoie le flux local (/api/media/stream/{task_id}).
    2. S'il n'est pas téléchargé, résout le flux en ligne direct sur les serveurs d'hébergement.
    """
    logger.info("Résolution streaming: %s - Ep %s (source=%s, server=%s, quality=%s)",
                animeName, episodeNumber, source, server, quality)

    # 1. Vérification si l'épisode est déjà téléchargé sur le disque dur
    local_task = library_service.find_downloaded_episode(
        anime_name=animeName,
        episode_number=episodeNumber,
        version=version or "",
        episode_url=episodeUrl,
    )

    if local_task:
        logger.info("Épisode trouvé sur le disque dur: %s (task_id=%s)", local_task.savePath, local_task.id)
        # Récupérer les sous-titres locaux s'ils existent
        subtitles = []
        try:
            subtitles = await get_subtitles_list(local_task.id)
        except Exception:
            pass

        return {
            "success": True,
            "isDownloaded": True,
            "sourceType": "local",
            "taskId": local_task.id,
            "streamUrl": f"/api/media/stream/{local_task.id}",
            "filePath": local_task.savePath,
            "title": f"{animeName} - Épisode {episodeNumber}",
            "subtitles": subtitles,
            "serverType": "Disque dur (Local)",
            "selectedQuality": "Original (Local)",
            "qualities": {},
        }

    # 2. Épisode non téléchargé -> Résolution du streaming direct sur les serveurs d'hébergement
    logger.info("Épisode non téléchargé sur disque dur. Extraction du flux distant...")
    video_url = ""
    server_type = server or "auto"
    selected_quality = quality or "auto"
    qualities_dict: Dict[str, str] = {}
    tracks: List[Dict[str, Any]] = []

    if source == "voir-anime":
        pref_srv = server if (server and server != "auto") else None
        pref_q = quality if (quality and quality != "auto") else None
        info = voiranime_service.extract_download_info(
            episodeUrl,
            preferred_server=pref_srv,
            preferred_quality=pref_q,
        )
        video_url = info.get("videoUrl") or ""
        server_type = info.get("serverType") or server_type
        selected_quality = info.get("selectedQuality") or selected_quality
        raw_qualities = info.get("videoQualities")
        if isinstance(raw_qualities, str):
            try:
                qualities_dict = json.loads(raw_qualities)
            except Exception:
                qualities_dict = {}
        elif isinstance(raw_qualities, dict):
            qualities_dict = raw_qualities

        sub_url = info.get("subtitleUrl")
        if sub_url:
            tracks.append({
                "kind": "captions",
                "label": "Français",
                "srclang": "fr",
                "src": f"/api/media/subtitle-proxy?url={urllib.parse.quote(sub_url)}",
                "default": True,
            })
    else:
        # french-manga
        info = scraping_service.extract_download_info(episodeUrl)
        video_url = info.get("videoUrl") or info.get("directUrl") or ""
        server_type = "vidzy"
        sub_url = info.get("subtitleUrl")
        if sub_url:
            tracks.append({
                "kind": "captions",
                "label": "Français",
                "srclang": "fr",
                "src": f"/api/media/subtitle-proxy?url={urllib.parse.quote(sub_url)}",
                "default": True,
            })

    if not video_url:
        logger.warning("Aucun flux vidéo direct trouvé pour l'épisode distant: %s", episodeUrl)
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "Impossible de trouver un flux vidéo direct sur les serveurs d'hébergement.",
                "isDownloaded": False,
                "sourceType": "remote",
                "serverType": server_type,
            }
        )

    return {
        "success": True,
        "isDownloaded": False,
        "sourceType": "remote",
        "streamUrl": video_url,
        "serverType": server_type,
        "selectedQuality": selected_quality,
        "qualities": qualities_dict,
        "title": f"{animeName} - Épisode {episodeNumber}",
        "subtitles": tracks,
    }

@router.get("/api/media/stream/{task_id}")
async def stream_video(task_id: str, request: Request, range: Optional[str] = Header(None)):
    task = download_manager.get_task(task_id)
    if not task or not task.savePath:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")

    file_path = Path(task.savePath)
    # Protection Path Traversal
    if not is_safe_path(file_path):
        logger.warning("Path Traversal bloqué sur streaming: %s", file_path)
        raise HTTPException(status_code=403, detail="Accès refusé : fichier hors du répertoire autorisé")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fichier vidéo introuvable sur le disque")

    file_size = file_path.stat().st_size
    content_type = "video/x-matroska" if file_path.suffix == ".mkv" else "video/mp4"

    if not range:
        def iter_full():
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            iter_full(),
            media_type=content_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            }
        )

    # HTTP Range handling: "bytes=0-1024" or "bytes=1024-"
    range_match = re.search(r"bytes=(\d+)-(\d*)", range)
    if not range_match:
        raise HTTPException(status_code=416, detail="Range header non valide")

    start = int(range_match.group(1))
    end = int(range_match.group(2)) if range_match.group(2) else file_size - 1

    if start >= file_size or end >= file_size or start > end:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"}
        )

    content_length = end - start + 1

    def iter_range():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = content_length
            chunk_size = 65536
            while remaining > 0:
                to_read = min(chunk_size, remaining)
                data = f.read(to_read)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iter_range(),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
        }
    )

@router.get("/api/media/subtitles/{task_id}")
async def get_subtitles_list(task_id: str):
    task = download_manager.get_task(task_id)
    if not task or not task.savePathSubtitle:
        return []

    paths = parse_subtitle_paths(task.savePathSubtitle)
    result = []

    video_stem = Path(task.savePath).stem if task.savePath else ""
    for idx, p in enumerate(paths):
        sf = Path(p)
        if sf.exists():
            lbl = sf.name.replace(video_stem, "").strip(".")
            if not lbl:
                lbl = f"Sous-titres {idx + 1}"
            lang = "fr" if "fr" in lbl.lower() else "und"
            result.append({
                "label": lbl,
                "srclang": lang,
                "src": f"/api/media/subtitle/{task_id}/{idx}",
            })

    return result

@router.get("/api/media/subtitle/{task_id}")
async def stream_subtitle_default(task_id: str):
    return await stream_subtitle_at_index(task_id, 0)

@router.get("/api/media/subtitle/{task_id}/{index}")
async def stream_subtitle_at_index(task_id: str, index: int):
    task = download_manager.get_task(task_id)
    if not task or not task.savePathSubtitle:
        raise HTTPException(status_code=404, detail="Sous-titres introuvables")

    paths = parse_subtitle_paths(task.savePathSubtitle)
    if index < 0 or index >= len(paths):
        raise HTTPException(status_code=404, detail="Index de sous-titre invalide")

    file_path = Path(paths[index])
    if not is_safe_path(file_path):
        logger.warning("Path Traversal bloqué sur sous-titres: %s", file_path)
        raise HTTPException(status_code=403, detail="Accès refusé : fichier de sous-titres hors du répertoire autorisé")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fichier de sous-titres introuvable")

    content_type = "text/vtt"
    if file_path.suffix == ".srt":
        content_type = "text/srt"
    elif file_path.suffix == ".ass":
        content_type = "text/ass"

    return FileResponse(path=file_path, media_type=content_type)

@router.get("/api/media/subtitle-proxy")
async def proxy_subtitle(url: str = Query(...)):
    """
    Proxy pour sous-titres distants avec en-têtes CORS universels pour HTML5 <track>.
    """
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL de sous-titre invalide")
    if not is_safe_url(url):
        logger.warning("SSRF bloqué sur subtitle-proxy: %s", url)
        raise HTTPException(status_code=400, detail="URL de sous-titre non autorisée")

    headers = {
        "User-Agent": proxy_service.get_user_agent(),
        "Referer": "https://voir-anime.to/" if "voir-anime" in url else "https://vidzy.org/",
    }
    try:
        async with _get_media_async_client(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Sous-titres distants inaccessibles")
            content = resp.text
            content_type = "text/vtt; charset=utf-8" if "WEBVTT" in content.upper() else "text/plain; charset=utf-8"
            return Response(
                content=content,
                media_type=content_type,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Cache-Control": "public, max-age=86400",
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.debug("Erreur subtitle-proxy: %s", e)
        raise HTTPException(status_code=502, detail="Erreur lors de la récupération des sous-titres")

