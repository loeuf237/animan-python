import json
import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request, Header, HTTPException, Response
from fastapi.responses import StreamingResponse, FileResponse

import httpx
from animan.config import settings
from animan.security import is_safe_url, is_safe_path
from animan.services.download_manager import download_manager
from animan.services.proxy_service import proxy_service

logger = logging.getLogger("animan.router.media")
router = APIRouter()

IMAGE_CACHE: Dict[str, tuple[bytes, str]] = {}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 Mo max pour prévenir les attaques OOM

@router.get("/api/media/image-proxy")
async def proxy_image(url: str):
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL d'image invalide")

    # Protection SSRF
    if not is_safe_url(url):
        logger.warning("SSRF bloqué sur image-proxy pour l'URL: %s", url)
        raise HTTPException(status_code=400, detail="URL d'image non autorisée ou non sécurisée")

    if url in IMAGE_CACHE:
        content, ctype = IMAGE_CACHE[url]
        return Response(content=content, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})

    try:
        referer = "https://voir-anime.to/" if any(d in url for d in ["voir-anime", "voembed", "vidmoly"]) else "https://french-manga.net/"
        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=settings.SSL_VERIFY) as client:
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
