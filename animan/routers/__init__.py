from animan.routers.anime import router as anime_router
from animan.routers.download import router as download_router
from animan.routers.library import router as library_router
from animan.routers.media import router as media_router
from animan.routers.extensions import router as extensions_router
from animan.routers.sources import router as sources_router

__all__ = [
    "anime_router",
    "download_router",
    "library_router",
    "media_router",
    "extensions_router",
    "sources_router",
]

