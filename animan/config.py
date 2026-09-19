import os
from pathlib import Path

HOME_DIR = Path.home()
DEFAULT_DOWNLOAD_DIR = str(HOME_DIR / "Downloads" / "Animan")
DEFAULT_DB_DIR = HOME_DIR / ".animan" / "db"
DEFAULT_DB_PATH = str(DEFAULT_DB_DIR / "animan.sqlite3")

class Settings:
    PORT: int = int(os.getenv("ANIMAN_PORT", "8080"))
    HOST: str = os.getenv("ANIMAN_HOST", "127.0.0.1")
    SSL_VERIFY: bool = os.getenv("ANIMAN_SSL_VERIFY", "true").lower() in ("1", "true", "yes")

    # Sources anime
    BASE_URL: str = os.getenv("ANIMAN_BASE_URL", "https://w16.french-manga.net")
    VOIR_ANIME_URL: str = os.getenv("ANIMAN_VOIR_ANIME_URL", "https://voir-anime.to")
    ANIMEPAHE_URL: str = os.getenv("ANIMAN_ANIMEPAHE_URL", "https://animepahe.pw")
    ANIMEPAHE_BACKUP_URLS: list = [
        "https://animepahe.pw",
        "https://animepahe.com",
        "https://animepahe.org",
        "https://animepahe.ru",
        "https://animepahe.si",
    ]
    ANIMEPAHE_COOKIE: str = os.getenv("ANIMAN_ANIMEPAHE_COOKIE", "")
    ANIMEPAHE_USER_AGENT: str = os.getenv(
        "ANIMAN_ANIMEPAHE_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0"
    )
    DEFAULT_USER_AGENT: str = os.getenv(
        "ANIMAN_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    # Téléchargement
    DOWNLOAD_DIR: str = os.getenv("ANIMAN_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR)
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("ANIMAN_MAX_CONCURRENT", "3"))
    CONNECTION_TIMEOUT: float = float(os.getenv("ANIMAN_CONNECT_TIMEOUT", "15.0"))
    READ_TIMEOUT: float = float(os.getenv("ANIMAN_READ_TIMEOUT", "30.0"))
    VOIRANIME_DEFAULT_SERVER: str = os.getenv("ANIMAN_VOIRANIME_DEFAULT_SERVER", "auto")

    # TMDB (The Movie Database)
    TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "4e44d9029b1270a757cddc766a1bcb63")
    TMDB_ENABLED: bool = os.getenv("ANIMAN_TMDB_ENABLED", "true").lower() in ("1", "true", "yes")

    # Miroirs VoirAnime
    VOIRANIME_BACKUP_URLS: list = ["https://voiranime.io", "https://voiranime.homes"]

    # Watchdog
    WATCHDOG_INTERVAL_SECONDS: int = int(os.getenv("ANIMAN_WATCHDOG_INTERVAL", "3600"))

    # Database
    DATABASE_PATH: str = os.getenv("ANIMAN_DB_PATH", DEFAULT_DB_PATH)
    DATABASE_URL: str = f"sqlite:///{DATABASE_PATH}"

    # Proxies
    PROXIES_CONFIG: str = os.getenv("ANIMAN_PROXIES", "")

    # Project directories
    BASE_DIR: Path = Path(__file__).resolve().parent
    TEMPLATES_DIR: Path = BASE_DIR / "templates"
    STATIC_DIR: Path = BASE_DIR / "static"

settings = Settings()

# Ensure directories exist
Path(settings.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
