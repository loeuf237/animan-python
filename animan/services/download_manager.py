import asyncio
import json
import logging
import math
import re
import shutil
import socket
import subprocess
import time
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse

import httpx

from animan.config import settings
from animan.models.download_task import DownloadTask, DownloadStatus, format_bytes
from animan.services.library_service import library_service
from animan.services.proxy_service import proxy_service
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.verification_service import verification_service, VerificationResult
from animan.security import is_safe_path

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
        self.qualities_sizes_json: str = "{}"

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

    def _create_async_client(
        self,
        headers: Optional[Dict[str, str]] = None,
        proxy: Optional[str] = None,
        timeout: Any = 10.0,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        proxy_val = proxy or proxy_service.get_random_proxy()
        try:
            return httpx.AsyncClient(
                headers=headers,
                proxy=proxy_val,
                timeout=timeout,
                follow_redirects=follow_redirects,
                verify=settings.SSL_VERIFY,
            )
        except Exception as e:
            logger.warning("[download_manager] Erreur initialisation proxy client HTTP (%s): %s - bascule en direct sans proxy", proxy_val, e)
            return httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                follow_redirects=follow_redirects,
                verify=settings.SSL_VERIFY,
                trust_env=False,
            )

    def _trigger_process_queue(self):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.process_queue())
        except RuntimeError:
            pass

    async def is_client_online(self) -> bool:
        """
        Vérifie si la machine locale dispose d'un accès actif au réseau Internet.
        Permet de distinguer formellement une coupure locale (perte Wi-Fi / 4G / câble débranché)
        d'une indisponibilité spécifique du serveur d'hébergement distant.
        """
        loop = asyncio.get_running_loop()

        def _socket_probe() -> bool:
            for host, port in [("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53)]:
                try:
                    s = socket.create_connection((host, port), timeout=2.0)
                    s.close()
                    return True
                except Exception:
                    continue
            return False

        try:
            if await loop.run_in_executor(None, _socket_probe):
                return True
        except Exception:
            pass

        # Fallback HTTP au cas où les ports DNS UDP/TCP 53 soient bloqués
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                r = await client.head("http://connectivitycheck.gstatic.com/generate_204")
                if r.status_code in (200, 204):
                    return True
        except Exception:
            pass

        return False

    def init_from_db(self):
        try:
            unfinished = library_service.get_unfinished_tasks()
            for entity in unfinished:
                task = entity.to_task()
                # Vérifier si le fichier final est en réalité déjà complet et valide sur disque
                if task.savePath:
                    out_path = Path(task.savePath)
                    part_path = Path(task.savePath + ".part")
                    if out_path.exists() and out_path.stat().st_size > 1024 * 1024:
                        verif = verification_service.verify_file(str(out_path), task.animeName, task.fileName)
                        if verif.valid:
                            task.status = DownloadStatus.COMPLETED
                            task.progress = 100.0
                            task.downloadedBytes = out_path.stat().st_size
                            task.totalBytes = max(task.totalBytes, out_path.stat().st_size)
                            task.verificationStatus = verif.status
                            task.videoDuration = verif.duration
                            task.error = None
                            library_service.save_task(task)
                            library_service.mark_as_downloaded(task.downloadPageUrl or "", task.animeName, task.episodeNumber, "")
                            self.tasks[task.id] = task
                            self.task_order.append(task.id)
                            continue
                    elif part_path.exists() and part_path.stat().st_size > 0:
                        task.downloadedBytes = part_path.stat().st_size
                        if task.totalBytes > 0:
                            task.progress = min(99.9, (task.downloadedBytes / task.totalBytes) * 100.0)

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

    def get_headers_for_url(self, url: str, server_type: Optional[str] = None) -> Dict[str, str]:
        ua = proxy_service.get_user_agent()
        headers = {"User-Agent": ua}
        u_lower = (url or "").lower()
        s_lower = (server_type or "").lower()

        if "tapecontent.net" in u_lower or "streamtape.com" in u_lower or s_lower in ["stape", "streamtape"]:
            headers["Referer"] = "https://streamtape.com/"
        elif any(h in u_lower for h in ["kwik", "animepahe", "pahe"]) or s_lower == "kwik":
            headers["Referer"] = "https://kwik.cx/"
        elif any(h in u_lower for h in ["voembed", "vidmoly", "vmeas.cloud", "vmpx.online"]) or s_lower in ["mytv", "vidmoly", "voembed"]:
            headers["Referer"] = "https://voembed.net/"
        elif "mail.ru" in u_lower or s_lower in ["fhd1", "mailru"]:
            headers["Referer"] = "https://my.mail.ru/"
        elif any(h in u_lower for h in ["voe.sx", "johnfullwonder", "voe-un-block"]) or s_lower == "voe":
            headers["Referer"] = "https://voe.sx/"
        elif any(h in u_lower for h in ["gn1r5n", "byse", "weneverbeenfree"]) or s_lower == "moon":
            headers["Referer"] = "https://gn1r5n.org/"
            headers["X-Embed-Origin"] = "voir-anime.to"
            headers["X-Embed-Referer"] = "https://voir-anime.to/"
        elif "vidzy" in u_lower or s_lower == "vidzy":
            headers["Referer"] = "https://vidzy.live/"
        else:
            try:
                parsed = urlparse(url)
                if parsed.scheme and parsed.netloc:
                    headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
                else:
                    headers["Referer"] = "https://vidzy.live/"
            except Exception:
                headers["Referer"] = "https://vidzy.live/"

        return headers

    async def get_remote_file_size(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        server_type: Optional[str] = None,
    ) -> int:
        if not url:
            return -1
        if ".m3u8" in url.lower():
            return await self.estimate_hls_size(url, headers=headers, server_type=server_type)

        try:
            req_headers = headers or self.get_headers_for_url(url, server_type)
            async with self._create_async_client(
                headers=req_headers,
                timeout=8.0,
                follow_redirects=True,
            ) as client:
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
                if cl2 and cl2.isdigit() and int(cl2) > 0 and range_resp.status_code == 200:
                    return int(cl2)
        except Exception as e:
            logger.debug("Erreur get_remote_file_size pour %s: %s", url, e)
        return -1

    async def estimate_hls_size(
        self,
        m3u8_url: str,
        headers: Optional[Dict[str, str]] = None,
        bandwidth: Optional[int] = None,
        server_type: Optional[str] = None,
    ) -> int:
        if not m3u8_url:
            return -1
        req_headers = headers or self.get_headers_for_url(m3u8_url, server_type or "myTV")

        try:
            async with self._create_async_client(
                headers=req_headers,
                timeout=8.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(m3u8_url)
                if resp.status_code != 200:
                    return -1

                text = resp.text
                target_variant_url = m3u8_url
                est_bandwidth = bandwidth or 0

                # Cas 1: Master playlist (#EXT-X-STREAM-INF)
                if "#EXT-X-STREAM-INF:" in text:
                    lines = text.strip().splitlines()
                    best_bw = 0
                    chosen_rel = ""
                    for i, line in enumerate(lines):
                        line_s = line.strip()
                        if line_s.startswith("#EXT-X-STREAM-INF:"):
                            bw_m = re.search(r"BANDWIDTH=(\d+)", line_s)
                            bw = int(bw_m.group(1)) if bw_m else 0
                            if i + 1 < len(lines):
                                cand_url = lines[i + 1].strip()
                                if not cand_url.startswith("#") and bw >= best_bw:
                                    best_bw = bw
                                    chosen_rel = cand_url
                    if chosen_rel:
                        target_variant_url = urljoin(m3u8_url, chosen_rel)
                        if best_bw > 0:
                            est_bandwidth = best_bw
                        v_resp = await client.get(target_variant_url)
                        if v_resp.status_code == 200:
                            text = v_resp.text

                # Cas 2: Analyse de la variante
                durations = [float(d) for d in re.findall(r"#EXTINF:([\d.]+)", text)]
                total_duration = sum(durations)
                segs = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]

                if not segs:
                    return -1

                if total_duration <= 0:
                    td_m = re.search(r"#EXT-X-TARGETDURATION:(\d+)", text)
                    target_dur = float(td_m.group(1)) if td_m else 10.0
                    total_duration = len(segs) * target_dur

                if est_bandwidth > 0 and total_duration > 0:
                    return int((est_bandwidth * total_duration) / 8)

                # Fallback: échantillonnage parallèle HEAD de 2 à 3 segments
                sample_indices = list(set([0, len(segs) // 2, max(0, len(segs) - 2)]))

                async def sample_seg(idx: int) -> int:
                    seg_u = segs[idx]
                    if not seg_u.startswith("http"):
                        seg_u = urljoin(target_variant_url, seg_u)
                    try:
                        hr = await client.head(seg_u, timeout=5.0)
                        cl = hr.headers.get("Content-Length")
                        if cl and cl.isdigit() and int(cl) > 0:
                            return int(cl)
                    except Exception:
                        pass
                    return -1

                sampled_results = await asyncio.gather(*(sample_seg(i) for i in sample_indices), return_exceptions=True)
                valid_samples = [s for s in sampled_results if isinstance(s, int) and s > 0]
                if valid_samples:
                    avg_seg_size = sum(valid_samples) / len(valid_samples)
                    return int(avg_seg_size * len(segs))

                if total_duration > 0:
                    return int((1_800_000 * total_duration) / 8)

        except Exception as e:
            logger.debug("Erreur estimate_hls_size pour %s: %s", m3u8_url, e)

        return -1

    async def get_or_resolve_episode_info(
        self,
        download_page_url: str,
        preferred_server: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ResolvedVideoInfo]:
        if not download_page_url:
            return None
        eff_server_key = preferred_server or self.voiranime_default_server
        cache_key = f"{download_page_url}::{eff_server_key}::{preferred_quality or ''}"
        if cache_key in self.resolved_info_cache:
            return self.resolved_info_cache[cache_key]

        async with self._info_semaphore:
            if cache_key in self.resolved_info_cache:
                return self.resolved_info_cache[cache_key]

            try:
                info = ResolvedVideoInfo()
                is_voir_anime = "voir-anime" in download_page_url
                is_animepahe = any(k in download_page_url for k in ["animepahe", "kwik.", "pahe."])

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
                    info.qualities_sizes_json = dl_info.get("qualitiesSizes", "{}")

                    # Si extract_download_info a déjà extrait une taille positive
                    if dl_info.get("size") and int(dl_info.get("size", -1)) > 0:
                        info.size = int(dl_info["size"])
                elif is_animepahe:
                    from animan.services.animepahe_service import animepahe_service
                    info.server_type = "kwik"
                    info.available_servers = ["kwik"]

                    if ("kwik." in download_page_url or "pahe." in download_page_url) and ("/e/" in download_page_url or "/d/" in download_page_url):
                        direct_url = await animepahe_service.extract_kwik_stream(download_page_url)
                        dl_info = {
                            "videoUrl": direct_url or "",
                            "serverType": "kwik",
                            "selectedQuality": preferred_quality or "HD",
                            "videoQualities": json.dumps({preferred_quality or "HD": download_page_url}),
                        }
                    elif preferred_server and ("kwik." in preferred_server or "pahe." in preferred_server):
                        direct_url = await animepahe_service.extract_kwik_stream(preferred_server)
                        dl_info = {
                            "videoUrl": direct_url or "",
                            "serverType": "kwik",
                            "selectedQuality": preferred_quality or "HD",
                        }
                    else:
                        sources = await animepahe_service.get_episode_sources(download_page_url)
                        qualities = {}
                        qualities_sizes = {}
                        target = None
                        for s in sources:
                            q_name = s.get("name") or f"{s.get('quality', 'HD')} ({s.get('audio', 'sub')})"
                            raw_q = (s.get("quality") or "").lower()
                            qualities[q_name] = s.get("url", "")

                            # Estimation de la taille selon la résolution sans appeler Kwik pour éviter le code 429
                            if "360" in raw_q or "360" in q_name:
                                est_bytes = 95 * 1024 * 1024
                            elif "1080" in raw_q or "1080" in q_name:
                                est_bytes = 420 * 1024 * 1024
                            else:
                                est_bytes = 220 * 1024 * 1024
                            qualities_sizes[q_name] = format_bytes(est_bytes)

                            if preferred_quality and (preferred_quality.lower() in q_name.lower() or preferred_quality.lower() in raw_q):
                                if not target:
                                    target = s
                        if not target and sources:
                            target = sources[0]

                        sel_q = preferred_quality or "HD"
                        target_url = ""
                        target_size = 220 * 1024 * 1024
                        if target:
                            sel_q = target.get("name") or target.get("quality", "HD")
                            target_url = target.get("url", "")
                            raw_tq = (target.get("quality") or "").lower()
                            if "360" in raw_tq or "360" in sel_q:
                                target_size = 95 * 1024 * 1024
                            elif "1080" in raw_tq or "1080" in sel_q:
                                target_size = 420 * 1024 * 1024
                            else:
                                target_size = 220 * 1024 * 1024

                        dl_info = {
                            "videoUrl": target_url,
                            "serverType": "kwik",
                            "selectedQuality": sel_q,
                            "videoQualities": json.dumps(qualities),
                            "qualitiesSizes": json.dumps(qualities_sizes),
                            "size": target_size,
                        }
                    info.video_qualities_json = dl_info.get("videoQualities", "{}")
                    info.qualities_sizes_json = dl_info.get("qualitiesSizes", "{}")
                    info.selected_server = "kwik"
                    info.selected_quality = dl_info.get("selectedQuality", "")
                    if dl_info.get("size"):
                        info.size = dl_info["size"]
                else:
                    # Vérifier si l'URL correspond à une extension Aniyomi active
                    matched_container = None
                    try:
                        from animan.services.extension_service import extension_service
                        parsed_u = urlparse(download_page_url)
                        u_host = (parsed_u.hostname or "").lower()
                        if u_host:
                            for cs in extension_service.get_enabled_container_sources():
                                if cs.base_url and u_host in cs.base_url.lower():
                                    matched_container = cs
                                    break
                    except Exception:
                        pass

                    if matched_container:
                        video_sources = await matched_container.get_episode_sources(download_page_url)
                        qualities = {}
                        target = None
                        for s in video_sources:
                            q_name = s.quality or s.server
                            qualities[q_name] = s.url
                            if preferred_quality and (preferred_quality.lower() in q_name.lower()):
                                if not target:
                                    target = s
                        if not target and video_sources:
                            target = video_sources[0]

                        dl_info = {
                            "videoUrl": target.url if target else "",
                            "serverType": target.server if target else "aniyomi",
                            "selectedQuality": target.quality if target else "HD",
                            "videoQualities": json.dumps(qualities),
                        }
                        info.server_type = dl_info["serverType"]
                        info.available_servers = [s.server for s in video_sources]
                        info.video_qualities_json = dl_info["videoQualities"]
                        info.selected_server = info.server_type
                        info.selected_quality = dl_info["selectedQuality"]
                    else:
                        dl_info = await asyncio.to_thread(scraping_service.extract_download_info, download_page_url)
                        info.server_type = "vidzy"

                info.direct_url = dl_info.get("videoUrl", "")
                info.subtitle_url = dl_info.get("subtitleUrl", "")
                info.subtitles_json = dl_info.get("subtitles", "[]")

                # Si la taille n'est pas encore déterminée
                if info.size <= 0 and info.direct_url:
                    if ".m3u8" in info.direct_url.lower() or info.server_type == "myTV":
                        info.size = await self.estimate_hls_size(info.direct_url, server_type=info.server_type)
                    else:
                        info.size = await self.get_remote_file_size(info.direct_url, server_type=info.server_type)

                info.formatted_size = format_bytes(info.size) if info.size > 0 else "Taille inconnue"

                # Si qualities_sizes_json est vide mais qu'on a la taille, générer pour la qualité sélectionnée
                if (not info.qualities_sizes_json or info.qualities_sizes_json == "{}") and info.size > 0:
                    info.qualities_sizes_json = json.dumps({info.selected_quality or "HD": info.formatted_size})

                # Mettre en cache seulement les résultats avec taille valide
                if info.size > 0:
                    self.resolved_info_cache[cache_key] = info

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
        cached = self.resolved_info_cache.get(cache_key)
        if not cached and not (selected_server or selected_quality):
            cached = self.resolved_info_cache.get(download_page_url)
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

        if not is_safe_path(anime_dir, [self.download_dir]):
            anime_dir = Path(self.download_dir) / "Downloads"

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
            if existing and existing.exists() and existing.stat().st_size > 1024 * 1024:
                verif = verification_service.verify_file(str(existing), anime_name, name)
                if verif.valid:
                    logger.info("Batch: %s Ep%d existe déjà et est valide (%s), ignoré",
                                anime_name, ep_num, format_bytes(existing.stat().st_size))
                    library_service.mark_as_downloaded(url, anime_name, ep_num, "")
                    continue

            if existing:
                cache_key = f"{url}::{sel_server or ''}::{sel_quality or ''}"
                cached = self.resolved_info_cache.get(cache_key)
                if not cached and not (sel_server or sel_quality):
                    cached = self.resolved_info_cache.get(url)
                if cached and cached.size > 0 and existing.stat().st_size == cached.size:
                    logger.info("Batch: %s Ep%d existe déjà avec la même taille, ignoré", anime_name, ep_num)
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
            cached = self.resolved_info_cache.get(cache_key)
            if not cached and not (sel_server or sel_quality):
                cached = self.resolved_info_cache.get(url)
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
            t.retryCount = 0
            t.directDownloadUrl = None  # Forcer la re-résolution pour obtenir un token CDN frais

            # Détecter le fichier partiel existant (.part ou savePath) pour reprise
            if t.savePath:
                part_path = Path(t.savePath + ".part")
                out_path = Path(t.savePath)
                if out_path.exists() and out_path.stat().st_size > 1024 * 1024:
                    verif = verification_service.verify_file(str(out_path), t.animeName, t.fileName)
                    if verif.valid:
                        t.status = DownloadStatus.COMPLETED
                        t.progress = 100.0
                        t.downloadedBytes = out_path.stat().st_size
                        t.totalBytes = max(t.totalBytes, out_path.stat().st_size)
                        t.verificationStatus = verif.status
                        t.videoDuration = verif.duration
                        self.broadcast_update(t)
                        library_service.save_task(t)
                        library_service.mark_as_downloaded(t.downloadPageUrl or "", t.animeName, t.episodeNumber, "")
                        return True

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
        cancellable_statuses = [
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PENDING,
            DownloadStatus.RETRYING,
            DownloadStatus.SCHEDULED,
            DownloadStatus.PAUSED,
            DownloadStatus.MUXING,
        ]
        if t and t.status in cancellable_statuses:
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
            library_service.save_task(t)
            self._trigger_process_queue()
            return True
        elif not t:
            entity = library_service.get_task_entity(task_id)
            if entity and entity.status in [s.value for s in cancellable_statuses]:
                task = entity.to_task()
                task.cancelled = True
                task.paused = False
                task.status = DownloadStatus.CANCELLED
                task.speed = 0
                library_service.save_task(task)
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
        if task_id in self.task_order:
            self.task_order.remove(task_id)
        if t:
            t.cancelled = True
            proc = getattr(t, "activeProcess", None)
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
            if t.savePath:
                out_p = Path(t.savePath)
                Path(t.savePath + ".part").unlink(missing_ok=True)
                out_p.with_suffix(".tmp.mp4").unlink(missing_ok=True)
                seg_d = out_p.parent / f".{out_p.stem}_segments"
                if seg_d.exists():
                    shutil.rmtree(seg_d, ignore_errors=True)
        deleted_from_db = library_service.delete_task_entity(task_id)
        self._trigger_process_queue()
        return (t is not None) or deleted_from_db

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
        try:
            for entity in library_service.get_unfinished_tasks():
                if entity.id not in self.tasks:
                    task = entity.to_task()
                    self.tasks[task.id] = task
                    if task.id not in self.task_order:
                        self.task_order.append(task.id)
        except Exception as e:
            logger.warning("Erreur rechargement tâches DB pour reprise: %s", e)

        for t in list(self.tasks.values()):
            if t.status in [DownloadStatus.PAUSED, DownloadStatus.FAILED]:
                t.paused = False
                t.cancelled = False
                t.retryCount = 0
                t.error = None
                t.directDownloadUrl = None

                if t.savePath:
                    out_path = Path(t.savePath)
                    part_path = Path(t.savePath + ".part")
                    if out_path.exists() and out_path.stat().st_size > 1024 * 1024:
                        verif = verification_service.verify_file(str(out_path), t.animeName, t.fileName)
                        if verif.valid:
                            t.status = DownloadStatus.COMPLETED
                            t.progress = 100.0
                            t.downloadedBytes = out_path.stat().st_size
                            t.totalBytes = max(t.totalBytes, out_path.stat().st_size)
                            t.verificationStatus = verif.status
                            t.videoDuration = verif.duration
                            self.broadcast_update(t)
                            library_service.save_task(t)
                            library_service.mark_as_downloaded(t.downloadPageUrl or "", t.animeName, t.episodeNumber, "")
                            continue
                    elif part_path.exists() and part_path.stat().st_size > 0:
                        if t.totalBytes > 0 and part_path.stat().st_size > t.totalBytes:
                            part_path.unlink(missing_ok=True)
                            t.downloadedBytes = 0
                        else:
                            t.downloadedBytes = part_path.stat().st_size
                        if t.totalBytes > 0 and t.downloadedBytes > 0:
                            t.progress = min(99.9, (t.downloadedBytes / t.totalBytes) * 100.0)

                t.status = DownloadStatus.PENDING
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
            max_retries = 15  # Tolérance robuste face aux coupures réseau et expirations CDN
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
                    is_animepahe = any(k in (direct_url or "").lower() for k in ["animepahe", "kwik.", "pahe."])
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
                        from animan.services.source_settings_service import source_settings_service
                        va_settings = source_settings_service.get_source_settings("voir-anime")
                        va_strategy = va_settings.get("quality_strategy", "highest")
                        pref_srv = task.selectedServer or self.voiranime_default_server
                        # Si échec répété du serveur distant (client confirmé en ligne) ou erreur HTML, repli sur serveurs alternatifs
                        consec_errs = getattr(task, "consecutiveServerErrors", 0)
                        client_offline = getattr(task, "clientOffline", False)
                        has_html_err = "html" in (task.error or "").lower()
                        # Le basculement vers d'autres hébergeurs n'intervient que sur pannes serveur avérées répétées ou page HTML d'erreur
                        if not client_offline and (consec_errs >= 2 or has_html_err):
                            logger.info("[download_manager] Repli sur les serveurs alternatifs pour %s après échecs confirmés sur %s", task.fileName, pref_srv)
                            if pref_srv:
                                part_clean = Path(task.savePath + ".part")
                                if part_clean.exists():
                                    part_clean.unlink(missing_ok=True)
                                segments_clean = Path(task.savePath).parent / f".{Path(task.savePath).stem}_segments"
                                if segments_clean.exists():
                                    shutil.rmtree(segments_clean, ignore_errors=True)
                                task.downloadedBytes = 0
                                task.progress = 0.0
                            pref_srv = None
                            task.selectedServer = None
                            task.selectedQuality = None

                        info = await asyncio.to_thread(
                            voiranime_service.extract_download_info,
                            direct_url,
                            preferred_server=pref_srv,
                            preferred_quality=task.selectedQuality,
                            quality_strategy=va_strategy,
                        )
                        direct_url = info.get("videoUrl", "")
                        if not direct_url:
                            raise ValueError(f"Impossible d'extraire l'URL vidéo pour {task.fileName}")
                        server_type = info.get("serverType", "unknown")
                        chunks_json = info.get("videoChunks", "[]")
                        task.directDownloadUrl = direct_url
                        if not task.subtitleUrl and info.get("subtitleUrl"):
                            task.subtitleUrl = info["subtitleUrl"]
                    elif is_animepahe:
                        from animan.services.animepahe_service import animepahe_service
                        server_type = "kwik"
                        if ("kwik." in direct_url or "pahe." in direct_url) and ("/e/" in direct_url or "/d/" in direct_url):
                            extracted = await animepahe_service.extract_kwik_stream(direct_url)
                            if not extracted:
                                raise ValueError(f"Impossible de résoudre le flux Kwik pour {task.fileName}")
                            direct_url = extracted
                        elif task.selectedServer and ("kwik." in task.selectedServer or "pahe." in task.selectedServer):
                            extracted = await animepahe_service.extract_kwik_stream(task.selectedServer)
                            if not extracted:
                                raise ValueError(f"Impossible de résoudre le flux Kwik sélectionné pour {task.fileName}")
                            direct_url = extracted
                        else:
                            sources = await animepahe_service.get_episode_sources(direct_url)
                            target = None
                            if task.selectedQuality and task.selectedQuality != "auto":
                                for s in sources:
                                    q_name = s.get("name") or s.get("quality", "")
                                    if task.selectedQuality.lower() in q_name.lower() or task.selectedQuality.lower() in s.get("quality", "").lower():
                                        target = s
                                        break
                            if not target and sources:
                                target = sources[0]
                            if not target or not target.get("url"):
                                raise ValueError(f"Aucune source Kwik trouvée pour {task.fileName}")
                            extracted = await animepahe_service.extract_kwik_stream(target["url"])
                            if not extracted:
                                raise ValueError(f"Échec d'extraction du flux vidéo Kwik pour {task.fileName}")
                            direct_url = extracted
                        task.directDownloadUrl = direct_url
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

                    need_resolve = False  # Les retries suivants réutiliseront l'URL sauf si déconnexion

                    if server_type == "myTV" and chunks_json != "[]":
                        chunks = json.loads(chunks_json)
                        if len(chunks) > 1:
                            await self._download_mytv_chunks(task, chunks)
                            return

                    bytes_before = task.downloadedBytes
                    is_hls = bool(direct_url and (".m3u8" in direct_url.lower()))
                    if is_hls:
                        await self._download_hls_stream(task, direct_url)
                        return

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

                    bytes_gained = task.downloadedBytes - bytes_before if 'bytes_before' in locals() else 0
                    if bytes_gained > 0:
                        logger.info("Progrès de %s octets pour %s malgré coupure réseau, maintien de l'hébergeur %s et réinitialisation des erreurs serveur",
                                    format_bytes(bytes_gained), task.fileName, task.selectedServer)
                        task.retryCount = max(0, task.retryCount - 1)
                        task.consecutiveServerErrors = 0

                    err_msg = str(e).lower()

                    # 1. Tester d'abord si la machine locale est déconnectée d'Internet
                    client_online = await self.is_client_online()
                    if not client_online:
                        task.clientOffline = True
                        logger.warning(
                            "[download_manager] Coupure Internet locale détectée pour %s (erreur: %s). "
                            "Conservation de l'hébergeur %s et des données partielles. En attente du rétablissement réseau...",
                            task.fileName, err_msg, task.selectedServer
                        )
                        task.status = DownloadStatus.RETRYING
                        task.error = "Connexion Internet locale interrompue. En attente du rétablissement réseau..."
                        task.speed = 0
                        self.broadcast_update(task)
                        library_service.save_task(task)

                        # Attente active du retour de la connexion sans consommer les retries serveur ni changer d'hôte
                        while not task.cancelled and not task.paused:
                            await asyncio.sleep(5.0)
                            if await self.is_client_online():
                                logger.info(
                                    "[download_manager] Connexion Internet rétablie pour %s ! Reprise du téléchargement sur l'hébergeur %s.",
                                    task.fileName, task.selectedServer
                                )
                                task.clientOffline = False
                                need_resolve = True  # Re-résoudre sur le même serveur en cas de token/lien direct expiré
                                task.directDownloadUrl = None
                                break
                        continue

                    task.clientOffline = False

                    if task.retryCount < max_retries:
                        task.retryCount += 1

                        # Détection des coupures réseau distantes, timeouts, expirations CDN ou réponses invalides de l'hébergeur
                        is_disconnect = (
                            "peer closed connection" in err_msg
                            or "remote protocol" in err_msg
                            or "connection reset" in err_msg
                            or "connection closed" in err_msg
                            or "incompleteread" in err_msg
                            or "broken pipe" in err_msg
                            or "readtimeout" in err_msg
                            or "connecttimeout" in err_msg
                            or "timeout" in err_msg
                            or "416" in err_msg
                            or "403" in err_msg
                            or "401" in err_msg
                            or "404" in err_msg
                            or "410" in err_msg
                            or "502" in err_msg
                            or "503" in err_msg
                            or "html" in err_msg
                        )
                        if is_disconnect:
                            if bytes_gained <= 0:
                                task.consecutiveServerErrors = getattr(task, "consecutiveServerErrors", 0) + 1
                                logger.info("Échec de connexion ou lien expiré sans progression (%s) pour %s, échecs serveur consécutifs: %d",
                                            err_msg, task.fileName, task.consecutiveServerErrors)
                            else:
                                task.consecutiveServerErrors = 0
                            need_resolve = True
                            task.directDownloadUrl = None
                        elif task.retryCount >= 2:
                            need_resolve = True
                            task.directDownloadUrl = None

                        # Détection des pannes DNS transitoires
                        is_dns = (
                            "name resolution" in err_msg
                            or "gaierror" in err_msg
                            or "temporary failure" in err_msg
                            or "nodename nor servname" in err_msg
                        )
                        if is_dns:
                            logger.warning("Panne DNS transitoire (%s) pour %s, temporisation 5s", err_msg, task.fileName)
                            await asyncio.sleep(5.0)
                            if task.retryCount > 0:
                                task.retryCount -= 1

                        task.status = DownloadStatus.RETRYING
                        task.error = f"Erreur serveur hébergeur: {str(e)}. Reprise ({task.retryCount}/{max_retries})"
                        self.broadcast_update(task)
                        library_service.save_task(task)

                        backoff = min(15.0, 2.0 + math.pow(1.3, min(task.retryCount, 10)))
                        await asyncio.sleep(backoff)
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

        if any(k in direct_url for k in ["kwik", "animepahe", "pahe"]):
            referer = "https://kwik.cx/"
        elif any(k in direct_url for k in ["streamtape", "tapecontent"]):
            referer = "https://streamtape.com/"
        elif "vidzy" in direct_url:
            referer = "https://vidzy.org/"
        elif "voir" in direct_url:
            referer = "https://voir-anime.to/"
        else:
            referer = "https://french-manga.net/"
        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": referer,
        }
        proxy = proxy_service.get_random_proxy()

        timeout = httpx.Timeout(connect=20.0, read=60.0, write=30.0, pool=None)
        async with self._create_async_client(headers=headers, proxy=proxy, timeout=timeout) as client:
            req_headers = dict(headers)
            is_resume = existing_len > 0
            if is_resume:
                req_headers["Range"] = f"bytes={existing_len}-"
                logger.info("Tentative de reprise pour %s depuis %s", task.fileName, format_bytes(existing_len))

            while True:
                async with client.stream("GET", direct_url, headers=req_headers) as stream_resp:
                    # Gestion du code 416 Range Not Satisfiable
                    if stream_resp.status_code == 416:
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
                        task.downloadedBytes = 0
                        req_headers.pop("Range", None)
                        raise ConnectionError("HTTP 416 (Range Not Satisfiable): Plage invalide, re-résolution requise")

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
                    task.reset_speed()
                    if downloaded > 0:
                        task.speed_tracker.add_sample(downloaded)
                    last_time = time.time()
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
                                task.reset_speed()
                                task.downloadedBytes = downloaded
                                self.broadcast_update(task)
                                library_service.save_task(task)
                                logger.info("Annulé %s — fichier .part conservé (%s)",
                                            task.fileName, format_bytes(downloaded))
                                return
                            if task.paused:
                                task.status = DownloadStatus.PAUSED
                                task.reset_speed()
                                task.downloadedBytes = downloaded
                                self.broadcast_update(task)
                                library_service.save_task(task)
                                logger.info("Pause %s — progression sauvegardée (%s)",
                                            task.fileName, format_bytes(downloaded))
                                return

                            f.write(chunk)
                            downloaded += len(chunk)

                            # Throttling
                            await self._apply_throttle(task, len(chunk))

                            now = time.time()
                            task.update_progress(downloaded, now)
                            if total_bytes > 0:
                                task.progress = min(100.0, (downloaded / total_bytes) * 100.0)

                            if now - last_time >= 0.5:
                                last_time = now
                                f.flush()
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

        async with self._create_async_client(headers=headers, proxy=proxy, timeout=settings.READ_TIMEOUT) as client:
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
                                task.reset_speed()
                                self.broadcast_update(task)
                                return
                            if task.paused:
                                task.status = DownloadStatus.PAUSED
                                task.reset_speed()
                                self.broadcast_update(task)
                                return

                            f.write(chunk)
                            chunk_downloaded += len(chunk)
                            cur_glob = downloaded_total + chunk_downloaded

                            await self._apply_throttle(task, len(chunk))

                            now = time.time()
                            task.update_progress(cur_glob, now)
                            if total_all_chunks > 0:
                                task.progress = (cur_glob / total_all_chunks) * 100.0

                            if now - last_time >= 0.5:
                                last_time = now
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
        # Si le flux provient de Kwik / Owocdn HLS, le router via le proxy HLS local
        # pour bénéficier du contournement Cloudflare TLS et du déchiffrement transparent AES-128
        is_kwik_owocdn = any(d in m3u8_url for d in ["owocdn.top", "kwik.cx", "kwik."])
        if is_kwik_owocdn and "/api/media/hls-proxy" not in m3u8_url:
            from urllib.parse import quote
            m3u8_url = f"http://127.0.0.1:{settings.PORT}/api/media/hls-proxy/playlist.m3u8?url={quote(m3u8_url)}"
            logger.info("Routage HLS AnimePahe via proxy local: %s", task.fileName)

        if task.totalBytes <= 0:
            try:
                est_sz = await self.estimate_hls_size(m3u8_url)
                if est_sz > 0:
                    task.totalBytes = est_sz
                    self.broadcast_update(task)
            except Exception:
                pass

        # Téléchargement natif par segments avec micro-retries in-situ et reprise sans perte
        await self._download_hls_segments_native(task, m3u8_url)

    async def _download_hls_segments_native(self, task: DownloadTask, m3u8_url: str):
        logger.info("Téléchargement HLS par segments (avec reprise) pour %s", task.fileName)
        output_path = Path(task.savePath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        segments_dir = output_path.parent / f".{output_path.stem}_segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": "https://voembed.net/",
        }
        proxy = proxy_service.get_random_proxy()

        timeout = httpx.Timeout(connect=20.0, read=45.0, write=30.0, pool=30.0)
        async with self._create_async_client(headers=headers, proxy=proxy, timeout=timeout) as client:
            resp = await client.get(m3u8_url)
            if resp.status_code != 200:
                raise ConnectionError(f"HTTP {resp.status_code} sur playlist m3u8")

            playlist_text = resp.text
            sub_url = m3u8_url
            # Si le m3u8 ne contient pas directement de tags #EXTINF, c'est une master playlist
            if "#EXTINF" not in playlist_text:
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

            # Analyser les segments déjà complétés sur le disque pour reprise instantanée sans perte
            existing_bytes = 0
            completed_indices = set()
            for idx in range(total_segments):
                sf = segments_dir / f"seg_{idx:05d}.ts"
                if sf.exists() and sf.stat().st_size > 0:
                    existing_bytes += sf.stat().st_size
                    completed_indices.add(idx)

            downloaded = existing_bytes
            if existing_bytes > 0:
                logger.info("Reprise HLS pour %s : %d/%d segments déjà présents (%s)",
                            task.fileName, len(completed_indices), total_segments, format_bytes(existing_bytes))
                task.downloadedBytes = downloaded
                if total_segments > 0:
                    task.progress = min(99.0, (len(completed_indices) / total_segments) * 100.0)
                self.broadcast_update(task)

            task.reset_speed()
            if task.downloadedBytes > 0:
                task.speed_tracker.add_sample(task.downloadedBytes)
            last_time = time.time()

            for idx, seg_url in enumerate(segments):
                if task.cancelled:
                    shutil.rmtree(segments_dir, ignore_errors=True)
                    task.status = DownloadStatus.CANCELLED
                    task.reset_speed()
                    self.broadcast_update(task)
                    return
                if task.paused:
                    task.status = DownloadStatus.PAUSED
                    task.reset_speed()
                    self.broadcast_update(task)
                    return

                seg_file = segments_dir / f"seg_{idx:05d}.ts"
                if idx in completed_indices and seg_file.exists() and seg_file.stat().st_size > 0:
                    continue

                seg_tmp = segments_dir / f"seg_{idx:05d}.tmp"
                max_seg_retries = 5
                seg_success = False

                for attempt in range(1, max_seg_retries + 1):
                    if task.cancelled or task.paused:
                        break
                    seg_bytes_this_attempt = 0
                    try:
                        if hasattr(client, "stream"):
                            async with client.stream("GET", seg_url) as seg_resp:
                                if seg_resp.status_code != 200:
                                    if seg_resp.status_code in (403, 404, 410):
                                        raise ConnectionError(f"HTTP {seg_resp.status_code} sur segment {idx} (lien expiré ou introuvable)")
                                    raise ConnectionError(f"HTTP {seg_resp.status_code} sur segment {idx}")

                                with open(seg_tmp, "wb") as f_seg:
                                    async for chunk_data in seg_resp.aiter_bytes(chunk_size=16384):
                                        if task.cancelled or task.paused:
                                            break
                                        f_seg.write(chunk_data)
                                        chunk_len = len(chunk_data)
                                        seg_bytes_this_attempt += chunk_len
                                        downloaded += chunk_len
                                        await self._apply_throttle(task, chunk_len)

                                        now = time.time()
                                        task.update_progress(downloaded, now)
                                        if now - last_time >= 0.5:
                                            last_time = now
                                            task.progress = min(99.0, (len(completed_indices) / total_segments) * 100.0)
                                            self.broadcast_update(task)
                        else:
                            seg_resp = await client.get(seg_url)
                            if seg_resp.status_code != 200:
                                if seg_resp.status_code in (403, 404, 410):
                                    raise ConnectionError(f"HTTP {seg_resp.status_code} sur segment {idx} (lien expiré ou introuvable)")
                                raise ConnectionError(f"HTTP {seg_resp.status_code} sur segment {idx}")
                            chunk_data = seg_resp.content
                            with open(seg_tmp, "wb") as f_seg:
                                f_seg.write(chunk_data)
                            chunk_len = len(chunk_data)
                            seg_bytes_this_attempt += chunk_len
                            downloaded += chunk_len
                            await self._apply_throttle(task, chunk_len)
                            now = time.time()
                            task.update_progress(downloaded, now)

                        if task.cancelled:
                            if seg_tmp.exists():
                                seg_tmp.unlink(missing_ok=True)
                            shutil.rmtree(segments_dir, ignore_errors=True)
                            task.status = DownloadStatus.CANCELLED
                            task.reset_speed()
                            self.broadcast_update(task)
                            return
                        if task.paused:
                            if seg_tmp.exists():
                                seg_tmp.unlink(missing_ok=True)
                            task.status = DownloadStatus.PAUSED
                            task.reset_speed()
                            self.broadcast_update(task)
                            return

                        if seg_tmp.exists() and seg_tmp.stat().st_size > 0:
                            seg_tmp.replace(seg_file)
                            completed_indices.add(idx)
                            seg_success = True
                            break
                        else:
                            raise ConnectionError(f"Segment {idx} téléchargé vide (0 octets)")

                    except Exception as seg_err:
                        if seg_bytes_this_attempt > 0:
                            downloaded -= seg_bytes_this_attempt
                            task.downloadedBytes = downloaded
                        if seg_tmp.exists():
                            seg_tmp.unlink(missing_ok=True)

                        err_str = str(seg_err).lower()
                        if "expiré" in err_str or "403" in err_str or "410" in err_str:
                            raise seg_err

                        if attempt >= max_seg_retries:
                            logger.warning("Échec définitif du segment %d/%d après %d essais pour %s: %s",
                                           idx + 1, total_segments, max_seg_retries, task.fileName, seg_err)
                            raise seg_err

                        backoff = min(1.0 * attempt, 4.0)
                        logger.warning("Micro-coupure sur segment %d/%d pour %s (%s), réessai %d/%d dans %.1fs...",
                                       idx + 1, total_segments, task.fileName, seg_err, attempt + 1, max_seg_retries, backoff)
                        await asyncio.sleep(backoff)

                if not seg_success and not (task.cancelled or task.paused):
                    raise ConnectionError(f"Impossible de télécharger le segment {idx}")

                now = time.time()
                task.update_progress(downloaded, now)
                task.progress = min(99.0, (len(completed_indices) / total_segments) * 100.0)
                if now - last_time >= 0.5:
                    last_time = now
                    self.broadcast_update(task)

        # Assemblage final sans perte des segments HLS
        logger.info("Assemblage de %d segments HLS vers %s", total_segments, task.fileName)
        temp_output = output_path.with_suffix(".tmp.mp4")
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)

        concat_file = segments_dir / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f_concat:
            for idx in range(total_segments):
                sf = segments_dir / f"seg_{idx:05d}.ts"
                f_concat.write(f"file '{sf.name}'\n")

        merged = False
        if self.is_ffmpeg_available() and task.fileName.endswith(".mp4"):
            remux_cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", "concat_list.txt",
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                str(temp_output)
            ]
            r_proc = await asyncio.create_subprocess_exec(
                *remux_cmd,
                cwd=str(segments_dir),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            r_rc = await r_proc.wait()
            if r_rc == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
                shutil.move(str(temp_output), str(output_path))
                merged = True

        if not merged:
            # Fallback concaténation binaire directe
            with open(output_path, "wb") as outfile:
                for idx in range(total_segments):
                    sf = segments_dir / f"seg_{idx:05d}.ts"
                    if sf.exists():
                        with open(sf, "rb") as infile:
                            shutil.copyfileobj(infile, outfile, length=65536)

        # Nettoyage sécurisé du dossier temporaire de segments une fois l'assemblage validé
        shutil.rmtree(segments_dir, ignore_errors=True)

        final_size = output_path.stat().st_size if output_path.exists() else downloaded
        task.downloadedBytes = final_size
        task.totalBytes = final_size
        task.progress = 100.0
        task.reset_speed()

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
            part_path = Path(task.savePath + ".part")
            if part_path.exists():
                part_path.unlink(missing_ok=True)
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

        async with self._create_async_client(headers=headers, proxy=proxy, timeout=15.0) as client:
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
                if fav:
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
        clean = name.replace("\0", "")
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean)
        clean = re.sub(r"\.{2,}", "_", clean)
        clean = re.sub(r"\s+", " ", clean).strip(" .")
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
