from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, List, Optional

from animan.models.anime import AnimeDetail, AnimeResult

logger = logging.getLogger(__name__)

class BaseSourceAdapter(ABC):
    name: str = ""
    pkg_prefixes: List[str] = []
    domains: List[str] = []

    def matches(self, pkg: Optional[str], base_url: Optional[str]) -> bool:
        p = (pkg or "").lower()
        u = (base_url or "").lower()
        if any(prefix.lower() in p for prefix in self.pkg_prefixes):
            return True
        if any(d.lower() in u for d in self.domains):
            return True
        return False

    @abstractmethod
    async def search_anime(self, query: str, container: Any) -> List[AnimeResult]:
        """Effectue une recherche spécifique via API ou SPA."""
        pass

    @abstractmethod
    async def get_latest_releases(self, container: Any) -> List[AnimeResult]:
        """Récupère les dernières sorties de la source."""
        pass

    @abstractmethod
    async def get_anime_detail(self, anime_url: str, container: Any) -> Optional[AnimeDetail]:
        """Récupère les métadonnées et la liste des épisodes."""
        pass

    @abstractmethod
    async def get_episode_sources(self, play_url: str, container: Any) -> List[Dict[str, Any]]:
        """Extrait les lecteurs vidéo et flux disponibles pour un épisode."""
        pass
