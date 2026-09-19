import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from animan.services.source_settings_service import source_settings_service

logger = logging.getLogger("animan.router.sources")
router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/settings")
async def get_all_source_settings():
    """Retourne la liste de toutes les sources (natives et extensions importées)
    avec leurs paramètres respectifs.
    """
    try:
        sources = source_settings_service.get_all_sources_with_settings()
        return {
            "success": True,
            "sources": sources,
        }
    except Exception as e:
        logger.error("[router.sources] Erreur récupération sources settings: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.get("/settings/{source_id}")
async def get_source_settings(source_id: str):
    """Retourne les paramètres d'une source spécifique."""
    try:
        settings = source_settings_service.get_source_settings(source_id)
        return {
            "success": True,
            "sourceId": source_id,
            "settings": settings,
        }
    except Exception as e:
        logger.error("[router.sources] Erreur lecture source %s: %s", source_id, e)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/settings/{source_id}")
async def save_source_settings(source_id: str, request: Request):
    """Enregistre ou met à jour la configuration d'une source spécifique."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={"success": False, "error": "Format JSON invalide"})

        updated = source_settings_service.save_source_settings(source_id, body)
        return {
            "success": True,
            "sourceId": source_id,
            "settings": updated,
            "message": "Paramètres de la source mis à jour avec succès",
        }
    except Exception as e:
        logger.error("[router.sources] Erreur sauvegarde source %s: %s", source_id, e)
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
