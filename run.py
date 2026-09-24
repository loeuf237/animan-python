import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from animan.config import settings
from animan.database import init_db
from animan.services.download_manager import download_manager
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.animepahe_service import animepahe_service
from animan.services.watchdog_service import watchdog_service
from animan.services.i18n_service import current_request_lang, detect_client_language
from animan.routers import (
    anime_router,
    download_router,
    library_router,
    media_router,
    extensions_router,
    sources_router,
    i18n_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("animan")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Animan Python v2.0...")
    # 1. Initialize SQLite database
    init_db()
    # 2. Restore unfinished download tasks
    download_manager.init_from_db()
    # 3. Start Watchdog service
    watchdog_service.start()
    # 4. Pre-load release feeds (background with concurrency lock)
    asyncio.create_task(scraping_service._safe_refresh_cache())
    asyncio.create_task(voiranime_service._safe_refresh_cache())
    asyncio.create_task(animepahe_service._safe_refresh_cache())

    logger.info("Application ready at http://%s:%d", settings.HOST, settings.PORT)
    yield

    logger.info("Stopping Animan...")
    watchdog_service.stop()

app = FastAPI(
    title="Animan",
    description="Anime Downloader - High performance anime streaming & downloads",
    version="2.0.0",
    lifespan=lifespan
)

@app.middleware("http")
async def i18n_middleware(request: Request, call_next):
    lang = request.query_params.get("lang")
    if not lang or lang not in ("fr", "en"):
        lang = request.cookies.get("animan_lang")
    if not lang or lang not in ("fr", "en"):
        lang = detect_client_language(request.headers.get("accept-language"))
    
    token = current_request_lang.set(lang)
    request.state.lang = lang
    try:
        response = await call_next(request)
    finally:
        current_request_lang.reset(token)

    if "lang" in request.query_params and request.query_params["lang"] in ("fr", "en"):
        response.set_cookie(key="animan_lang", value=lang, max_age=31536000, httponly=False, samesite="lax")
    elif not request.cookies.get("animan_lang"):
        response.set_cookie(key="animan_lang", value=lang, max_age=31536000, httponly=False, samesite="lax")
    return response

@app.middleware("http")
async def security_headers_and_csrf_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
        if sec_fetch_site == "cross-site":
            logger.warning("CSRF blocked: cross-site sec-fetch-site for %s %s", request.method, request.url.path)
            return JSONResponse(status_code=403, content={"error": "Cross-site request blocked"})

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source_url = origin or referer
        if source_url:
            try:
                from urllib.parse import urlparse
                parsed_source = urlparse(source_url)
                source_host = (parsed_source.hostname or "").lower()
                allowed_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "testserver", settings.HOST.lower()}
                if source_host and source_host not in allowed_hosts:
                    logger.warning("CSRF blocked: Origin '%s' rejected for %s %s", source_url, request.method, request.url.path)
                    return JSONResponse(status_code=403, content={"error": "Forbidden origin (CSRF blocked)"})
            except Exception:
                return JSONResponse(status_code=403, content={"error": "Invalid origin"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response

# Montage des fichiers statiques
static_dir = settings.STATIC_DIR
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")
app.mount("/img", StaticFiles(directory=str(static_dir / "img")), name="img")

# Enregistrement des routeurs
app.include_router(anime_router)
app.include_router(download_router)
app.include_router(library_router)
app.include_router(media_router)
app.include_router(extensions_router)
app.include_router(sources_router)
app.include_router(i18n_router)

if __name__ == "__main__":
    import os
    reload_enabled = os.getenv("ANIMAN_RELOAD", "true").lower() in ("1", "true", "yes")
    uvicorn.run(
        "run:app" if reload_enabled else app,
        host=settings.HOST,
        port=settings.PORT,
        log_level="info",
        reload=reload_enabled,
        reload_dirs=["animan"] if reload_enabled else None,
        timeout_keep_alive=30,
    )

