import os
import random
from typing import List, Optional, Dict
from animan.config import settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

class ProxyService:
    def __init__(self):
        self.selected_user_agent: str = "Random (Rotator)"
        self.proxies: List[str] = []
        self._load_proxies()

    def _load_proxies(self):
        # 1. From settings
        if settings.PROXIES_CONFIG:
            for p_str in settings.PROXIES_CONFIG.split(","):
                self.add_proxy_str(p_str)

        # 2. From proxies.txt
        if os.path.exists("proxies.txt"):
            try:
                with open("proxies.txt", "r", encoding="utf-8") as f:
                    for line in f:
                        self.add_proxy_str(line)
            except Exception:
                pass

    def add_proxy_str(self, p_str: str):
        p_str = p_str.strip()
        if not p_str or p_str.startswith("#"):
            return
        if p_str.startswith("socks://"):
            p_str = "socks5://" + p_str[len("socks://"):]
        elif not p_str.startswith(("http://", "https://", "socks5://", "socks5h://", "socks4://", "socks4a://")):
            p_str = f"http://{p_str}"
        if p_str not in self.proxies:
            self.proxies.append(p_str)

    def get_selected_user_agent(self) -> str:
        return self.selected_user_agent

    def set_selected_user_agent(self, ua: str):
        if ua and ua.strip():
            self.selected_user_agent = ua.strip()
        else:
            self.selected_user_agent = "Random (Rotator)"

    def get_user_agent(self) -> str:
        ua = self.selected_user_agent
        if not ua or ua == "Random (Rotator)":
            return random.choice(USER_AGENTS)
        if ua == "Chrome":
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        if ua == "Firefox":
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0"
        if ua == "Safari":
            return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
        if ua == "Edge":
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
        return ua

    def get_random_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None
        return random.choice(self.proxies)

    def get_proxy_dict(self) -> Optional[Dict[str, str]]:
        p = self.get_random_proxy()
        if p:
            return {"http://": p, "https://": p}
        return None

proxy_service = ProxyService()
