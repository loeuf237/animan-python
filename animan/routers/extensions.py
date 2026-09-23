import logging
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse

from animan.services.extension_service import extension_service
from animan.templates_config import templates

logger = logging.getLogger("animan.router.extensions")
router = APIRouter()


@router.get("/extensions", response_class=HTMLResponse)
async def extensions_page(
    request: Request,
    q: Optional[str] = Query(None, alias="q"),
    lang: Optional[str] = Query(None, alias="lang")
):
    """Page de gestion des magasins d'extensions et des sources Aniyomi."""
    active_repo = extension_service.get_active_repository()
    extensions = extension_service.get_visible_extensions(query=q, lang=lang) if active_repo else []
    
    enabled_count = sum(1 for e in extensions if e.get("is_enabled"))
    total_count = len(extensions)

    return templates.TemplateResponse(
        request=request,
        name="extensions.html",
        context={
            "active_repo": active_repo,
            "extensions": extensions,
            "enabled_count": enabled_count,
            "total_count": total_count,
            "query": q or "",
            "selected_lang": lang or "all",
        }
    )


@router.post("/api/extensions/import-repo")
async def import_repo_api(payload: dict = Body(...)):
    """Importe massivement un nouveau magasin d'extensions."""
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Veuillez fournir une URL de magasin valide.")

    try:
        result = await extension_service.import_repository(url)
        return JSONResponse(content=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("[router.extensions] Error importing repository: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error during import: {e}")


@router.post("/api/extensions/{ext_id}/toggle")
async def toggle_extension_api(ext_id: int, payload: dict = Body(...)):
    """Active ou désactive une extension à la demande de l'utilisateur."""
    enabled = bool(payload.get("enabled", False))
    try:
        result = await extension_service.toggle_extension(ext_id, enabled)
        return JSONResponse(content=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("[router.extensions] Error toggling extension %d: %s", ext_id, e)
        raise HTTPException(status_code=500, detail=f"Error toggling extension: {e}")


@router.get("/api/extensions/list")
async def list_extensions_api(
    q: Optional[str] = Query(None),
    lang: Optional[str] = Query(None),
    enabled_only: bool = Query(False)
):
    """Retourne la liste JSON des extensions visibles (uniquement du dernier magasin actif)."""
    active_repo = extension_service.get_active_repository()
    extensions = extension_service.get_visible_extensions(query=q, lang=lang, enabled_only=enabled_only) if active_repo else []
    return JSONResponse(content={
        "active_repo": active_repo,
        "count": len(extensions),
        "extensions": extensions
    })
