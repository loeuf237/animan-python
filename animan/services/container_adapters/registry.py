from .anisama_adapter import AniSamaAdapter
from .franime_adapter import FrAnimeAdapter
import logging
from typing import List, Optional

from animan.services.container_adapters.base import BaseSourceAdapter
from animan.services.container_adapters.hanime_adapter import HanimeAdapter
from animan.services.container_adapters.animesama_adapter import AnimeSamaAdapter

logger = logging.getLogger(__name__)

class AdapterRegistry:
    def __init__(self):
        self._adapters: List[BaseSourceAdapter] = []
        self._register_defaults()

    def _register_defaults(self):
        self.register(HanimeAdapter())
        self.register(AniSamaAdapter())
        self.register(FrAnimeAdapter())
        self.register(AnimeSamaAdapter())

    def register(self, adapter: BaseSourceAdapter):
        self._adapters.append(adapter)

    def find_adapter(self, pkg: Optional[str], base_url: Optional[str]) -> Optional[BaseSourceAdapter]:
        for adapter in self._adapters:
            if adapter.matches(pkg, base_url):
                return adapter
        return None

adapter_registry = AdapterRegistry()
