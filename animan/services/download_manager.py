import asyncio
import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

import httpx

from animan.config import settings
from animan.models.download_task import DownloadTask, DownloadStatus, format_bytes
from animan.services.library_service import library_service
from animan.services.proxy_service import proxy_service
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.verification_service import verification_service, VerificationResult

logger = logging.getLogger("animan.download_manager")

class ResolvedVideoInfo:
    def __init__(self):
        self.direct_url: str = ""
        self.subtitle_url: str = ""
        self.subtitles_json: str = "[]"
        self.size: int = -1
        self.formatted_size: str = "Taille inconnue"
        self.server_type: str = "unknown"
        self.video_chunks_json: str = "[]"
        self.video_qualities_json: str = "{}"
        self.available_servers: List[str] = []
        self.selected_server: str = ""
        self.selected_quality: str = ""

class DownloadManagerService:
    def __init__(self):
        self.download_dir: str = settings.DOWNLOAD_DIR
        self.max_concurrent_downloads: int = settings.MAX_CONCURRENT_DOWNLOADS
        self.global_speed_limit: int = 0
        self.plex_organization: bool = False
        self.voiranime_default_server: str = settings.VOIRANIME_DEFAULT_SERVER

        self.tasks: Dict[str, DownloadTask] = {}
        self.task_order: List[str] = []
        self.sse_subscribers: List[asyncio.Queue] = []
        self.resolved_info_cache: Dict[str, ResolvedVideoInfo] = {}

        self._active_workers: int = 0
        self._lock = asyncio.Lock()
        self._info_semaphore = asyncio.Semaphore(4)

    def _trigger_process_queue(self):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.process_queue())
        except RuntimeError:
            pass

    def init_from_db(self):
        try:
            unfinished = library_service.get_unfinished_tasks()
            for entity in unfinished:
                task = entity.to_task()
                if task.status in [DownloadStatus.DOWNLOADING, DownloadStatus.RETRYING]:
                    task.status = DownloadStatus.PAUSED
                    task.speed = 0
                    library_service.save_task(task)
                self.tasks[task.id] = task
                self.task_order.append(task.id)
            logger.info("Chargé %d tâche(s) non terminée(s) depuis la base au démarrage", len(self.tasks))
        except Exception as e:
            logger.error("Erreur chargement tâches non terminées: %s", e)

    # -------------------------------------------------------------------------
    # Paramètres et Configuration
    # -------------------------------------------------------------------------

    def get_settings(self) -> Dict[str, Any]:
        return {
            "maxConcurrentDownloads": self.max_concurrent_downloads,
            "globalSpeedLimit": self.global_speed_limit,
            "plexOrganization": self.plex_organization,
            "selectedUserAgent": proxy_service.get_selected_user_agent(),
            "voiranimeDefaultServer": self.voiranime_default_server,
            "ffmpegAvailable": self.is_ffmpeg_available(),
        }

    def update_settings(
        self,
        max_concurrent: int,
        global_limit: int,
        plex_org: bool,
        user_agent: Optional[str] = None,
        voiranime_default_server: Optional[str] = None,
    ):
        self.max_concurrent_downloads = max(1, max_concurrent)
        self.set_global_speed_limit(global_limit)
        self.plex_organization = plex_org
        if user_agent:
            proxy_service.set_selected_user_agent(user_agent)
        if voiranime_default_server:
            self.voiranime_default_server = voiranime_default_server
            voiranime_service.default_server = voiranime_default_server
        self._trigger_process_queue()

    def set_global_speed_limit(self, limit_bytes_per_sec: int):
        self.global_speed_limit = max(0, limit_bytes_per_sec)
        for t in self.tasks.values():
            if t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PENDING]:
                t.maxSpeedLimit = self.global_speed_limit

    def set_task_speed_limit(self, task_id: str, limit: int) -> bool:
        task = self.tasks.get(task_id)
        if task:
            task.maxSpeedLimit = max(0, limit)
            self.broadcast_update(task)
            return True
        return False

    # -------------------------------------------------------------------------
    # Vérification Doublon & Taille distante
    # -------------------------------------------------------------------------

    def check_existing_file(self, anime_name: str, file_name: str, episode_number: int) -> Optional[Path]:
        if not anime_name or not file_name:
            return None

        clean_anime = self.sanitize_file_name(anime_name)
        if self.plex_organization:
            anime_dir = Path(self.download_dir) / clean_anime / "Season 01"
            ext = Path(file_name).suffix or ".mp4"
            final_name = f"{clean_anime} - S01E{episode_number:02d}{ext}"
        else:
            anime_dir = Path(self.download_dir) / clean_anime
            final_name = self.sanitize_file_name(file_name)

        exact_file = anime_dir / final_name
        if exact_file.exists():
            return exact_file

        base_name = re.sub(r"\.(mp4|mkv|avi)$", "", final_name)
        for ext in [".mp4", ".mkv", ".avi"]:
            alt = anime_dir / f"{base_name}{ext}"
            if alt.exists():
                return alt

        return None

    async def get_remote_file_size(self, url: str) -> int:
        if not url:
            return -1
        try:
            headers = {
                "User-Agent": proxy_service.get_user_agent(),
                "Referer": "https://vidzy.live/",
            }
            proxy = proxy_service.get_random_proxy()
            async with httpx.AsyncClient(headers=headers, proxy=proxy, timeout=10.0, follow_redirects=True, verify=False) as client:
                resp = await client.head(url)
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit() and int(cl) > 0:
                    return int(cl)

                # Essai Range: bytes=0-0
                range_resp = await client.get(url, headers={"Range": "bytes=0-0"})
                cr = range_resp.headers.get("Content-Range")
                if cr and "/" in cr:
                    total_str = cr.split("/")[-1].strip()
                    if total_str.isdigit():
                        return int(total_str)
                cl2 = range_resp.headers.get("Content-Length")
                if cl2 and cl2.isdigit():
                    return int(cl2)
        except Exception:
            pass
        return -1

    async def get_or_resolve_episode_info(
        self,
        download_page_url: str,
        preferred_server: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ResolvedVideoInfo]:
        if not download_page_url:
            return None
        cache_key = f"{download_page_url}::{preferred_server or ''}::{preferred_quality or ''}"
        if cache_key in self.resolved_info_cache:
            return self.resolved_info_cache[cache_key]

        async with self._info_semaphore:
            if cache_key in self.resolved_info_cache:
                return self.resolved_info_cache[cache_key]

            try:
                info = ResolvedVideoInfo()
                is_voir_anime = "voir-anime" in download_page_url

                if is_voir_anime:
                    eff_server = preferred_server or self.voiranime_default_server
                    dl_info = await asyncio.to_thread(
                        voiranime_service.extract_download_info,
                        download_page_url,
                        preferred_server=eff_server,
                        preferred_quality=preferred_quality,
                    )
                    info.server_type = dl_info.get("serverType", "unknown")
                    info.video_chunks_json = dl_info.get("videoChunks", "[]")
                    info.video_qualities_json = dl_info.get("videoQualities", "{}")
                    raw_avail = dl_info.get("availableServers", "[]")
                    if isinstance(raw_avail, str):
                        try:
                            info.available_servers = json.loads(raw_avail)
                        except Exception:
                            info.available_servers = []
                    elif isinstance(raw_avail, list):
                        info.available_servers = raw_avail
                    info.selected_server = dl_info.get("serverType", "")
                    info.selected_quality = dl_info.get("selectedQuality", "")
                else:
                    dl_info = await asyncio.to_thread(scraping_service.extract_download_info, download_page_url)
                    info.server_type = "vidzy"

                info.direct_url = dl_info.get("videoUrl", "")
                info.subtitle_url = dl_info.get("subtitleUrl", "")
                info.subtitles_json = dl_info.get("subtitles", "[]")

                if info.direct_url:
                    info.size = await self.get_remote_file_size(info.direct_url)

                if info.server_type == "myTV" and info.video_chunks_json:
                    try:
                        chunks = json.loads(info.video_chunks_json)
                        total_sz = 0
                        for c_url in chunks:
                            sz = await self.get_remote_file_size(c_url)
                            if sz > 0:
                                total_sz += sz
                        if total_sz > 0:
                            info.size = total_sz
                    except Exception:
                        pass

                info.formatted_size = format_bytes(info.size) if info.size > 0 else "Taille inconnue"
                self.resolved_info_cache[cache_key] = info
                self.resolved_info_cache[download_page_url] = info
                return info
            except Exception as e:
                logger.error("Erreur get_or_resolve_episode_info: %s", e)
                return None

    # -------------------------------------------------------------------------
    # Démarrage des téléchargements
    # -------------------------------------------------------------------------

    def start_download(
        self,
        anime_name: str,
        episode_number: int,
        download_page_url: str,
        file_name: str,
        subtitle_url: Optional[str] = None,
        scheduled_start_time: Optional[datetime] = None,
        speed_limit: int = 0,
        download_subtitles: bool = False,
        selected_server: Optional[str] = None,
        selected_quality: Optional[str] = None,
    ) -> DownloadTask:
        cache_key = f"{download_page_url}::{selected_server or ''}::{selected_quality or ''}"
        cached = self.resolved_info_cache.get(cache_key) or self.resolved_info_cache.get(download_page_url)
        initial_total_bytes = cached.size if cached and cached.size > 0 else 0
        resolved_subs = cached.subtitles_json if cached else "[]"

        now = datetime.now(timezone.utc) if (scheduled_start_time and scheduled_start_time.tzinfo) else datetime.now()
        is_scheduled = scheduled_start_time is not None and scheduled_start_time > now
        status = DownloadStatus.SCHEDULED if is_scheduled else DownloadStatus.PENDING

        clean_anime = self.sanitize_file_name(anime_name)
        if self.plex_organization:
            anime_dir = Path(self.download_dir) / clean_anime / "Season 01"
            ext = Path(file_name).suffix or ".mp4"
            final_file_name = f"{clean_anime} - S01E{episode_number:02d}{ext}"
        else:
            anime_dir = Path(self.download_dir) / clean_anime
            final_file_name = self.sanitize_file_name(file_name)

        anime_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(anime_dir / final_file_name)

        task = DownloadTask(
            animeName=anime_name,
            episodeNumber=episode_number,
            fileName=final_file_name,
            fileUrl=download_page_url,
            savePath=save_path,
            downloadPageUrl=download_page_url,
            subtitleUrl=subtitle_url,
            subtitlesJson=resolved_subs,
            downloadSubtitles=download_subtitles,
            status=status,
            scheduledStartTime=scheduled_start_time,
            maxSpeedLimit=speed_limit if speed_limit > 0 else self.global_speed_limit,
            totalBytes=initial_total_bytes,
            selectedServer=selected_server,
            selectedQuality=selected_quality,
        )

        self.tasks[task.id] = task
        self.task_order.append(task.id)
        library_service.save_task(task)

        if task.status == DownloadStatus.PENDING:
            self._trigger_process_queue()

        self.broadcast_update(task)
        return task

    def start_batch_download(self, anime_name: str, episodes: List[Dict[str, Any]]) -> List[DownloadTask]:
        started = []
        new_tasks = []

        clean_anime = self.sanitize_file_name(anime_name)
        if self.plex_organization:
            anime_dir = Path(self.download_dir) / clean_anime / "Season 01"
        else:
            anime_dir = Path(self.download_dir) / clean_anime
        anime_dir.mkdir(parents=True, exist_ok=True)

        for ep in episodes:
            ep_num = int(ep.get("number", 0))
            url = ep.get("url", "")
            if not url:
                continue
            name = ep.get("fileName", f"{anime_name} - Episode {ep_num}.mp4")
            sub_url = ep.get("subtitleUrl")
            dl_subs = str(ep.get("downloadSubtitles", "false")).lower() == "true"
            sel_server = ep.get("selectedServer")
            sel_quality = ep.get("selectedQuality")

            # Check duplicate
            existing = self.check_existing_file(anime_name, name, ep_num)
            if existing:
                cache_key = f"{url}::{sel_server or ''}::{sel_quality or ''}"
                cached = self.resolved_info_cache.get(cache_key) or self.resolved_info_cache.get(url)
                if cached and cached.size > 0 and existing.stat().st_size == cached.size:
                    logger.info("Batch: %s Ep%d existe déjà, ignoré", anime_name, ep_num)
                    continue

            sched_time = None
            if ep.get("scheduledTime"):
                try:
                    sched_time = datetime.fromisoformat(ep["scheduledTime"])
                except Exception:
                    pass

            speed_limit = 0
            if ep.get("speedLimit"):
                try:
                    speed_limit = int(ep["speedLimit"])
                except Exception:
                    pass

            cache_key = f"{url}::{sel_server or ''}::{sel_quality or ''}"
            cached = self.resolved_info_cache.get(cache_key) or self.resolved_info_cache.get(url)
            initial_total_bytes = cached.size if cached and cached.size > 0 else 0
            resolved_subs = cached.subtitles_json if cached else "[]"

            now = datetime.now(timezone.utc) if (sched_time and sched_time.tzinfo) else datetime.now()
            is_scheduled = sched_time is not None and sched_time > now
            status = DownloadStatus.SCHEDULED if is_scheduled else DownloadStatus.PENDING

            if self.plex_organization:
                ext = Path(name).suffix or ".mp4"
                final_file_name = f"{clean_anime} - S01E{ep_num:02d}{ext}"
            else:
                final_file_name = self.sanitize_file_name(name)

            save_path = str(anime_dir / final_file_name)

            task = DownloadTask(
                animeName=anime_name,
                episodeNumber=ep_num,
                fileName=final_file_name,
                fileUrl=url,
                savePath=save_path,
                downloadPageUrl=url,
                subtitleUrl=sub_url,
                subtitlesJson=resolved_subs,
                downloadSubtitles=dl_subs,
                status=status,
                scheduledStartTime=sched_time,
                maxSpeedLimit=speed_limit if speed_limit > 0 else self.global_speed_limit,
                totalBytes=initial_total_bytes,
                selectedServer=sel_server,
                selectedQuality=sel_quality,
            )

            self.tasks[task.id] = task
            self.task_order.append(task.id)
            new_tasks.append(task)
            started.append(task)

        if new_tasks:
            library_service.save_tasks_batch(new_tasks)
            for task in new_tasks:
                self.broadcast_update(task)
            self._trigger_process_queue()

        return started

    # -------------------------------------------------------------------------
    # Contrôle de la file et des tâches
    # -------------------------------------------------------------------------

    def get_all_tasks(self) -> List[DownloadTask]:
        ordered = []
        for tid in self.task_order:
            t = self.tasks.get(tid)
            if t:
                ordered.append(t)
        return ordered

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        if task_id in self.tasks:
            return self.tasks[task_id]
        entity = library_service.get_task_entity(task_id)
        return entity.to_task() if entity else None

    def pause_download(self, task_id: str) -> bool:
        t = self.tasks.get(task_id)
        if t and t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PENDING, DownloadStatus.RETRYING, DownloadStatus.SCHEDULED]:
            t.paused = True
            t.status = DownloadStatus.PAUSED
            t.speed = 0
            self.broadcast_update(t)
            library_service.save_task(t)
            self._trigger_process_queue()
            return True
        return False

    def resume_download(self, task_id: str) -> bool:
        t = self.tasks.get(task_id)
        if not t:
            entity = library_service.get_task_entity(task_id)
            if entity:
                t = entity.to_task()
                self.tasks[t.id] = t
                if t.id not in self.task_order:
                    self.task_order.append(t.id)

        if t and t.status in [DownloadStatus.PAUSED, DownloadStatus.FAILED, DownloadStatus.CANCELLED, DownloadStatus.COMPLETED]:
            t.paused = False
            t.cancelled = False
            t.error = None

            # Détecter le fichier partiel existant (.part ou savePath) pour reprise
            if t.savePath:
                part_path = Path(t.savePath + ".part")
                out_path = Path(t.savePath)
                if part_path.exists() and part_path.stat().st_size > 0:
                    if t.totalBytes > 0 and part_path.stat().st_size > t.totalBytes:
                        logger.warning("Fichier .part (%d octets) plus grand que totalBytes (%d) pour %s, suppression",
                                       part_path.stat().st_size, t.totalBytes, t.fileName)
                        part_path.unlink(missing_ok=True)
                        t.downloadedBytes = 0
                    else:
                        t.downloadedBytes = part_path.stat().st_size
                elif out_path.exists() and out_path.stat().st_size > 0:
                    try:
                        with open(out_path, "rb") as f_chk:
                            head = f_chk.read(100).lower()
                            if b"<html" not in head and b"<!doctype" not in head:
                                t.downloadedBytes = out_path.stat().st_size
                    except Exception:
                        pass

                if t.totalBytes > 0 and t.downloadedBytes > 0:
                    t.progress = min(99.9, (t.downloadedBytes / t.totalBytes) * 100.0)
                elif t.downloadedBytes == 0:
                    t.progress = 0.0
                logger.info("Reprise détectée pour %s: %s déjà téléchargé(s)",
                            t.fileName, format_bytes(t.downloadedBytes))

            t.status = DownloadStatus.PENDING
            self.broadcast_update(t)
            library_service.save_task(t)
            self._trigger_process_queue()
            return True
        return False

    def cancel_download(self, task_id: str) -> bool:
        t = self.tasks.get(task_id)
        if t and t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PENDING, DownloadStatus.RETRYING, DownloadStatus.SCHEDULED]:
            t.cancelled = True
            t.status = DownloadStatus.CANCELLED
            t.speed = 0
            self.broadcast_update(t)
            library_service.save_task(t)
            self._trigger_process_queue()
            return True
        return False

    def cancel_all_downloads(self) -> int:
        count = 0
        active_statuses = [
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PENDING,
            DownloadStatus.RETRYING,
            DownloadStatus.SCHEDULED,
            DownloadStatus.PAUSED,
            DownloadStatus.MUXING
        ]
        cancelled_tasks = []
        for t in self.tasks.values():
            if t.status in active_statuses:
                t.cancelled = True
                t.paused = False
                t.status = DownloadStatus.CANCELLED
                t.speed = 0
                proc = getattr(t, "activeProcess", None)
                if proc:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                self.broadcast_update(t)
                cancelled_tasks.append(t)
                count += 1
        if cancelled_tasks:
            library_service.save_tasks_batch(cancelled_tasks)
            self._trigger_process_queue()
        logger.info("Annulation globale : %d téléchargement(s) annulé(s)", count)
        return count

    def remove_task(self, task_id: str) -> bool:
        t = self.tasks.pop(task_id, None)
        if t:
            if task_id in self.task_order:
                self.task_order.remove(task_id)
            if t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.RETRYING]:
                t.cancelled = True
            self._trigger_process_queue()
            return True
        return False

    def pause_all_downloads(self):
        for t in self.tasks.values():
            if t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PENDING, DownloadStatus.RETRYING, DownloadStatus.SCHEDULED]:
                t.paused = True
                t.status = DownloadStatus.PAUSED
                t.speed = 0
                self.broadcast_update(t)
                library_service.save_task(t)
        self._trigger_process_queue()

    def resume_all_downloads(self):
        for t in self.tasks.values():
            if t.status == DownloadStatus.PAUSED:
                t.paused = False
                t.cancelled = False
                t.status = DownloadStatus.PENDING
                t.error = None
                self.broadcast_update(t)
                library_service.save_task(t)
        self._trigger_process_queue()

    def clear_inactive_tasks(self):
        inactive = [DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED]
        for tid in list(self.tasks.keys()):
            if self.tasks[tid].status in inactive:
                self.remove_task(tid)

    def clear_history_tasks(self, status: Optional[str] = None, anime_name: Optional[str] = None):
        target_statuses = None
        if status:
            target_statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
        for tid in list(self.tasks.keys()):
            t = self.tasks.get(tid)
            if not t:
                continue
            if anime_name and t.animeName.lower() != anime_name.lower():
                continue
            if target_statuses:
                if t.status.value.upper() in target_statuses or t.status.name.upper() in target_statuses:
                    self.remove_task(tid)
            else:
                if t.status in [DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED]:
                    self.remove_task(tid)

    def move_task_to_top(self, task_id: str):
        if task_id in self.task_order:
            self.task_order.remove(task_id)
            self.task_order.insert(0, task_id)
            self._trigger_process_queue()
            task = self.tasks.get(task_id)
            if task:
                self.broadcast_update(task)

    def move_series_to_top(self, anime_name: str):
        if not anime_name:
            return
        series_ids = [tid for tid in self.task_order if self.tasks.get(tid) and self.tasks[tid].animeName.lower() == anime_name.lower()]
        if series_ids:
            for tid in series_ids:
                self.task_order.remove(tid)
            for tid in reversed(series_ids):
                self.task_order.insert(0, tid)
            self._trigger_process_queue()
            for tid in series_ids:
                t = self.tasks.get(tid)
                if t:
                    self.broadcast_update(t)

    def reorder_tasks(self, ordered_ids: List[str]):
        new_order = [tid for tid in ordered_ids if tid in self.tasks]
        for tid in self.task_order:
            if tid not in new_order:
                new_order.append(tid)
        self.task_order = new_order
        self._trigger_process_queue()

    # -------------------------------------------------------------------------
    # Vérification d'intégrité & Re-téléchargement
    # -------------------------------------------------------------------------

    def verify_task(self, task_id: str) -> Optional[VerificationResult]:
        task = self.get_task(task_id)
        if not task:
            return None

        verif = verification_service.verify_file(
            file_path_str=task.savePath,
            anime_name=task.animeName,
            file_name=task.fileName,
            expected_size=task.totalBytes
        )

        if verif.relocatedPath and verif.relocatedPath != task.savePath:
            task.savePath = verif.relocatedPath

        task.verificationStatus = verif.status
        task.verifiedAt = datetime.now(timezone.utc)
        task.videoDuration = verif.duration
        task.verificationError = verif.error

        library_service.save_task(task)
        if task.id in self.tasks:
            self.tasks[task.id] = task
            self.broadcast_update(task)

        return verif

    def verify_all_completed(self) -> Dict[str, Any]:
        """Vérifie l'intégrité de l'ensemble des téléchargements terminés."""
        completed_tasks: Dict[str, DownloadTask] = {}

        # 1. Tâches en mémoire
        for t in self.tasks.values():
            if t.status in [DownloadStatus.COMPLETED, DownloadStatus.FAILED]:
                completed_tasks[t.id] = t

        # 2. Tâches dans l'historique
        for entity in library_service.get_history():
            if entity.id not in completed_tasks and entity.status in [DownloadStatus.COMPLETED.value, DownloadStatus.FAILED.value]:
                completed_tasks[entity.id] = entity.to_task()

        total = len(completed_tasks)
        valid_count = 0
        missing_count = 0
        empty_count = 0
        incomplete_count = 0
        corrupted_count = 0
        results_list = []

        for task in completed_tasks.values():
            verif = verification_service.verify_file(
                file_path_str=task.savePath,
                anime_name=task.animeName,
                file_name=task.fileName,
                expected_size=task.totalBytes
            )

            if verif.relocatedPath and verif.relocatedPath != task.savePath:
                task.savePath = verif.relocatedPath

            task.verificationStatus = verif.status
            task.verifiedAt = datetime.now(timezone.utc)
            task.videoDuration = verif.duration
            task.verificationError = verif.error

            library_service.save_task(task)
            if task.id in self.tasks:
                self.tasks[task.id] = task
                self.broadcast_update(task)

            if verif.valid:
                valid_count += 1
            elif verif.status == "MISSING":
                missing_count += 1
            elif verif.status == "EMPTY":
                empty_count += 1
            elif verif.status == "INCOMPLETE":
                incomplete_count += 1
            else:
                corrupted_count += 1

            results_list.append({
                "taskId": task.id,
                "animeName": task.animeName,
                "episodeNumber": task.episodeNumber,
                "fileName": task.fileName,
                "status": verif.status,
                "valid": verif.valid,
                "duration": verif.duration,
                "formattedDuration": verif.formattedDuration,
                "formattedSize": verif.formattedSize,
                "expectedSize": verif.expectedSize,
                "sizeRatio": verif.sizeRatio,
                "error": verif.error,
            })

        return {
            "total": total,
            "valid": valid_count,
            "missing": missing_count,
            "empty": empty_count,
            "incomplete": incomplete_count,
            "corrupted": corrupted_count,
            "results": results_list,
        }

    def redownload_task(self, task_id: str, force: bool = False) -> Optional[DownloadTask]:
        """Relance un téléchargement en reprenant si possible ou en nettoyant si corrompu."""
        task = self.get_task(task_id)
        if not task:
            return None

        # Vérifier si un fichier partiel sain existe sur le disque
        has_healthy_part = False
        if not force and task.savePath:
            part_p = Path(task.savePath + ".part")
            out_p = Path(task.savePath)

            # Si le statut de vérification est explicitement corrompu, ne pas reprendre
            if task.verificationStatus in ["CORRUPTED", "INVALID"]:
                logger.warning("Fichier marqué comme %s pour %s, purge obligatoire pour nouveau départ sain",
                               task.verificationStatus, task.fileName)
                has_healthy_part = False
            else:
                target = part_p if part_p.exists() else (out_p if out_p.exists() else None)
                if target and target.stat().st_size > 1024:
                    if task.totalBytes > 0 and target.stat().st_size > task.totalBytes:
                        logger.warning("Fichier partiel %s (%s) plus grand que totalBytes (%s), purge requise",
                                       target.name, format_bytes(target.stat().st_size), format_bytes(task.totalBytes))
                        has_healthy_part = False
                    else:
                        try:
                            with open(target, "rb") as f_chk:
                                head = f_chk.read(100).lower()
                                if b"<html" not in head and b"<!doctype" not in head:
                                    has_healthy_part = True
                        except Exception:
                            pass

        # Si un fichier partiel sain existe et qu'on ne force pas le reset complet : reprise !
        if has_healthy_part:
            logger.info("Fichier partiel sain détecté pour %s, basculement vers resume_download", task.fileName)
            self.resume_download(task_id)
            return self.get_task(task_id)

        # Sinon, purger tout fichier corrompu ou vide sur le disque
        if task.savePath:
            try:
                p = Path(task.savePath)
                if p.exists() and p.is_file():
                    p.unlink()
                part_p = Path(task.savePath + ".part")
                if part_p.exists() and part_p.is_file():
                    part_p.unlink()
            except Exception as e:
                logger.warning("Impossible de supprimer le fichier corrompu %s: %s", task.savePath, e)

        # Réinitialiser la tâche pour un nouveau téléchargement complet
        task.progress = 0.0
        task.downloadedBytes = 0
        task.speed = 0
        task.error = None
        task.cancelled = False
        task.paused = False
        task.directDownloadUrl = None  # Forcer la re-résolution de l'URL
        task.status = DownloadStatus.PENDING
        task.verificationStatus = "UNVERIFIED"
        task.verificationError = None
        task.completedAt = None

        self.tasks[task.id] = task
        if task.id not in self.task_order:
            self.task_order.append(task.id)

        library_service.save_task(task)
        self.broadcast_update(task)
        self._trigger_process_queue()
        logger.info("Tâche relancée pour re-téléchargement complet : %s", task.fileName)
        return task

    # -------------------------------------------------------------------------
    # Traitement de la file d'attente (process_queue)
    # -------------------------------------------------------------------------

    async def process_queue(self):
        async with self._lock:
            active_count = sum(1 for t in self.tasks.values() if t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.RETRYING])
            slots = self.max_concurrent_downloads - active_count
            if slots <= 0:
                return

            pending = [self.tasks[tid] for tid in self.task_order if tid in self.tasks and self.tasks[tid].status == DownloadStatus.PENDING]
            for i in range(min(slots, len(pending))):
                task = pending[i]
                task.status = DownloadStatus.DOWNLOADING
                self.broadcast_update(task)
                library_service.save_task(task)
                asyncio.create_task(self._execute_download(task))

    # -------------------------------------------------------------------------
    # Exécution du téléchargement
    # -------------------------------------------------------------------------

    async def _execute_download(self, task: DownloadTask):
        try:
            max_retries = 6  # Tolérance accrue face aux coupures réseau CDN
            task.retryCount = 0
            need_resolve = True

            while True:
                if task.cancelled:
                    task.status = DownloadStatus.CANCELLED
                    self.broadcast_update(task)
                    library_service.save_task(task)
                    return
                if task.paused:
                    task.status = DownloadStatus.PAUSED
                    task.speed = 0
                    self.broadcast_update(task)
                    library_service.save_task(task)
                    return

                try:
                    direct_url = task.fileUrl
                    is_voir_anime = ("voir-anime" in (direct_url or "").lower()) or ("voiranime" in (direct_url or "").lower())
                    server_type = "vidzy"
                    chunks_json = "[]"

                    # Réutiliser l'URL directe déjà résolue si disponible et valide (reprise)
                    # S'assurer qu'elle n'est PAS une page HTML (ne contient pas /d/vidzy ou similaire)
                    is_cached_valid = bool(
                        task.directDownloadUrl and
                        not self._needs_scraping_resolution(task.directDownloadUrl) and
                        not re.search(r"vidzy\.[a-z]+/d/", task.directDownloadUrl)
                    )

                    if is_cached_valid and not need_resolve:
                        direct_url = task.directDownloadUrl
                        logger.info("Réutilisation de l'URL directe en cache pour %s", task.fileName)
                    elif is_voir_anime:
                        info = await asyncio.to_thread(
                            voiranime_service.extract_download_info,
                            direct_url,
                            preferred_server=task.selectedServer or self.voiranime_default_server,
                            preferred_quality=task.selectedQuality,
                        )
                        direct_url = info.get("videoUrl", "")
                        if not direct_url:
                            raise ValueError(f"Impossible d'extraire l'URL vidéo pour {task.fileName}")
                        server_type = info.get("serverType", "unknown")
                        chunks_json = info.get("videoChunks", "[]")
                        task.directDownloadUrl = direct_url
                        if not task.subtitleUrl and info.get("subtitleUrl"):
                            task.subtitleUrl = info["subtitleUrl"]
                    elif direct_url and self._needs_scraping_resolution(direct_url):
                        info = await asyncio.to_thread(scraping_service.extract_download_info, direct_url)
                        direct_url = info.get("videoUrl", "")
                        if not direct_url:
                            raise ValueError(f"Impossible d'extraire l'URL vidéo directe pour {task.fileName}")
                        task.directDownloadUrl = direct_url
                        if not task.subtitleUrl and info.get("subtitleUrl"):
                            task.subtitleUrl = info["subtitleUrl"]
                        if not task.subtitlesJson or task.subtitlesJson == "[]":
                            task.subtitlesJson = info.get("subtitles", "[]")
                    else:
                        task.directDownloadUrl = direct_url

                    need_resolve = False  # Les retries suivants réutiliseront l'URL

                    if server_type == "myTV" and chunks_json != "[]":
                        chunks = json.loads(chunks_json)
                        if len(chunks) > 1:
                            await self._download_mytv_chunks(task, chunks)
                            return

                    is_hls = bool(direct_url and (".m3u8" in direct_url.lower()))
                    if is_hls:
                        await self._download_hls_stream(task, direct_url)
                        return

                    bytes_before = task.downloadedBytes
                    await self._download_single_file(task, direct_url)
                    break

                except Exception as e:
                    if task.cancelled:
                        task.status = DownloadStatus.CANCELLED
                        task.speed = 0
                        self.broadcast_update(task)
                        library_service.save_task(task)
                        return
                    if task.paused:
                        task.status = DownloadStatus.PAUSED
                        task.speed = 0
                        self.broadcast_update(task)
                        library_service.save_task(task)
                        return

                    # Si des octets ont été reçus pendant cette tentative (le téléchargement avance),
                    # on réinitialise le compteur d'échecs consécutifs !
                    bytes_gained = task.downloadedBytes - bytes_before if 'bytes_before' in locals() else 0
                    if bytes_gained > 0:
                        logger.info("Progrès de %s octets pour %s malgré coupure réseau, réinitialisation du compteur d'essais",
                                    format_bytes(bytes_gained), task.fileName)
                        task.retryCount = 0

                    if task.retryCount < max_retries:
                        task.retryCount += 1
                        err_msg = str(e).lower()
                        # Si URL expirée (401, 403, 404, 410, ou HTML reçu), forcer la re-résolution
                        if "html" in err_msg or "403" in err_msg or "401" in err_msg or "404" in err_msg or "410" in err_msg:
                            need_resolve = True
                            task.directDownloadUrl = None
                            logger.info("Lien direct expiré ou invalide (%s) pour %s, re-résolution au prochain essai", err_msg, task.fileName)

                        task.status = DownloadStatus.RETRYING
                        task.error = f"Erreur réseau: {str(e)}. Reprise ({task.retryCount}/{max_retries})"
                        self.broadcast_update(task)
                        library_service.save_task(task)
                        await asyncio.sleep(min(8.0, math.pow(1.5, task.retryCount)))
                    else:
                        task.status = DownloadStatus.FAILED
                        task.error = str(e)
                        task.speed = 0
                        self.broadcast_update(task)
                        library_service.save_task(task)
                        break
        finally:
            self._trigger_process_queue()

    async def _download_single_file(self, task: DownloadTask, direct_url: str):
        if not direct_url:
            raise ValueError("URL directe introuvable")

        output_path = Path(task.savePath)
        part_path = Path(task.savePath + ".part")

        # 1. Gestion propre du fichier existant et reprise
        existing_len = 0
        if output_path.exists():
            if output_path.stat().st_size < 1024 * 1024:
                try:
                    with open(output_path, "rb") as f_chk:
                        h = f_chk.read(100).lower()
                        if b"<html" in h or b"<!doctype" in h:
                            logger.warning("Fichier final corrompu (HTML) détecté et supprimé pour %s", task.fileName)
                            output_path.unlink(missing_ok=True)
                except Exception:
                    pass

            if output_path.exists():
                verif = await asyncio.to_thread(
                    verification_service.verify_file,
                    file_path_str=str(output_path),
                    anime_name=task.animeName,
                    file_name=task.fileName,
                    expected_size=task.totalBytes if task.totalBytes and task.totalBytes > 0 else None
                )
                if verif.valid:
                    logger.info("Fichier final déjà existant et valide pour %s (%s)",
                                task.fileName, format_bytes(output_path.stat().st_size))
                    part_path.unlink(missing_ok=True)
                    task.status = DownloadStatus.COMPLETED
                    task.progress = 100.0
                    task.verificationStatus = verif.status
                    task.videoDuration = verif.duration
                    task.downloadedBytes = output_path.stat().st_size
                    if not task.totalBytes or task.totalBytes <= 0:
                        task.totalBytes = output_path.stat().st_size
                    task.completedAt = datetime.now(timezone.utc)
                    self.broadcast_update(task)
                    library_service.save_task(task)
                    library_service.mark_as_downloaded(
                        task.downloadPageUrl or "",
                        task.animeName,
                        task.episodeNumber,
                        ""
                    )
                    return
                else:
                    logger.warning("Fichier final existant invalide/corrompu pour %s (%s), suppression : %s",
                                   task.fileName, format_bytes(output_path.stat().st_size), verif.error)
                    output_path.unlink(missing_ok=True)

        if part_path.exists():
            part_size = part_path.stat().st_size
            if part_size < 1024 * 1024:
                try:
                    with open(part_path, "rb") as f_chk:
                        h = f_chk.read(100).lower()
                        if b"<html" in h or b"<!doctype" in h:
                            logger.warning("Fichier .part corrompu (HTML) détecté et supprimé pour %s", task.fileName)
                            part_path.unlink(missing_ok=True)
                except Exception:
                    pass
            elif task.totalBytes and task.totalBytes > 0 and part_size > task.totalBytes:
                logger.warning("Fichier .part (%s) dépasse la taille attendue (%s) pour %s, suppression",
                               format_bytes(part_size), format_bytes(task.totalBytes), task.fileName)
                part_path.unlink(missing_ok=True)

            if part_path.exists():
                existing_len = part_path.stat().st_size

        referer = "https://vidzy.org/" if "vidzy" in direct_url else ("https://voir-anime.to/" if "voir" in direct_url else "https://french-manga.net/")
        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": referer,
        }
        proxy = proxy_service.get_random_proxy()

        timeout = httpx.Timeout(connect=settings.CONNECTION_TIMEOUT, read=120.0, write=30.0, pool=None)
        async with httpx.AsyncClient(headers=headers, proxy=proxy, timeout=timeout, follow_redirects=True, verify=False) as client:
            req_headers = dict(headers)
            is_resume = existing_len > 0
            if is_resume:
                req_headers["Range"] = f"bytes={existing_len}-"
                logger.info("Tentative de reprise pour %s depuis %s", task.fileName, format_bytes(existing_len))

            while True:
                async with client.stream("GET", direct_url, headers=req_headers) as stream_resp:
                    # Gestion du code 416 Range Not Satisfiable
                    if stream_resp.status_code == 416 and is_resume:
                        logger.warning("HTTP 416 (Range Not Satisfiable) pour %s avec existing_len=%s",
                                       task.fileName, format_bytes(existing_len))
                        if part_path.exists():
                            verif_part = await asyncio.to_thread(
                                verification_service.verify_file,
                                file_path_str=str(part_path),
                                anime_name=task.animeName,
                                file_name=task.fileName
                            )
                            if verif_part.valid:
                                logger.info("Le fichier .part est en réalité complet et valide pour %s, finalisation", task.fileName)
                                if output_path.exists():
                                    output_path.unlink(missing_ok=True)
                                shutil.move(str(part_path), str(output_path))
                                await self._finalize_task(task)
                                return
                            else:
                                logger.warning("Fichier .part invalide/corrompu (%s), suppression pour reprise propre", verif_part.error)
                                part_path.unlink(missing_ok=True)

                        existing_len = 0
                        is_resume = False
                        req_headers.pop("Range", None)
                        continue

                    if stream_resp.status_code not in [200, 206]:
                        raise ConnectionError(f"HTTP {stream_resp.status_code}")

                    # Contrôle strict du type de contenu (rejeter formellement le HTML)
                    content_type = stream_resp.headers.get("Content-Type", "").lower()
                    if "text/html" in content_type or "text/plain" in content_type or "application/json" in content_type:
                        raise ValueError(f"Réponse HTTP invalide : type '{content_type}' reçu au lieu d'un flux vidéo binaire")

                    # Le serveur ne supporte pas Range — on recommence depuis 0
                    if stream_resp.status_code == 200 and is_resume:
                        logger.warning("Le serveur ne supporte pas la reprise pour %s, téléchargement depuis le début", task.fileName)
                        existing_len = 0
                        is_resume = False

                    # Extraction et validation de la taille via Content-Range ou Content-Length
                    total_bytes = 0
                    content_range = stream_resp.headers.get("Content-Range", "")
                    if stream_resp.status_code == 206 and content_range:
                        match = re.search(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", content_range, re.IGNORECASE)
                        if match:
                            range_start = int(match.group(1))
                            total_str = match.group(3)
                            if total_str != "*":
                                total_bytes = int(total_str)

                            if range_start != existing_len:
                                logger.warning("Désalignement Content-Range pour %s: serveur à %d, local à %d",
                                               task.fileName, range_start, existing_len)
                                if part_path.exists() and part_path.stat().st_size > range_start:
                                    with open(part_path, "r+b") as f_adj:
                                        f_adj.truncate(range_start)
                                existing_len = range_start

                    if total_bytes == 0:
                        cl = stream_resp.headers.get("Content-Length")
                        if cl and cl.isdigit():
                            total_bytes = int(cl) + existing_len

                    if total_bytes > 0:
                        task.totalBytes = total_bytes
                        self.broadcast_update(task)

                    # Si le .part dépasse la taille totale, purge et reprise depuis 0
                    if total_bytes > 0 and existing_len > total_bytes:
                        logger.warning("Fichier .part (%s) plus grand que total_bytes (%s) pour %s, réinitialisation",
                                       format_bytes(existing_len), format_bytes(total_bytes), task.fileName)
                        part_path.unlink(missing_ok=True)
                        existing_len = 0
                        is_resume = False
                        req_headers.pop("Range", None)
                        continue

                    accept_ranges = "bytes" in stream_resp.headers.get("Accept-Ranges", "").lower() or stream_resp.status_code == 206
                    task.supportsResume = accept_ranges

                    # Vérifier si le .part est déjà complet
                    if total_bytes > 0 and existing_len >= total_bytes:
                        logger.info("Fichier .part déjà complet pour %s, vérification", task.fileName)
                        if part_path.exists():
                            verif_part = await asyncio.to_thread(
                                verification_service.verify_file,
                                file_path_str=str(part_path),
                                anime_name=task.animeName,
                                file_name=task.fileName
                            )
                            if verif_part.valid:
                                if output_path.exists():
                                    output_path.unlink(missing_ok=True)
                                shutil.move(str(part_path), str(output_path))
                                await self._finalize_task(task)
                                return
                            else:
                                logger.warning("Fichier .part complet mais corrompu pour %s, réinitialisation", task.fileName)
                                part_path.unlink(missing_ok=True)
                                existing_len = 0
                                is_resume = False
                                req_headers.pop("Range", None)
                                continue

                    # Check disk space
                    free_space = shutil.disk_usage(self.download_dir).free
                    req_space = (total_bytes - existing_len) if total_bytes > 0 else 500 * 1024 * 1024
                    if free_space < req_space:
                        raise OSError(f"Espace disque insuffisant (Requis: {format_bytes(req_space)}, Disponible: {format_bytes(free_space)})")

                    # Toujours écrire dans le fichier .part, jamais le fichier final
                    mode = "ab" if is_resume else "wb"
                    downloaded = existing_len
                    last_time = time.time()
                    last_bytes = downloaded
                    first_chunk = True

                    if task.status != DownloadStatus.DOWNLOADING:
                        task.status = DownloadStatus.DOWNLOADING
                        task.error = None
                        self.broadcast_update(task)

                    with open(part_path, mode) as f:
                        async for chunk in stream_resp.aiter_bytes(chunk_size=65536):
                            # Vérification des premiers octets pour s'assurer que ce n'est pas du HTML
                            if first_chunk and not is_resume:
                                head_chk = chunk[:100].lower()
                                if b"<html" in head_chk or b"<!doctype" in head_chk:
                                    raise ValueError("Contenu reçu est du HTML et non un flux vidéo")
                                first_chunk = False

                            if task.cancelled:
                                task.status = DownloadStatus.CANCELLED
                                task.speed = 0
                                task.downloadedBytes = downloaded
                                self.broadcast_update(task)
                                library_service.save_task(task)
                                logger.info("Annulé %s — fichier .part conservé (%s)",
                                            task.fileName, format_bytes(downloaded))
                                return
                            if task.paused:
                                task.status = DownloadStatus.PAUSED
                                task.speed = 0
                                task.downloadedBytes = downloaded
                                self.broadcast_update(task)
                                library_service.save_task(task)
                                logger.info("Pause %s — progression sauvegardée (%s)",
                                            task.fileName, format_bytes(downloaded))
                                return

                            f.write(chunk)
                            downloaded += len(chunk)
                            task.downloadedBytes = downloaded
                            if total_bytes > 0:
                                task.progress = min(100.0, (downloaded / total_bytes) * 100.0)

                            # Throttling
                            await self._apply_throttle(task, len(chunk))

                            now = time.time()
                            if now - last_time >= 0.5:
                                task.speed = int((downloaded - last_bytes) / (now - last_time))
                                last_time = now
                                last_bytes = downloaded
                                self.broadcast_update(task)

                    if total_bytes > 0 and downloaded < total_bytes:
                        raise ConnectionError(f"Téléchargement incomplet: {downloaded}/{total_bytes} octets")
                    if downloaded <= 0:
                        raise ConnectionError("0 octet reçu")

                    break

        # Téléchargement complet : renommer .part → fichier final
        if part_path.exists():
            # Supprimer le fichier final existant s'il existe (il est incomplet/invalide)
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            shutil.move(str(part_path), str(output_path))
            logger.info("Fichier .part renommé en fichier final : %s (%s)", output_path.name, format_bytes(downloaded))

        # Sous-titres
        if task.downloadSubtitles:
            await self._download_subtitles(task)

        await self._finalize_task(task)

    async def _download_mytv_chunks(self, task: DownloadTask, chunks: List[str]):
        logger.info("myTV: %d morceau(x) à télécharger pour %s", len(chunks), task.fileName)
        base_path = re.sub(r"\.(mp4|mkv)$", "", task.savePath)
        chunk_files = []
        total_all_chunks = 0

        # Estimer la taille totale
        for curl in chunks:
            sz = await self.get_remote_file_size(curl)
            if sz > 0:
                total_all_chunks += sz

        if total_all_chunks > 0:
            task.totalBytes = total_all_chunks
            self.broadcast_update(task)

        downloaded_total = 0
        headers = {"User-Agent": proxy_service.get_user_agent(), "Referer": "https://vidzy.live/"}
        proxy = proxy_service.get_random_proxy()

        async with httpx.AsyncClient(headers=headers, proxy=proxy, timeout=settings.READ_TIMEOUT, follow_redirects=True, verify=False) as client:
            for idx, curl in enumerate(chunks):
                if task.cancelled:
                    task.status = DownloadStatus.CANCELLED
                    self.broadcast_update(task)
                    return
                if task.paused:
                    task.status = DownloadStatus.PAUSED
                    self.broadcast_update(task)
                    return

                part_file = Path(f"{base_path}_part{idx + 1}.tmp")
                chunk_files.append(part_file)

                async with client.stream("GET", curl) as resp:
                    if resp.status_code not in [200, 206]:
                        raise ConnectionError(f"HTTP {resp.status_code} pour morceau {idx + 1}")

                    last_time = time.time()
                    last_bytes = downloaded_total
                    chunk_downloaded = 0

                    with open(part_file, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=16384):
                            if task.cancelled:
                                task.status = DownloadStatus.CANCELLED
                                self.broadcast_update(task)
                                return
                            if task.paused:
                                task.status = DownloadStatus.PAUSED
                                self.broadcast_update(task)
                                return

                            f.write(chunk)
                            chunk_downloaded += len(chunk)
                            cur_glob = downloaded_total + chunk_downloaded
                            task.downloadedBytes = cur_glob
                            if total_all_chunks > 0:
                                task.progress = (cur_glob / total_all_chunks) * 100.0

                            await self._apply_throttle(task, len(chunk))

                            now = time.time()
                            if now - last_time >= 0.5:
                                task.speed = int((cur_glob - last_bytes) / (now - last_time))
                                last_time = now
                                last_bytes = cur_glob
                                self.broadcast_update(task)

                    downloaded_total += chunk_downloaded

        # Concaténer
        logger.info("Concaténation de %d morceaux vers %s", len(chunk_files), task.fileName)
        output_file = Path(task.savePath)
        with open(output_file, "wb") as outfile:
            for pf in chunk_files:
                with open(pf, "rb") as infile:
                    shutil.copyfileobj(infile, outfile, length=65536)
                pf.unlink(missing_ok=True)

        if task.downloadSubtitles:
            await self._download_subtitles(task)

        await self._finalize_task(task)

    async def _download_hls_stream(self, task: DownloadTask, m3u8_url: str):
        logger.info("Téléchargement HLS pour %s depuis %s", task.fileName, m3u8_url)
        output_path = Path(task.savePath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output_path.with_suffix(".tmp.mp4")
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)

        if self.is_ffmpeg_available():
            ua = proxy_service.get_user_agent()
            referer = "https://voembed.net/"
            headers_arg = f"User-Agent: {ua}\r\nReferer: {referer}\r\n"
            cmd = [
                "ffmpeg", "-y",
                "-headers", headers_arg,
                "-i", m3u8_url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                "-progress", "pipe:1",
                str(temp_output)
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            task.activeProcess = proc

            last_time = time.time()
            last_bytes = 0

            try:
                while True:
                    if task.cancelled:
                        try:
                            proc.terminate()
                            await proc.wait()
                        except Exception:
                            pass
                        temp_output.unlink(missing_ok=True)
                        task.status = DownloadStatus.CANCELLED
                        task.speed = 0
                        self.broadcast_update(task)
                        return

                    if task.paused:
                        try:
                            proc.terminate()
                            await proc.wait()
                        except Exception:
                            pass
                        task.status = DownloadStatus.PAUSED
                        task.speed = 0
                        self.broadcast_update(task)
                        return

                    line = await proc.stdout.readline()
                    if not line:
                        break

                    text = line.decode(errors="replace").strip()
                    if text.startswith("total_size="):
                        try:
                            downloaded = int(text.split("=")[1])
                            if downloaded > 0:
                                task.downloadedBytes = downloaded
                                now = time.time()
                                if now - last_time >= 0.5:
                                    task.speed = int((downloaded - last_bytes) / (now - last_time))
                                    last_time = now
                                    last_bytes = downloaded
                                    self.broadcast_update(task)
                        except (ValueError, IndexError):
                            pass

                rc = await proc.wait()
                if rc != 0 or not temp_output.exists() or temp_output.stat().st_size == 0:
                    raise ConnectionError(f"FFmpeg HLS failed with exit code {rc}")

                final_size = temp_output.stat().st_size
                shutil.move(str(temp_output), str(output_path))
                task.downloadedBytes = final_size
                task.totalBytes = final_size
                task.progress = 100.0
                task.speed = 0

                if task.downloadSubtitles:
                    await self._download_subtitles(task)

                await self._finalize_task(task)
                return

            finally:
                task.activeProcess = None
                if temp_output.exists() and not output_path.exists():
                    temp_output.unlink(missing_ok=True)
        else:
            await self._download_hls_segments_native(task, m3u8_url)

    async def _download_hls_segments_native(self, task: DownloadTask, m3u8_url: str):
        logger.info("Téléchargement HLS natif (fallback) pour %s", task.fileName)
        output_path = Path(task.savePath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output_path.with_suffix(".tmp.mp4")
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)

        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": "https://voembed.net/",
        }
        proxy = proxy_service.get_random_proxy()

        async with httpx.AsyncClient(headers=headers, proxy=proxy, timeout=settings.READ_TIMEOUT, follow_redirects=True, verify=False) as client:
            resp = await client.get(m3u8_url)
            if resp.status_code != 200:
                raise ConnectionError(f"HTTP {resp.status_code} sur playlist m3u8")

            playlist_text = resp.text
            sub_url = m3u8_url
            for line in playlist_text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    sub_url = urljoin(m3u8_url, line)
                    break

            if sub_url != m3u8_url:
                sub_resp = await client.get(sub_url)
                if sub_resp.status_code != 200:
                    raise ConnectionError(f"HTTP {sub_resp.status_code} sur sous-playlist HLS")
                playlist_text = sub_resp.text

            segments = [
                urljoin(sub_url, line.strip())
                for line in playlist_text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]

            if not segments:
                raise ValueError("Aucun segment trouvé dans la playlist HLS")

            total_segments = len(segments)
            downloaded = 0
            last_time = time.time()
            last_bytes = 0

            with open(temp_output, "wb") as outfile:
                for idx, seg_url in enumerate(segments):
                    if task.cancelled:
                        outfile.close()
                        temp_output.unlink(missing_ok=True)
                        task.status = DownloadStatus.CANCELLED
                        task.speed = 0
                        self.broadcast_update(task)
                        return
                    if task.paused:
                        task.status = DownloadStatus.PAUSED
                        task.speed = 0
                        self.broadcast_update(task)
                        return

                    seg_resp = await client.get(seg_url)
                    if seg_resp.status_code != 200:
                        continue

                    chunk_data = seg_resp.content
                    outfile.write(chunk_data)
                    downloaded += len(chunk_data)
                    task.downloadedBytes = downloaded
                    task.progress = ((idx + 1) / total_segments) * 100.0

                    await self._apply_throttle(task, len(chunk_data))

                    now = time.time()
                    if now - last_time >= 0.5:
                        task.speed = int((downloaded - last_bytes) / (now - last_time))
                        last_time = now
                        last_bytes = downloaded
                        self.broadcast_update(task)

            shutil.move(str(temp_output), str(output_path))
            task.downloadedBytes = downloaded
            task.totalBytes = downloaded
            task.progress = 100.0
            task.speed = 0

            if task.downloadSubtitles:
                await self._download_subtitles(task)

            await self._finalize_task(task)

    async def _apply_throttle(self, task: DownloadTask, bytes_read: int):
        speed_limit = task.maxSpeedLimit if task.maxSpeedLimit > 0 else self.global_speed_limit
        if speed_limit <= 0:
            return

        now_ms = time.time() * 1000
        if task.throttleStartTimeMs == 0:
            task.throttleStartTimeMs = now_ms
            task.throttleBytesWritten = 0

        task.throttleBytesWritten += bytes_read
        elapsed_ms = max(1.0, now_ms - task.throttleStartTimeMs)

        expected_time_ms = (task.throttleBytesWritten * 1000.0) / speed_limit
        sleep_time_ms = expected_time_ms - elapsed_ms

        if sleep_time_ms > 0:
            await asyncio.sleep(min(sleep_time_ms / 1000.0, 1.0))

        if elapsed_ms > 2000 or task.throttleBytesWritten > 1024 * 1024:
            task.throttleStartTimeMs = time.time() * 1000
            task.throttleBytesWritten = 0

    async def _finalize_task(self, task: DownloadTask):
        task.progress = 100.0
        task.speed = 0

        # Muxing FFmpeg si sous-titres présents
        if task.savePathSubtitle and self.is_ffmpeg_available():
            task.status = DownloadStatus.MUXING
            self.broadcast_update(task)
            library_service.save_task(task)
            await asyncio.to_thread(self._mux_subtitles_with_ffmpeg, task)

        # Vérification d'intégrité automatique du fichier téléchargé
        verif = await asyncio.to_thread(
            verification_service.verify_file,
            file_path_str=task.savePath,
            anime_name=task.animeName,
            file_name=task.fileName,
            expected_size=task.totalBytes
        )

        if verif.relocatedPath and verif.relocatedPath != task.savePath:
            task.savePath = verif.relocatedPath

        task.verificationStatus = verif.status
        task.verifiedAt = datetime.now(timezone.utc)
        task.videoDuration = verif.duration
        task.verificationError = verif.error

        if verif.valid:
            task.status = DownloadStatus.COMPLETED
            task.completedAt = datetime.now(timezone.utc)
            self.broadcast_update(task)
            library_service.save_task(task)

            # Progression
            library_service.mark_as_downloaded(
                task.downloadPageUrl or "",
                task.animeName,
                task.episodeNumber,
                ""
            )
            logger.info("Téléchargement terminé et validé : %s (%s, durée: %s)", task.fileName, task.formattedTotalSize, verif.formattedDuration)

            if self.plex_organization:
                await asyncio.to_thread(self._generate_nfo_files, task)
        else:
            task.status = DownloadStatus.FAILED
            task.error = f"Vérification d'intégrité échouée : {verif.error}"
            self.broadcast_update(task)
            library_service.save_task(task)
            logger.error("Téléchargement échoué après vérification pour %s : %s", task.fileName, verif.error)

    # -------------------------------------------------------------------------
    # Sous-titres & FFmpeg
    # -------------------------------------------------------------------------

    async def _download_subtitles(self, task: DownloadTask):
        subs: List[Dict[str, str]] = []
        if task.subtitlesJson:
            try:
                subs = json.loads(task.subtitlesJson)
            except Exception:
                pass

        if not subs and task.subtitleUrl:
            subs.append({"url": task.subtitleUrl, "label": "Sous-titres", "lang": "fr"})

        if not subs:
            return

        downloaded_paths = []
        headers = {"User-Agent": proxy_service.get_user_agent(), "Referer": "https://vidzy.live/"}
        proxy = proxy_service.get_random_proxy()

        async with httpx.AsyncClient(headers=headers, proxy=proxy, timeout=15.0, follow_redirects=True, verify=False) as client:
            for sub in subs:
                url = sub.get("url", "")
                label = sub.get("label", "Sous-titres")
                if not url:
                    continue

                try:
                    ext = ".srt" if ".srt" in url else ".ass" if ".ass" in url else ".vtt"
                    clean_lbl = re.sub(r'[<>:"/\\|?*]', "_", label)
                    sub_name = f"{re.sub(r'\.(mp4|mkv|avi)$', '', task.fileName)}.{clean_lbl}{ext}"
                    sub_path = str(Path(task.savePath).parent / sub_name)

                    resp = await client.get(url)
                    if resp.status_code == 200:
                        with open(sub_path, "wb") as f:
                            f.write(resp.content)
                        downloaded_paths.append(sub_path)
                        logger.info("Sous-titres téléchargés: %s", sub_name)
                except Exception as e:
                    logger.warning("Erreur téléchargement sous-titres %s: %s", label, e)

        if downloaded_paths:
            task.savePathSubtitle = json.dumps(downloaded_paths)

    def is_ffmpeg_available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def _mux_subtitles_with_ffmpeg(self, task: DownloadTask):
        if not self.is_ffmpeg_available():
            return
        video_path = Path(task.savePath)
        if not video_path.exists():
            return

        sub_paths = []
        if task.savePathSubtitle:
            try:
                sub_paths = json.loads(task.savePathSubtitle)
            except Exception:
                sub_paths = [task.savePathSubtitle]

        existing_subs = [Path(sp) for sp in sub_paths if Path(sp).exists()]
        if not existing_subs:
            return

        base_name = re.sub(r"\.(mp4|mkv|avi)$", "", str(video_path))
        output_path = f"{base_name}.mkv"

        cmd = ["ffmpeg", "-y", "-i", str(video_path)]
        for sf in existing_subs:
            cmd.extend(["-i", str(sf)])

        cmd.extend(["-map", "0:v", "-map", "0:a"])
        for i in range(len(existing_subs)):
            cmd.extend(["-map", str(i + 1)])

        cmd.extend(["-c:v", "copy", "-c:a", "copy", "-c:s", "srt"])

        for i, sf in enumerate(existing_subs):
            lbl = sf.stem.replace(video_path.stem, "").strip(".") or f"Sous-titres {i + 1}"
            lang = "fre" if "fr" in lbl.lower() else "und"
            cmd.extend([f"-metadata:s:s:{i}", f"language={lang}", f"-metadata:s:s:{i}", f"title={lbl}"])

        cmd.append(output_path)

        try:
            logger.info("Muxing FFmpeg avec commande: %s", " ".join(cmd))
            ret = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ret.returncode == 0 and Path(output_path).exists() and Path(output_path).stat().st_size > 0:
                task.fileName = Path(output_path).name
                task.savePath = output_path
                task.savePathSubtitle = None
                video_path.unlink(missing_ok=True)
                for sf in existing_subs:
                    sf.unlink(missing_ok=True)
                library_service.save_task(task)
                logger.info("Muxing FFmpeg réussi: %s", Path(output_path).name)
        except Exception as e:
            logger.error("Erreur FFmpeg: %s", e)

    # -------------------------------------------------------------------------
    # Plex / Jellyfin NFO
    # -------------------------------------------------------------------------

    def _generate_nfo_files(self, task: DownloadTask):
        try:
            video_file = Path(task.savePath)
            season_dir = video_file.parent
            anime_dir = season_dir.parent

            tvshow_nfo = anime_dir / "tvshow.nfo"
            if not tvshow_nfo.exists():
                synopsis = ""
                studio = ""
                genres = []

                # Favoris ou recherche pour métadonnées
                fav = next((f for f in library_service.get_all_favorites() if f.title.lower() == task.animeName.lower()), None)
                detail = None
                if fav:
                    # Sync detail lookup
                    pass

                content = (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
                    '<tvshow>\n'
                    f'    <title>{saxutils.escape(task.animeName)}</title>\n'
                    f'    <plot>{saxutils.escape(synopsis)}</plot>\n'
                    f'    <studio>{saxutils.escape(studio)}</studio>\n'
                )
                for g in genres:
                    content += f'    <genre>{saxutils.escape(g)}</genre>\n'
                content += '</tvshow>\n'

                with open(tvshow_nfo, "w", encoding="utf-8") as f:
                    f.write(content)

            ep_nfo = season_dir / f"{video_file.stem}.nfo"
            ep_content = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
                '<episodedetails>\n'
                f'    <title>{saxutils.escape(f"Épisode {task.episodeNumber}")}</title>\n'
                f'    <episode>{task.episodeNumber}</episode>\n'
                '    <season>1</season>\n'
                f'    <plot>{saxutils.escape(f"{task.animeName} - Épisode {task.episodeNumber}")}</plot>\n'
                '</episodedetails>\n'
            )
            with open(ep_nfo, "w", encoding="utf-8") as f:
                f.write(ep_content)
        except Exception as e:
            logger.error("Erreur génération NFO: %s", e)

    # -------------------------------------------------------------------------
    # SSE Broadcast
    # -------------------------------------------------------------------------

    def subscribe_sse(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.sse_subscribers.append(q)
        # Send initial snapshot
        for t in self.get_all_tasks():
            q.put_nowait(t.to_dict())
        return q

    def unsubscribe_sse(self, q: asyncio.Queue):
        if q in self.sse_subscribers:
            self.sse_subscribers.remove(q)

    def broadcast_update(self, task: DownloadTask):
        data = task.to_dict()
        for q in list(self.sse_subscribers):
            try:
                q.put_nowait(data)
            except Exception:
                if q in self.sse_subscribers:
                    self.sse_subscribers.remove(q)

    # -------------------------------------------------------------------------
    # Ticker / Scheduled Downloads
    # -------------------------------------------------------------------------

    async def check_scheduled_tasks(self):
        now_naive = datetime.now()
        now_utc = datetime.now(timezone.utc)
        for t in self.tasks.values():
            if t.status == DownloadStatus.SCHEDULED and t.scheduledStartTime:
                now = now_utc if t.scheduledStartTime.tzinfo else now_naive
                if t.scheduledStartTime <= now:
                    t.status = DownloadStatus.PENDING
                    self.broadcast_update(t)
        await self.process_queue()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def sanitize_file_name(self, name: str) -> str:
        if not name:
            return "download"
        clean = re.sub(r'[<>:"/\\|?*]', "_", name)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean or "download"

    def _needs_scraping_resolution(self, url: str) -> bool:
        if not url:
            return False
        if re.search(r"\.(mp4|mkv|avi|webm)(\?.*)?$", url):
            return False
        if "vidzy.live" in url or "luluvdo.com" in url or "french-manga.net" in url:
            return True
        if "vidzy.cc" in url and any(x in url for x in ["/e/", "/d/", "embed-"]):
            return True
        return not bool(re.search(r"\.(mp4|mkv|avi|webm|ts|m4v)(\?.*)?$", url))

download_manager = DownloadManagerService()
