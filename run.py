import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from animan.config import settings
from animan.database import init_db
from animan.services.download_manager import download_manager
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.watchdog_service import watchdog_service
from animan.routers import anime_router, download_router, library_router, media_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("animan")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Démarrage d'Animan Python v2.0...")
    # 1. Initialiser la base SQLite
    init_db()
    # 2. Restaurer les tâches non terminées
    download_manager.init_from_db()
    # 3. Démarrer le Watchdog
    watchdog_service.start()
    # 4. Pré-charger les flux de sorties
    asyncio.create_task(scraping_service.refresh_cache())
    asyncio.create_task(voiranime_service.refresh_cache())

    logger.info("Application prête sur http://%s:%d", settings.HOST, settings.PORT)
    yield

    logger.info("Arrêt d'Animan...")
    watchdog_service.stop()

app = FastAPI(
    title="Animan",
    description="Anime Downloader - Téléchargeur d'animés (french-manga.net + voir-anime.to)",
    version="2.0.0",
    lifespan=lifespan
)

# Montage des fichiers statiques
static_dir = settings.STATIC_DIR
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")

# Enregistrement des routeurs
app.include_router(anime_router)
app.include_router(download_router)
app.include_router(library_router)
app.include_router(media_router)

if __name__ == "__main__":
    uvicorn.run(
        "run:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level="info"
    )
