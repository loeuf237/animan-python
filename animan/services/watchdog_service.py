import asyncio
import logging
from animan.config import settings
from animan.services.library_service import library_service
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.download_manager import download_manager

logger = logging.getLogger("animan.watchdog")

class WatchdogService:
    def __init__(self):
        self.interval: int = settings.WATCHDOG_INTERVAL_SECONDS
        self._running: bool = False
        self._task: asyncio.Task = None

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Watchdog démarré (intervalle: %ds)", self.interval)

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        last_watchdog_time = 0.0
        while self._running:
            try:
                now = asyncio.get_event_loop().time()
                # 1. Vérification des tâches planifiées toutes les 5 secondes
                await download_manager.check_scheduled_tasks()

                # 2. Vérification des nouveaux épisodes toutes les `interval` secondes
                if now - last_watchdog_time >= self.interval:
                    last_watchdog_time = now
                    await self.check_new_episodes()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Erreur dans la boucle watchdog: %s", e)

            await asyncio.sleep(5)

    async def check_new_episodes(self) -> int:
        favorites = [f for f in library_service.get_all_favorites() if f.autoDownload]
        if not favorites:
            return 0

        total_new = 0
        logger.info("[Watchdog] Vérification de %d animé(s) en auto-download...", len(favorites))
        for fav in favorites:
            try:
                count = await self._check_anime(fav)
                total_new += count
            except Exception as e:
                logger.error("[Watchdog] Erreur pour '%s': %s", fav.title, e)
        return total_new

    async def _check_anime(self, fav) -> int:
        logger.info("[Watchdog] Vérification de '%s'...", fav.title)
        if fav.source == "voir-anime":
            detail = await voiranime_service.get_anime_detail(fav.url)
        else:
            detail = await scraping_service.get_anime_detail(fav.url)

        if not detail or not detail.episodes:
            logger.warning("[Watchdog] Aucun épisode trouvé pour '%s'", fav.title)
            return 0

        current_max = max((ep.number for ep in detail.episodes), default=0)
        last_known = fav.lastKnownEpisode

        if current_max > last_known:
            new_count = current_max - last_known
            logger.info("[Watchdog] %d nouveau(x) épisode(s) trouvé(s) pour '%s'!", new_count, fav.title)

            for ep in detail.episodes:
                if ep.number > last_known:
                    url = ep.downloadPageUrl or ep.playerUrl
                    if not url:
                        continue
                    file_name = f"{fav.title} - Episode {ep.number}.mp4"
                    logger.info("[Watchdog] Auto-download: %s Ep%d", fav.title, ep.number)
                    download_manager.start_download(
                        anime_name=fav.title,
                        episode_number=ep.number,
                        download_page_url=url,
                        file_name=file_name,
                        subtitle_url=ep.subtitleUrl,
                        download_subtitles=False,
                    )

            library_service.update_last_known_episode(fav.url, current_max)
            return new_count
        else:
            logger.info("[Watchdog] Pas de nouveauté pour '%s' (dernier: Ep%d)", fav.title, last_known)
            library_service.update_last_known_episode(fav.url, current_max)
            return 0

watchdog_service = WatchdogService()
