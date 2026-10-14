from animan.services.source_http import source_http, VerificationRequired, RateLimited, PROFILE
import asyncio
import errno
from animan.services.background import spawn
import json
import logging
import math
import os
import re
import shutil
import socket
import subprocess
from animan import media_tools, platform_events
import tempfile
import time
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from animan.config import settings
from animan.models.download_task import DownloadTask, DownloadStatus, format_bytes, ensure_utc
from animan.services.library_service import library_service
from animan.services.proxy_service import proxy_service
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.verification_service import verification_service, VerificationResult
from animan.services.extractors import extractor_registry
from animan.services.subtitle_service import normalize_subtitles, subtitle_extension, subtitle_language
from animan.services.download_resume import (RESUME_OVERLAP, ResumeMismatch, read_metadata,
                                            write_metadata, representation, response_range, prepare_hls_cache)
from animan.security import is_safe_path, is_safe_url

logger = logging.getLogger("animan.download_manager")

class SubtitleError(ValueError):
    """A known subtitle track could not be downloaded or validated."""
    def __init__(self, message: str, refresh_required: bool = False):
        super().__init__(message)
        self.refresh_required = refresh_required

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
        return source_http.async_client(headers=headers, timeout=timeout, follow_redirects=follow_redirects)

    def _trigger_process_queue(self):
        try:
            loop = asyncio.get_running_loop()
            spawn(self.process_queue(), name="process-queue")
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
            restored = [entity.to_task() for entity in unfinished]
            for task in restored:
                if task.status == DownloadStatus.VERIFICATION_REQUIRED and task.verificationUrl:
                    source_http.state(task.verificationUrl).blocked_url = task.verificationUrl
            destinations = {}
            for task in restored:
                if task.savePath:
                    destinations.setdefault(task.savePath, set()).add(task.downloadPageUrl or task.fileUrl)
            conflicts = {path for path, urls in destinations.items() if len(urls) > 1}
            for task in restored:
                if task.savePath in conflicts:
                    self._pause_destination_conflict(task)
                    self.tasks[task.id] = task
                    self.task_order.append(task.id)
                    continue
                # Vérifier si le fichier final est en réalité déjà complet et valide sur disque
                if task.savePath:
                    out_path = Path(task.savePath)
                    part_path = Path(task.savePath + ".part")
                    if out_path.exists() and out_path.stat().st_size > 1024 * 1024:
                        verif = verification_service.verify_file(str(out_path), task.animeName, task.fileName)
                        if verif.valid and not self._has_pending_subtitles(task):
                            task.status = DownloadStatus.COMPLETED
                            task.progress = 100.0
                            task.downloadedBytes = out_path.stat().st_size
                            task.totalBytes = max(task.totalBytes, out_path.stat().st_size)
                            task.verificationStatus = verif.status
                            task.videoDuration = verif.duration
                            task.error = None
                            library_service.save_task(task)
                            library_service.mark_as_downloaded(task.animeUrl or task.downloadPageUrl or "", task.animeName, task.episodeNumber, task.version)
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
            logger.info("Loaded %d unfinished task(s) from database at startup", len(self.tasks))
        except Exception as e:
            logger.error("Error loading unfinished tasks: %s", e)

    # -------------------------------------------------------------------------
    # Paramètres et Configuration
    # -------------------------------------------------------------------------

    def get_settings(self) -> Dict[str, Any]:
        return {
            "maxConcurrentDownloads": self.max_concurrent_downloads,
            "globalSpeedLimit": self.global_speed_limit,
            "plexOrganization": self.plex_organization,
            "selectedUserAgent": proxy_service.get_selected_user_agent(),
            "networkProfile": PROFILE,
            "voiranimeDefaultServer": self.voiranime_default_server,
            "ffmpegAvailable": self.is_ffmpeg_available(),
            "proxy": proxy_service.get_proxy_settings(),
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

    def _pause_destination_conflict(self, task):
        task.paused = True
        task.status = DownloadStatus.PAUSED
        task.speed = 0
        task.error = "Plusieurs liens partagent ce fichier. Relancez la version souhaitée depuis la fiche animé."
        library_service.save_task(task)
        self.broadcast_update(task)

    def _has_destination_conflict(self, task):
        return bool(task.savePath and any(
            other.id != task.id and other.savePath == task.savePath
            and other.status != DownloadStatus.CANCELLED
            and (other.downloadPageUrl or other.fileUrl) != (task.downloadPageUrl or task.fileUrl)
            for other in self.tasks.values()))

    def _active_episode_task(self, url: str, source: str, version: str):
        active = {DownloadStatus.PENDING, DownloadStatus.DOWNLOADING, DownloadStatus.SCHEDULED,
                  DownloadStatus.PAUSED, DownloadStatus.RETRYING, DownloadStatus.MUXING}
        return next((task for task in self.tasks.values()
                     if task.status in active and task.downloadPageUrl == url
                     and task.source == source and task.version == version), None)

    def _version_suffix(self, version: str) -> str:
        clean = self.sanitize_file_name(version) if version else ""
        return f" [{clean}]" if clean else ""

    def _versioned_filename(self, name: str, version: str) -> str:
        suffix = self._version_suffix(version)
        path = Path(name)
        if suffix and not path.stem.endswith(suffix):
            return f"{path.stem}{suffix}{path.suffix or '.mp4'}"
        return name

    def check_existing_file(self, anime_name: str, file_name: str, episode_number: int, version: str = "") -> Optional[Path]:
        if not anime_name or not file_name:
            return None

        file_name = self._versioned_filename(file_name, version)
        clean_anime = self.sanitize_file_name(anime_name)
        if self.plex_organization:
            anime_dir = Path(self.download_dir) / clean_anime / "Season 01"
            ext = Path(file_name).suffix or ".mp4"
            final_name = f"{clean_anime} - S01E{episode_number:02d}{self._version_suffix(version)}{ext}"
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
        return extractor_registry.get_headers_for_url(url, server_type)

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
                try:
                    resp = await client.head(url)
                    if resp.status_code == 200:
                        cl = resp.headers.get("Content-Length")
                        if cl and cl.isdigit() and int(cl) > 1024:
                            return int(cl)
                except VerificationRequired:
                    raise
                except Exception:
                    pass

                # Essai Range: bytes=0-0 pour les serveurs rejetant HEAD (ex: Sibnet)
                try:
                    range_resp = await client.get(url, headers={"Range": "bytes=0-0"})
                    cr = range_resp.headers.get("Content-Range")
                    if cr and "/" in cr:
                        total_str = cr.split("/")[-1].strip()
                        if total_str.isdigit():
                            return int(total_str)
                    cl2 = range_resp.headers.get("Content-Length")
                    if cl2 and cl2.isdigit() and int(cl2) > 0 and range_resp.status_code == 200:
                        return int(cl2)
                except VerificationRequired:
                    raise
                except Exception:
                    pass
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Error in get_remote_file_size for %s: %s", url, e)
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
                    except VerificationRequired:
                        raise
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

        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Error in estimate_hls_size for %s: %s", m3u8_url, e)

        return -1

    async def resolve_imported_video_stream(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Résout l'URL directe (m3u8 ou mp4) pour les sources importées et hébergeurs vidéo
        en déléguant au hub modulaire d'extracteurs vidéo.
        """
        if not url:
            return None

        clean_url = url.split("#")[0].strip()

        # 1. Si l'URL est déjà un flux vidéo direct (mp4, m3u8, webm, mkv)
        if re.search(r"\.(mp4|m3u8|webm|mkv)(\?.*)?$", clean_url, re.IGNORECASE):
            is_hls = ".m3u8" in clean_url.lower()
            headers = self.get_headers_for_url(clean_url, "imported")
            if referer:
                headers["Referer"] = referer
            sz = (
                await self.estimate_hls_size(clean_url, headers=headers)
                if is_hls
                else await self.get_remote_file_size(clean_url, headers=headers, server_type="imported")
            )
            return {
                "videoUrl": clean_url,
                "serverType": "direct",
                "selectedQuality": preferred_quality or "HD",
                "videoQualities": json.dumps({"HD": clean_url}),
                "size": sz,
                "headers": headers,
            }

        # 2. Délégation aux extracteurs dédiés
        res = await extractor_registry.extract(clean_url, referer=referer, preferred_quality=preferred_quality)
        if res and res.video_url:
            info = res.to_download_info()
            if info.get("size", -1) <= 0:
                is_hls = ".m3u8" in info["videoUrl"].lower()
                headers = info.get("headers") or self.get_headers_for_url(info["videoUrl"], info["serverType"])
                sz = (
                    await self.estimate_hls_size(info["videoUrl"], headers=headers, server_type=info["serverType"])
                    if is_hls
                    else await self.get_remote_file_size(info["videoUrl"], headers=headers, server_type=info["serverType"])
                )
                info["size"] = sz
            return info

        return None

    async def get_or_resolve_episode_info(
        self,
        download_page_url: str,
        preferred_server: Optional[str] = None,
        preferred_quality: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Optional[ResolvedVideoInfo]:
        if not download_page_url:
            return None
        eff_server_key = preferred_server or self.voiranime_default_server
        cache_key = f"{download_page_url}::{source or ''}::{eff_server_key}::{preferred_quality or ''}"
        if cache_key in self.resolved_info_cache:
            return self.resolved_info_cache[cache_key]

        async with self._info_semaphore:
            if cache_key in self.resolved_info_cache:
                return self.resolved_info_cache[cache_key]

            try:
                info = ResolvedVideoInfo()
                parsed_u = urlparse(download_page_url)
                u_host = (parsed_u.hostname or "").lower()
                clean_page_url = download_page_url.split("#")[0].strip()
                is_known_embed = extractor_registry.is_known_embed(clean_page_url)
                is_imported = bool(source and source not in ("french-manga", "voir-anime", "animepahe")) or is_known_embed

                matched_container = None
                try:
                    from animan.services.extension_service import extension_service
                    if source and source not in ("french-manga", "voir-anime", "animepahe"):
                        matched_container = extension_service.get_container_source_by_id(source)
                    if not matched_container and u_host:
                        for cs in extension_service.get_enabled_container_sources():
                            if cs.base_url and u_host in cs.base_url.lower():
                                matched_container = cs
                                break
                except VerificationRequired:
                    raise
                except Exception:
                    pass

                if matched_container:
                    is_imported = True

                is_voir_anime = not is_imported and (source == "voir-anime" or "voir-anime" in download_page_url)
                is_animepahe = not is_imported and (source == "animepahe" or any(k in download_page_url for k in ["animepahe", "kwik.", "pahe."]))

                if is_imported:
                    target_url = download_page_url
                    avail_servers = []
                    qualities = {}
                    video_sources = []
                    if matched_container and not is_known_embed:
                        try:
                            video_sources = await matched_container.get_episode_sources(download_page_url)
                        except VerificationRequired:
                            raise
                        except Exception as e:
                            logger.debug("[download_manager] Error getting episode sources: %s", e)
                            video_sources = []

                        if video_sources:
                            for vs in video_sources:
                                s_name = vs.get("server") or vs.get("name")
                                if s_name and s_name not in avail_servers:
                                    avail_servers.append(s_name)
                                qualities[s_name or "Serveur"] = vs.get("url", "")

                        target = None
                        if preferred_server and preferred_server != "auto":
                            for s in video_sources:
                                s_srv = s.get("server") or s.get("name") or ""
                                if preferred_server.lower() in s_srv.lower():
                                    target = s
                                    break
                        if not target and preferred_quality and preferred_quality != "auto":
                            for s in video_sources:
                                q_name = s.get("quality") or s.get("server") or ""
                                if preferred_quality.lower() in q_name.lower():
                                    target = s
                                    break
                        if not target and video_sources:
                            target = video_sources[0]
                        if target and target.get("url"):
                            target_url = target.get("url", "")

                    # Résolution du flux direct via resolve_imported_video_stream avec repli
                    resolved = None
                    candidate_urls = []
                    if target and target.get("url"):
                        candidate_urls.append(target.get("url"))
                    if video_sources:
                        for s in video_sources:
                            u_ = s.get("url")
                            if u_ and u_ not in candidate_urls:
                                candidate_urls.append(u_)

                    for cand_u in (candidate_urls or [target_url]):
                        try:
                            cand_res = await self.resolve_imported_video_stream(
                                cand_u, preferred_quality=preferred_quality
                            )
                            if cand_res and cand_res.get("videoUrl"):
                                resolved = cand_res
                                break
                        except VerificationRequired:
                            raise
                        except Exception:
                            pass

                    if resolved and resolved.get("videoUrl"):
                        dl_info = resolved
                    else:
                        raise ValueError("Aucun flux vidéo résolu pour cette extension.")
                    info.server_type = dl_info.get("serverType", "imported")
                    info.available_servers = avail_servers if avail_servers else [info.server_type]
                    info.video_qualities_json = dl_info.get("videoQualities", "{}")
                    info.selected_server = info.server_type
                    info.selected_quality = dl_info.get("selectedQuality", "HD")
                    if dl_info.get("size"):
                        info.size = dl_info["size"]
                elif is_voir_anime:
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
                        except VerificationRequired:
                            raise
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
                    dl_info = await asyncio.to_thread(scraping_service.extract_download_info, download_page_url)
                    info.server_type = "vidzy"

                info.direct_url = dl_info.get("videoUrl", "")
                info.subtitle_url = dl_info.get("subtitleUrl", "")
                info.subtitles_json = json.dumps(normalize_subtitles(dl_info.get("subtitles", []), download_page_url))

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
            except VerificationRequired:
                raise
            except Exception as e:
                logger.error("Error in get_or_resolve_episode_info: %s", e)
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
        source: str = "french-manga",
        version: str = "",
        anime_url: str = "",
    ) -> DownloadTask:
        existing_task = self._active_episode_task(download_page_url, source, version)
        if existing_task:
            return existing_task
        file_name = self._versioned_filename(file_name, version)
        cache_key = f"{download_page_url}::{source}::{selected_server or ''}::{selected_quality or ''}"
        cached = self.resolved_info_cache.get(cache_key)
        if not cached and not (selected_server or selected_quality):
            cached = self.resolved_info_cache.get(download_page_url)
        initial_total_bytes = cached.size if cached and cached.size > 0 else 0
        resolved_subs = cached.subtitles_json if cached else "[]"

        scheduled_start_time = ensure_utc(scheduled_start_time)
        now = datetime.now(timezone.utc)
        is_scheduled = scheduled_start_time is not None and scheduled_start_time > now
        status = DownloadStatus.SCHEDULED if is_scheduled else DownloadStatus.PENDING

        file_name = self._versioned_filename(file_name, version)
        clean_anime = self.sanitize_file_name(anime_name)
        if self.plex_organization:
            anime_dir = Path(self.download_dir) / clean_anime / "Season 01"
            ext = Path(file_name).suffix or ".mp4"
            final_file_name = f"{clean_anime} - S01E{episode_number:02d}{self._version_suffix(version)}{ext}"
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
            source=source,
            version=version,
            animeUrl=anime_url,
        )

        self.tasks[task.id] = task
        self.task_order.append(task.id)
        library_service.save_task(task)

        if task.status == DownloadStatus.PENDING:
            self._trigger_process_queue()

        self.broadcast_update(task)
        return task

    def start_batch_download(self, anime_name: str, episodes: List[Dict[str, Any]], source: str = "french-manga") -> List[DownloadTask]:
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
            ep_source = ep.get("source") or source
            version = ep.get("version") or ""
            if self._active_episode_task(url, ep_source, version):
                continue
            name = self._versioned_filename(ep.get("fileName", f"{anime_name} - Episode {ep_num}.mp4"), version)
            sub_url = ep.get("subtitleUrl")
            dl_subs = str(ep.get("downloadSubtitles", "false")).lower() == "true"
            sel_server = ep.get("selectedServer")
            sel_quality = ep.get("selectedQuality")

            # Check duplicate
            existing = self.check_existing_file(anime_name, name, ep_num, version)
            if existing and existing.exists() and existing.stat().st_size > 1024 * 1024:
                verif = verification_service.verify_file(str(existing), anime_name, name)
                if verif.valid:
                    logger.info("Batch: %s Ep%d already exists and is valid (%s), skipping",
                                anime_name, ep_num, format_bytes(existing.stat().st_size))
                    library_service.mark_as_downloaded(ep.get("animeUrl") or url, anime_name, ep_num, version)
                    continue

            if existing:
                cache_key = f"{url}::{ep_source}::{sel_server or ''}::{sel_quality or ''}"
                cached = self.resolved_info_cache.get(cache_key)
                if not cached and not (sel_server or sel_quality):
                    cached = self.resolved_info_cache.get(url)
                if cached and cached.size > 0 and existing.stat().st_size == cached.size:
                    logger.info("Batch: %s Ep%d already exists with the same size, skipping", anime_name, ep_num)
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

            cache_key = f"{url}::{ep_source}::{sel_server or ''}::{sel_quality or ''}"
            cached = self.resolved_info_cache.get(cache_key)
            if not cached and not (sel_server or sel_quality):
                cached = self.resolved_info_cache.get(url)
            initial_total_bytes = cached.size if cached and cached.size > 0 else 0
            resolved_subs = cached.subtitles_json if cached else "[]"

            sched_time = ensure_utc(sched_time)
            now = datetime.now(timezone.utc)
            is_scheduled = sched_time is not None and sched_time > now
            status = DownloadStatus.SCHEDULED if is_scheduled else DownloadStatus.PENDING

            if self.plex_organization:
                ext = Path(name).suffix or ".mp4"
                final_file_name = f"{clean_anime} - S01E{ep_num:02d}{self._version_suffix(version)}{ext}"
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
                source=ep_source,
                version=version,
                animeUrl=ep.get("animeUrl") or "",
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

    def resume_verified_domain(self, domain: str) -> int:
        ids = [task.id for task in self.tasks.values()
               if task.status == DownloadStatus.VERIFICATION_REQUIRED
               and urlparse(task.verificationUrl or "").hostname == domain]
        return sum(self.resume_download(task_id) for task_id in ids)

    def resume_download(self, task_id: str) -> bool:
        t = self.tasks.get(task_id)
        if not t:
            entity = library_service.get_task_entity(task_id)
            if entity:
                t = entity.to_task()
                self.tasks[t.id] = t
                if t.id not in self.task_order:
                    self.task_order.append(t.id)

        if t and t.status == DownloadStatus.VERIFICATION_REQUIRED:
            if not t.verificationUrl or source_http.state(t.verificationUrl).blocked_url:
                return False
            t.verificationUrl = None
            t.status = DownloadStatus.PAUSED
        if t and self._has_destination_conflict(t):
            self._pause_destination_conflict(t)
            return False
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
                    if verif.valid and not self._has_pending_subtitles(t):
                        t.status = DownloadStatus.COMPLETED
                        t.progress = 100.0
                        t.downloadedBytes = out_path.stat().st_size
                        t.totalBytes = max(t.totalBytes, out_path.stat().st_size)
                        t.verificationStatus = verif.status
                        t.videoDuration = verif.duration
                        self.broadcast_update(t)
                        library_service.save_task(t)
                        library_service.mark_as_downloaded(t.animeUrl or t.downloadPageUrl or "", t.animeName, t.episodeNumber, t.version)
                        return True

                if part_path.exists() and part_path.stat().st_size > 0:
                    if t.totalBytes > 0 and part_path.stat().st_size > t.totalBytes:
                        logger.warning(".part file (%d bytes) larger than totalBytes (%d) for %s, deleting",
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
                logger.info("Resume detected for %s: %s already downloaded",
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
            DownloadStatus.VERIFICATION_REQUIRED,
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
            DownloadStatus.VERIFICATION_REQUIRED,
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
        logger.info("Global cancellation: %d download(s) cancelled", count)
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
                Path(t.savePath + ".part.resume.json").unlink(missing_ok=True)
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
            logger.warning("Error reloading DB tasks for resume: %s", e)

        for t in list(self.tasks.values()):
            if self._has_destination_conflict(t):
                self._pause_destination_conflict(t)
                continue
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
                        if verif.valid and not self._has_pending_subtitles(t):
                            t.status = DownloadStatus.COMPLETED
                            t.progress = 100.0
                            t.downloadedBytes = out_path.stat().st_size
                            t.totalBytes = max(t.totalBytes, out_path.stat().st_size)
                            t.verificationStatus = verif.status
                            t.videoDuration = verif.duration
                            self.broadcast_update(t)
                            library_service.save_task(t)
                            library_service.mark_as_downloaded(t.animeUrl or t.downloadPageUrl or "", t.animeName, t.episodeNumber, t.version)
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

    def _apply_verification(self, task: DownloadTask, verif: VerificationResult) -> None:
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
        self._apply_verification(task, verif)
        return verif

    async def verify_task_async(self, task_id: str) -> Optional[VerificationResult]:
        """Variante non bloquante : ffprobe/ffmpeg tournent dans un thread."""
        task = self.get_task(task_id)
        if not task:
            return None

        verif = await asyncio.to_thread(
            verification_service.verify_file,
            file_path_str=task.savePath,
            anime_name=task.animeName,
            file_name=task.fileName,
            expected_size=task.totalBytes,
        )
        # Mutations d'état et broadcast SSE (asyncio.Queue) : uniquement dans la boucle
        self._apply_verification(task, verif)
        return verif

    def _collect_completed_tasks(self) -> Dict[str, DownloadTask]:
        completed_tasks: Dict[str, DownloadTask] = {}

        # 1. Tâches en mémoire
        for t in self.tasks.values():
            if t.status in [DownloadStatus.COMPLETED, DownloadStatus.FAILED]:
                completed_tasks[t.id] = t

        # 2. Tâches dans l'historique
        for entity in library_service.get_history():
            if entity.id not in completed_tasks and entity.status in [DownloadStatus.COMPLETED.value, DownloadStatus.FAILED.value]:
                completed_tasks[entity.id] = entity.to_task()
        return completed_tasks

    @staticmethod
    def _summarize_verifications(pairs: List[Tuple[DownloadTask, VerificationResult]]) -> Dict[str, Any]:
        valid_count = missing_count = empty_count = incomplete_count = corrupted_count = 0
        results_list = []

        for task, verif in pairs:
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
            "total": len(pairs),
            "valid": valid_count,
            "missing": missing_count,
            "empty": empty_count,
            "incomplete": incomplete_count,
            "corrupted": corrupted_count,
            "results": results_list,
        }

    def verify_all_completed(self) -> Dict[str, Any]:
        """Vérifie l'intégrité de l'ensemble des téléchargements terminés."""
        pairs: List[Tuple[DownloadTask, VerificationResult]] = []
        for task in self._collect_completed_tasks().values():
            verif = verification_service.verify_file(
                file_path_str=task.savePath,
                anime_name=task.animeName,
                file_name=task.fileName,
                expected_size=task.totalBytes
            )
            self._apply_verification(task, verif)
            pairs.append((task, verif))
        return self._summarize_verifications(pairs)

    async def verify_all_completed_async(self) -> Dict[str, Any]:
        """Variante non bloquante de verify_all_completed (ffprobe/ffmpeg dans des threads)."""
        tasks = await asyncio.to_thread(self._collect_completed_tasks)
        pairs: List[Tuple[DownloadTask, VerificationResult]] = []
        for task in tasks.values():
            verif = await asyncio.to_thread(
                verification_service.verify_file,
                file_path_str=task.savePath,
                anime_name=task.animeName,
                file_name=task.fileName,
                expected_size=task.totalBytes,
            )
            self._apply_verification(task, verif)
            pairs.append((task, verif))
        return self._summarize_verifications(pairs)

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
                logger.warning("File marked as %s for %s, mandatory purge for fresh start",
                               task.verificationStatus, task.fileName)
                has_healthy_part = False
            else:
                target = part_p if part_p.exists() else (out_p if out_p.exists() else None)
                if target and target.stat().st_size > 1024:
                    if task.totalBytes > 0 and target.stat().st_size > task.totalBytes:
                        logger.warning("Partial file %s (%s) larger than totalBytes (%s), purge required",
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
            logger.info("Healthy partial file detected for %s, switching to resume_download", task.fileName)
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
                Path(task.savePath + ".part.resume.json").unlink(missing_ok=True)
            except Exception as e:
                logger.warning("Unable to delete corrupted file %s: %s", task.savePath, e)

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
        logger.info("Task restarted for full redownload: %s", task.fileName)
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
            for task in pending:
                if slots <= 0:
                    break
                if self._has_destination_conflict(task):
                    self._pause_destination_conflict(task)
                    continue
                slots -= 1
                task.status = DownloadStatus.DOWNLOADING
                task.phase = "resolving"
                self.broadcast_update(task)
                library_service.save_task(task)
                spawn(self._execute_download(task), name=f"download-{task.id}")

    # -------------------------------------------------------------------------
    # Exécution du téléchargement
    # -------------------------------------------------------------------------

    async def _execute_download(self, task: DownloadTask):
        try:
            max_retries = 5  # Tolérance robuste face aux coupures réseau et expirations CDN
            task.retryCount = 0
            need_resolve = True
            skip_local = False

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

                local_finalization = False
                try:
                    # Retry finalization locally before asking a possibly expired player
                    # for another video URL. The file is still verified by the downloader.
                    await asyncio.to_thread(self._recover_muxed_file, task)
                    if not skip_local and task.savePath and Path(task.savePath).is_file():
                        local = await asyncio.to_thread(verification_service.verify_file, task.savePath,
                                                       expected_size=task.totalBytes or None)
                        if local.valid:
                            local_finalization = True
                            await self._download_single_file(task, task.directDownloadUrl or task.fileUrl or "")
                            return
                    task.phase = "resolving"
                    self.broadcast_update(task)
                    direct_url = task.fileUrl
                    clean_direct = (direct_url or "").split("#")[0].strip()
                    parsed_u = urlparse(clean_direct)
                    u_host = (parsed_u.hostname or "").lower()
                    is_known_embed = extractor_registry.is_known_embed(clean_direct)
                    is_imported = (
                        (task.source and (task.source not in ("french-manga", "voir-anime", "animepahe"))) or
                        is_known_embed
                    )
                    is_voir_anime = not is_imported and (("voir-anime" in (direct_url or "").lower()) or ("voiranime" in (direct_url or "").lower()) or task.source == "voir-anime")
                    is_animepahe = not is_imported and (any(k in (direct_url or "").lower() for k in ["animepahe", "kwik.", "pahe."]) or task.source == "animepahe")
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
                        logger.info("Reusing cached direct URL for %s", task.fileName)
                    elif is_imported:
                        matched_container = None
                        try:
                            from animan.services.extension_service import extension_service
                            if task.source and task.source not in ("french-manga", "voir-anime", "animepahe"):
                                matched_container = extension_service.get_container_source_by_id(task.source)
                            if not matched_container and u_host:
                                for cs in extension_service.get_enabled_container_sources():
                                    if cs.base_url and u_host in cs.base_url.lower():
                                        matched_container = cs
                                        break
                        except VerificationRequired:
                            raise
                        except Exception:
                            pass

                        target_url = direct_url
                        video_sources = []
                        target = None
                        if matched_container and not is_known_embed:
                            video_sources = await matched_container.get_episode_sources(direct_url)
                            target = None
                            if task.selectedServer and task.selectedServer != "auto":
                                for s in video_sources:
                                    s_srv = s.get("server") or s.get("name") or ""
                                    if task.selectedServer.lower() in s_srv.lower():
                                        target = s
                                        break
                            if not target and task.selectedQuality and task.selectedQuality != "auto":
                                for s in video_sources:
                                    q_name = s.get("quality") or s.get("server") or ""
                                    if task.selectedQuality.lower() in q_name.lower():
                                        target = s
                                        break
                            if not target and video_sources:
                                target = video_sources[0]
                            if target and target.get("url"):
                                target_url = target.get("url", "")

                        resolved = None
                        candidate_urls = []
                        if target and target.get("url"):
                            candidate_urls.append(target.get("url"))
                        if video_sources:
                            for vs in video_sources:
                                v_u = vs.get("url")
                                if v_u and v_u not in candidate_urls:
                                    candidate_urls.append(v_u)

                        for cand_u in (candidate_urls or [target_url]):
                            try:
                                cand_res = await self.resolve_imported_video_stream(
                                    cand_u, preferred_quality=task.selectedQuality
                                )
                                if cand_res and cand_res.get("videoUrl"):
                                    resolved = cand_res
                                    break
                            except VerificationRequired:
                                raise
                            except Exception:
                                pass

                        if not resolved or not resolved.get("videoUrl"):
                            clean_t = target_url.split("#")[0].strip()
                            if re.search(r"\.(mp4|m3u8|webm|mkv)(\?.*)?$", clean_t, re.IGNORECASE):
                                resolved = {
                                    "videoUrl": clean_t,
                                    "serverType": "direct",
                                    "selectedQuality": task.selectedQuality or "HD",
                                }
                            else:
                                raise ValueError(f"Impossible de résoudre le flux vidéo de la source importée pour {task.fileName}")

                        direct_url = resolved["videoUrl"]
                        server_type = resolved.get("serverType", "imported")
                        task.selectedServer = server_type
                        task.directDownloadUrl = direct_url
                        self._update_resolved_subtitles(task, resolved.get("subtitles", []), target_url)
                        task.subtitleUrl = resolved.get("subtitleUrl") or task.subtitleUrl
                        if resolved.get("size") and task.totalBytes <= 0:
                            task.totalBytes = resolved["size"]
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
                            logger.info("[download_manager] Falling back to alternative servers for %s after confirmed failures on %s", task.fileName, pref_srv)
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
                        if (skip_local or not task.subtitleUrl) and info.get("subtitleUrl"):
                            task.subtitleUrl = info["subtitleUrl"]
                        self._update_resolved_subtitles(task, info.get("subtitles", []), task.fileUrl)
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
                        if (skip_local or not task.subtitleUrl) and info.get("subtitleUrl"):
                            task.subtitleUrl = info["subtitleUrl"]
                        if skip_local or not task.subtitlesJson or task.subtitlesJson == "[]":
                            self._update_resolved_subtitles(task, info.get("subtitles", []), task.fileUrl)
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

                except VerificationRequired as exc:
                    task.status = DownloadStatus.VERIFICATION_REQUIRED
                    task.verificationUrl = exc.url
                    task.error = str(exc)
                    task.speed = 0
                    self.broadcast_update(task)
                    library_service.save_task(task)
                    return
                except Exception as e:
                    if isinstance(e, (httpx.RequestError, httpx.HTTPStatusError)) and not isinstance(e, RateLimited):
                        request = getattr(e, "request", None)
                        if request is not None:
                            task.verificationUrl = str(request.url)
                    if isinstance(e, RateLimited):
                        # A large Retry-After should not consume all download attempts.
                        task.status = DownloadStatus.PAUSED
                        task.error = f"Limitation de débit ; réessayez après {int(e.retry_after)} secondes"
                        task.speed = 0
                        self.broadcast_update(task)
                        library_service.save_task(task)
                        return
                    if isinstance(e, SubtitleError):
                        if local_finalization and e.refresh_required:
                            skip_local = True
                            need_resolve = True
                            continue
                        task.status = DownloadStatus.FAILED
                        task.error = str(e)
                        self.broadcast_update(task)
                        library_service.save_task(task)
                        return
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
                        logger.info("Progress of %s bytes for %s despite network interruption, keeping host %s and resetting server errors",
                                    format_bytes(bytes_gained), task.fileName, task.selectedServer)
                        task.retryCount = max(0, task.retryCount - 1)
                        task.consecutiveServerErrors = 0

                    err_msg = str(e).lower()

                    # 1. Tester d'abord si la machine locale est déconnectée d'Internet
                    client_online = await self.is_client_online()
                    if not client_online:
                        task.clientOffline = True
                        logger.warning(
                            "[download_manager] Local Internet disconnection detected for %s (error: %s). "
                            "Retaining host %s and partial data. Waiting for network recovery...",
                            task.fileName, err_msg, task.selectedServer
                        )
                        task.status = DownloadStatus.RETRYING
                        task.error = "Local Internet connection interrupted. Waiting for network recovery..."
                        task.speed = 0
                        self.broadcast_update(task)
                        library_service.save_task(task)

                        # Attente active du retour de la connexion sans consommer les retries serveur ni changer d'hôte
                        while not task.cancelled and not task.paused:
                            await asyncio.sleep(5.0)
                            if await self.is_client_online():
                                logger.info(
                                    "[download_manager] Internet connection restored for %s! Resuming download on host %s.",
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
                                logger.info("Connection failure or expired link without progress (%s) for %s, consecutive server failures: %d",
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
                            logger.warning("Transient DNS failure (%s) for %s, waiting 5s", err_msg, task.fileName)
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
        task.phase = "video"
        self.broadcast_update(task)
        output_path = Path(task.savePath)
        part_path = Path(task.savePath + ".part")
        metadata_path = Path(task.savePath + ".part.resume.json")

        # 1. Gestion propre du fichier existant et reprise
        existing_len = 0
        if output_path.exists():
            if output_path.stat().st_size < 1024 * 1024:
                try:
                    with open(output_path, "rb") as f_chk:
                        h = f_chk.read(100).lower()
                        if b"<html" in h or b"<!doctype" in h:
                            logger.warning("Corrupted final file (HTML) detected and deleted for %s", task.fileName)
                            output_path.unlink(missing_ok=True)
                except VerificationRequired:
                    raise
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
                    logger.info("Final file already exists and is valid for %s (%s)",
                                task.fileName, format_bytes(output_path.stat().st_size))
                    part_path.unlink(missing_ok=True)
                    if task.downloadSubtitles:
                        await self._download_subtitles(task)
                        await self._finalize_task(task)
                        return
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
                        task.animeUrl or task.downloadPageUrl or "",
                        task.animeName,
                        task.episodeNumber,
                        task.version
                    )
                    return
                else:
                    logger.warning("Existing final file invalid/corrupted for %s (%s), deleting: %s",
                                   task.fileName, format_bytes(output_path.stat().st_size), verif.error)
                    output_path.unlink(missing_ok=True)

        if not direct_url:
            raise ValueError("URL directe introuvable")

        if part_path.exists():
            part_size = part_path.stat().st_size
            if part_size < 1024 * 1024:
                try:
                    with open(part_path, "rb") as f_chk:
                        h = f_chk.read(100).lower()
                        if b"<html" in h or b"<!doctype" in h:
                            logger.warning("Corrupted .part file (HTML) detected and deleted for %s", task.fileName)
                            part_path.unlink(missing_ok=True)
                except VerificationRequired:
                    raise
                except Exception:
                    pass
            elif task.totalBytes and task.totalBytes > 0 and part_size > task.totalBytes:
                logger.warning(".part file (%s) exceeds expected size (%s) for %s, deleting",
                               format_bytes(part_size), format_bytes(task.totalBytes), task.fileName)
                part_path.unlink(missing_ok=True)

            if part_path.exists():
                existing_len = part_path.stat().st_size

        headers = self.get_headers_for_url(direct_url, getattr(task, "selectedServer", None))
        proxy = proxy_service.get_random_proxy()

        timeout = httpx.Timeout(connect=20.0, read=60.0, write=30.0, pool=None)
        async with self._create_async_client(headers=headers, proxy=proxy, timeout=timeout) as client:
            req_headers = dict(headers)
            req_headers["Accept-Encoding"] = "identity"
            is_resume = existing_len > 0
            previous = read_metadata(metadata_path) if is_resume else {}
            request_start = max(0, existing_len - RESUME_OVERLAP) if is_resume else 0
            if is_resume:
                req_headers["Range"] = f"bytes={request_start}-"
                if previous.get("validator"):
                    req_headers["If-Range"] = previous["validator"]
                logger.info("Resume attempt for %s from %s", task.fileName, format_bytes(existing_len))

            while True:
                async with client.stream("GET", direct_url, headers=req_headers) as stream_resp:
                    # Gestion du code 416 Range Not Satisfiable
                    if stream_resp.status_code == 416:
                        logger.warning("HTTP 416 (Range Not Satisfiable) for %s with existing_len=%s",
                                       task.fileName, format_bytes(existing_len))
                        unsatisfied = re.fullmatch(r"bytes\s+\*/(\d+)",
                                                   stream_resp.headers.get("Content-Range", ""), re.IGNORECASE)
                        if part_path.exists() and unsatisfied and int(unsatisfied[1]) == existing_len:
                            verif_part = await asyncio.to_thread(
                                verification_service.verify_file,
                                file_path_str=str(part_path),
                                anime_name=task.animeName,
                                file_name=task.fileName,
                                expected_size=existing_len,
                            )
                            if verif_part.valid:
                                logger.info(".part file is actually complete and valid for %s, finalizing", task.fileName)
                                if output_path.exists():
                                    output_path.unlink(missing_ok=True)
                                shutil.move(str(part_path), str(output_path))
                                metadata_path.unlink(missing_ok=True)
                                await self._finalize_task(task)
                                return
                            else:
                                logger.warning("Invalid/corrupted .part file (%s), deleting for clean resume", verif_part.error)
                                part_path.unlink(missing_ok=True)

                        existing_len = 0
                        is_resume = False
                        task.downloadedBytes = 0
                        request_start = 0
                        had_range = "Range" in req_headers
                        req_headers.pop("Range", None)
                        req_headers.pop("If-Range", None)
                        metadata_path.unlink(missing_ok=True)
                        if had_range:
                            continue
                        raise ConnectionError("HTTP 416 (Range Not Satisfiable): Plage invalide, re-résolution requise")

                    if stream_resp.status_code not in [200, 206]:
                        raise ConnectionError(f"HTTP {stream_resp.status_code}")

                    # Contrôle strict du type de contenu (rejeter formellement le HTML)
                    content_type = stream_resp.headers.get("Content-Type", "").lower()
                    if "text/html" in content_type or "text/plain" in content_type or "application/json" in content_type:
                        raise ValueError(f"Réponse HTTP invalide : type '{content_type}' reçu au lieu d'un flux vidéo binaire")

                    # Le serveur ne supporte pas Range — on recommence depuis 0
                    if stream_resp.status_code == 200 and is_resume:
                        logger.warning("Server does not support resume for %s, downloading from beginning", task.fileName)
                        existing_len = 0
                        is_resume = False
                        request_start = 0

                    # Extraction et validation de la taille via Content-Range ou Content-Length
                    total_bytes = 0
                    response_length = None
                    if stream_resp.status_code == 206:
                        total_bytes, response_length = response_range(stream_resp.headers, request_start)
                    else:
                        cl = stream_resp.headers.get("Content-Length")
                        if cl and cl.isdigit():
                            total_bytes = response_length = int(cl)

                    current = representation(stream_resp.headers, total_bytes)
                    if is_resume and ((previous.get("validator") and current["validator"]
                                       and previous["validator"] != current["validator"])
                                      or (previous.get("total") and total_bytes
                                          and previous["total"] != total_bytes)):
                        # Keep the old partial intact until a full response is accepted.
                        existing_len = request_start = 0
                        is_resume = False
                        req_headers.pop("Range", None)
                        req_headers.pop("If-Range", None)
                        continue

                    if total_bytes > 0:
                        task.totalBytes = total_bytes
                        self.broadcast_update(task)

                    # Si le .part dépasse la taille totale, purge et reprise depuis 0
                    if total_bytes > 0 and existing_len > total_bytes:
                        logger.warning(".part file (%s) larger than total_bytes (%s) for %s, resetting",
                                       format_bytes(existing_len), format_bytes(total_bytes), task.fileName)
                        part_path.unlink(missing_ok=True)
                        existing_len = 0
                        is_resume = False
                        req_headers.pop("Range", None)
                        req_headers.pop("If-Range", None)
                        request_start = 0
                        continue

                    accept_ranges = "bytes" in stream_resp.headers.get("Accept-Ranges", "").lower() or stream_resp.status_code == 206
                    task.supportsResume = accept_ranges

                    # Vérifier si le .part est déjà complet
                    if total_bytes > 0 and existing_len >= total_bytes:
                        logger.info(".part file already complete for %s, verifying", task.fileName)
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
                                metadata_path.unlink(missing_ok=True)
                                await self._finalize_task(task)
                                return
                            else:
                                logger.warning(".part file complete but corrupted for %s, resetting", task.fileName)
                                part_path.unlink(missing_ok=True)
                                existing_len = 0
                                is_resume = False
                                req_headers.pop("Range", None)
                                req_headers.pop("If-Range", None)
                                request_start = 0
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
                    overlap = b""
                    if is_resume:
                        with open(part_path, "rb") as existing_file:
                            existing_file.seek(request_start)
                            overlap = existing_file.read(existing_len - request_start)
                    overlap_position = received = 0
                    metadata_written = False

                    if task.status != DownloadStatus.DOWNLOADING:
                        task.status = DownloadStatus.DOWNLOADING
                        task.error = None
                        self.broadcast_update(task)

                    try:
                        with open(part_path, mode) as f:
                            async for chunk in stream_resp.aiter_bytes(chunk_size=65536):
                                received += len(chunk)
                                if response_length is not None and received > response_length:
                                    raise ConnectionError("Media response exceeds its declared byte range")
                                if overlap_position < len(overlap):
                                    count = min(len(chunk), len(overlap) - overlap_position)
                                    if chunk[:count] != overlap[overlap_position:overlap_position + count]:
                                        raise ResumeMismatch("Media identity changed during resume")
                                    overlap_position += count
                                    chunk = chunk[count:]
                                    if not chunk:
                                        continue
                                if not metadata_written:
                                    write_metadata(metadata_path, current)
                                    metadata_written = True
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
                                    logger.info("Cancelled %s — .part file kept (%s)",
                                                task.fileName, format_bytes(downloaded))
                                    return
                                if task.paused:
                                    task.status = DownloadStatus.PAUSED
                                    task.reset_speed()
                                    task.downloadedBytes = downloaded
                                    self.broadcast_update(task)
                                    library_service.save_task(task)
                                    logger.info("Paused %s — progress saved (%s)",
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
                    except ResumeMismatch:
                        logger.warning("Different media bytes after reconnect for %s; restarting safely", task.fileName)
                        existing_len = request_start = 0
                        is_resume = False
                        req_headers.pop("Range", None)
                        req_headers.pop("If-Range", None)
                        continue

                    if overlap_position < len(overlap) or (response_length is not None and received != response_length):
                        raise ConnectionError("Incomplete media response during resume")

                    if total_bytes > 0 and downloaded < total_bytes:
                        raise ConnectionError(f"Incomplete download: {downloaded}/{total_bytes} bytes")
                    if downloaded <= 0:
                        raise ConnectionError("0 bytes received")

                    break

        # Téléchargement complet : renommer .part → fichier final
        if part_path.exists():
            # Supprimer le fichier final existant s'il existe (il est incomplet/invalide)
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            shutil.move(str(part_path), str(output_path))
            logger.info(".part file renamed to final file: %s (%s)", output_path.name, format_bytes(downloaded))
        metadata_path.unlink(missing_ok=True)

        # Sous-titres
        if task.downloadSubtitles:
            await self._download_subtitles(task)

        await self._finalize_task(task)

    async def _download_mytv_chunks(self, task: DownloadTask, chunks: List[str]):
        task.phase = "video"
        self.broadcast_update(task)
        logger.info("myTV: %d chunk(s) to download for %s", len(chunks), task.fileName)
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
        logger.info("Concatenating %d chunks to %s", len(chunk_files), task.fileName)
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
        logger.info("HLS download for %s from %s", task.fileName, m3u8_url)
        if task.totalBytes <= 0:
            try:
                est_sz = await self.estimate_hls_size(m3u8_url)
                if est_sz > 0:
                    task.totalBytes = est_sz
                    self.broadcast_update(task)
            except VerificationRequired:
                raise
            except Exception:
                pass

        # Téléchargement natif par segments avec micro-retries in-situ et reprise sans perte
        await self._download_hls_segments_native(task, m3u8_url)

    async def _download_hls_segments_native(self, task: DownloadTask, m3u8_url: str):
        task.phase = "video"
        self.broadcast_update(task)
        logger.info("Segmented HLS download (with resume) for %s", task.fileName)
        output_path = Path(task.savePath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        segments_dir = output_path.parent / f".{output_path.stem}_segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        headers = self.get_headers_for_url(m3u8_url, getattr(task, "selectedServer", None))
        proxy = proxy_service.get_random_proxy()

        timeout = httpx.Timeout(connect=20.0, read=45.0, write=30.0, pool=30.0)
        async with self._create_async_client(headers=headers, proxy=proxy, timeout=timeout) as client:
            resp = await client.get(m3u8_url)
            if resp.status_code != 200:
                raise ConnectionError(f"HTTP {resp.status_code} on m3u8 playlist")

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
                        raise ConnectionError(f"HTTP {sub_resp.status_code} on HLS sub-playlist")
                    playlist_text = sub_resp.text

            segments = []
            encryption = []
            current_key = None
            sequence = 0
            for line in playlist_text.splitlines():
                line = line.strip()
                if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                    sequence = int(line.split(":", 1)[1])
                elif line.startswith("#EXT-X-KEY:"):
                    attrs = dict(re.findall(r'(\w+)=("[^"\n]*"|[^,\n]*)', line.split(":", 1)[1]))
                    method = attrs.get("METHOD", "NONE")
                    if method == "NONE":
                        current_key = None
                    elif method == "AES-128" and attrs.get("URI"):
                        key_url = urljoin(sub_url, attrs["URI"].strip('"'))
                        iv = bytes.fromhex(attrs["IV"].removeprefix("0x").zfill(32)) if attrs.get("IV") else None
                        if iv is not None and len(iv) != 16:
                            raise ValueError("IV AES-128 HLS invalide")
                        current_key = (key_url, iv)
                    else:
                        raise ValueError("Méthode de chiffrement HLS non prise en charge")
                elif line and not line.startswith("#"):
                    segments.append(urljoin(sub_url, line))
                    encryption.append((current_key[0], current_key[1] or sequence.to_bytes(16, "big")) if current_key else None)
                    sequence += 1
            keys = {}

            if not segments:
                raise ValueError("No segments found in HLS playlist")

            prepare_hls_cache(segments_dir, sub_url, playlist_text)

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
                logger.info("HLS resume for %s: %d/%d segments already present (%s)",
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
                                        raise ConnectionError(f"HTTP {seg_resp.status_code} on segment {idx} (expired or not found link)")
                                    raise ConnectionError(f"HTTP {seg_resp.status_code} on segment {idx}")

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
                                declared_length = seg_resp.headers.get("Content-Length")
                                if not (task.cancelled or task.paused) and declared_length is not None and (
                                        not declared_length.isdigit() or int(declared_length) != seg_bytes_this_attempt):
                                    raise ConnectionError(f"Incomplete HLS segment {idx}")
                        else:
                            seg_resp = await client.get(seg_url)
                            if seg_resp.status_code != 200:
                                if seg_resp.status_code in (403, 404, 410):
                                    raise ConnectionError(f"HTTP {seg_resp.status_code} on segment {idx} (expired or not found link)")
                                raise ConnectionError(f"HTTP {seg_resp.status_code} on segment {idx}")
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
                            if encryption[idx]:
                                key_url, iv = encryption[idx]
                                if key_url not in keys:
                                    key_response = await client.get(key_url)
                                    key_response.raise_for_status()
                                    if len(key_response.content) != 16:
                                        raise ValueError("Clé AES-128 HLS invalide")
                                    keys[key_url] = key_response.content
                                plaintext = media_tools.decrypt_aes_cbc(
                                    seg_tmp.read_bytes(), keys[key_url], iv, unpad=True)
                                seg_tmp.write_bytes(plaintext)
                            seg_tmp.replace(seg_file)
                            completed_indices.add(idx)
                            seg_success = True
                            break
                        else:
                            raise ConnectionError(f"Segment {idx} downloaded empty (0 bytes)")

                    except (VerificationRequired, RateLimited):
                        raise
                    except Exception as seg_err:
                        if seg_bytes_this_attempt > 0:
                            downloaded -= seg_bytes_this_attempt
                            task.downloadedBytes = downloaded
                        if seg_tmp.exists():
                            seg_tmp.unlink(missing_ok=True)

                        err_str = str(seg_err).lower()
                        if "expiré" in err_str or "expired" in err_str or "403" in err_str or "410" in err_str:
                            raise seg_err

                        if attempt >= max_seg_retries:
                            logger.warning("Permanent failure for segment %d/%d after %d retries for %s: %s",
                                           idx + 1, total_segments, max_seg_retries, task.fileName, seg_err)
                            raise seg_err

                        backoff = min(1.0 * attempt, 4.0)
                        logger.warning("Micro-interruption on segment %d/%d for %s (%s), retry %d/%d in %.1fs...",
                                       idx + 1, total_segments, task.fileName, seg_err, attempt + 1, max_seg_retries, backoff)
                        await asyncio.sleep(backoff)

                if not seg_success and not (task.cancelled or task.paused):
                    raise ConnectionError(f"Cannot download segment {idx}")

                now = time.time()
                task.update_progress(downloaded, now)
                task.progress = min(99.0, (len(completed_indices) / total_segments) * 100.0)
                if now - last_time >= 0.5:
                    last_time = now
                    self.broadcast_update(task)

        task.phase = "assembling"
        task.reset_speed()
        self.broadcast_update(task)

        # Assemblage final sans perte des segments HLS
        logger.info("Assembling %d HLS segments to %s", total_segments, task.fileName)
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
                "-i", str(concat_file),
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                str(temp_output)
            ]
            if media_tools.is_native():
                result = await asyncio.to_thread(media_tools.run, remux_cmd, timeout=300)
                r_rc = result.returncode
            else:
                r_proc = await asyncio.create_subprocess_exec(
                    *remux_cmd, cwd=str(segments_dir),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
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
        if task.cancelled or task.paused:
            task.status = DownloadStatus.CANCELLED if task.cancelled else DownloadStatus.PAUSED
            library_service.save_task(task)
            self.broadcast_update(task)
            return
        task.progress = 100.0
        task.speed = 0

        # Muxing FFmpeg si sous-titres présents
        if task.savePathSubtitle and self.is_ffmpeg_available():
            task.status = DownloadStatus.MUXING
            task.phase = "muxing"
            self.broadcast_update(task)
            library_service.save_task(task)
            try:
                await asyncio.to_thread(self._mux_subtitles_with_ffmpeg, task)
            except Exception as exc:
                task.status = DownloadStatus.FAILED
                task.error = f"Échec de fusion des sous-titres : {exc}"
                self.broadcast_update(task)
                library_service.save_task(task)
                return

        if task.cancelled or task.paused:
            task.status = DownloadStatus.CANCELLED if task.cancelled else DownloadStatus.PAUSED
            library_service.save_task(task)
            self.broadcast_update(task)
            return

        task.phase = "verifying"
        self.broadcast_update(task)

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
            # Keep the foreground transfer alive until its shared-storage copy
            # has been published. Android may kill an idle background process.
            if platform_events.completed_handler is not None:
                try:
                    await asyncio.to_thread(platform_events.completed, task)
                except Exception as exc:
                    logger.exception("Completed media could not be exported by the native platform")
                    task.error = f"Android export failed; media is available in the library: {exc}"
            task.status = DownloadStatus.COMPLETED
            task.completedAt = datetime.now(timezone.utc)
            part_path = Path(task.savePath + ".part")
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            self.broadcast_update(task)
            library_service.save_task(task)

            # Progression
            library_service.mark_as_downloaded(
                task.animeUrl or task.downloadPageUrl or "",
                task.animeName,
                task.episodeNumber,
                task.version
            )
            logger.info("Download completed and verified: %s (%s, duration: %s)", task.fileName, task.formattedTotalSize, verif.formattedDuration)

            if self.plex_organization:
                await asyncio.to_thread(self._generate_nfo_files, task)
        else:
            task.status = DownloadStatus.FAILED
            task.error = f"Integrity verification failed: {verif.error}"
            self.broadcast_update(task)
            library_service.save_task(task)
            logger.error("Download failed after verification for %s: %s", task.fileName, verif.error)

    # -------------------------------------------------------------------------
    # Sous-titres & FFmpeg
    # -------------------------------------------------------------------------

    def _update_resolved_subtitles(self, task: DownloadTask, value, base_url: str):
        tracks = normalize_subtitles(value, base_url)
        # A failed/empty re-extraction must not erase known pending subtitles.
        if not tracks:
            return
        previous = {track["url"]: track for track in normalize_subtitles(task.subtitlesJson)}
        for track in tracks:
            cached = previous.get(track["url"], {})
            for key in ("path", "muxed"):
                if key in cached:
                    track[key] = cached[key]
        task.subtitlesJson = json.dumps(tracks)

    def _recover_muxed_file(self, task: DownloadTask) -> bool:
        """Recover a legacy task whose MP4 was removed after a successful MKV export.

        Only the exact sibling destination is considered, and every requested track
        must be present with its title and language. Never adopt an arbitrary MKV.
        """
        if not task.savePath or Path(task.savePath).exists():
            return False
        candidate = Path(task.savePath).with_suffix(".mkv")
        if not candidate.is_file() or not media_tools.which("ffprobe"):
            return False
        try:
            tracks = normalize_subtitles(task.subtitlesJson)
            if task.downloadSubtitles and not tracks:
                return False
            result = verification_service.verify_file(str(candidate), expected_size=task.totalBytes or None)
            if not result.valid:
                return False
            probe = media_tools.run([media_tools.which("ffprobe"), "-v", "error", "-show_streams",
                                    "-of", "json", str(candidate)], capture_output=True,
                                   text=True, check=True, timeout=30)
            present = Counter((stream.get("tags", {}).get("title", ""),
                               stream.get("tags", {}).get("language", "und"))
                              for stream in json.loads(probe.stdout).get("streams", [])
                              if stream.get("codec_type") == "subtitle")
            expected = Counter((track["label"], subtitle_language(track.get("lang"))) for track in tracks)
            if task.downloadSubtitles and any(present[key] < count for key, count in expected.items()):
                return False
            for track in tracks:
                track["muxed"] = True
            task.subtitlesJson = json.dumps(tracks)
            task.savePathSubtitle = None
            task.savePath = str(candidate)
            task.fileName = candidate.name
            task.totalBytes = task.downloadedBytes = candidate.stat().st_size
            library_service.save_task(task)
            return True
        except (OSError, ValueError, subprocess.SubprocessError):
            logger.warning("Unable to recover existing mux for %s", task.fileName, exc_info=True)
            return False

    def _has_pending_subtitles(self, task: DownloadTask) -> bool:
        if not task.downloadSubtitles:
            return False
        if task.savePathSubtitle:
            return True
        try:
            tracks = normalize_subtitles(task.subtitlesJson)
        except (ValueError, TypeError):
            return True
        return not tracks or any(not track.get("muxed") for track in tracks)

    async def _download_subtitles(self, task: DownloadTask):
        base_url = task.downloadPageUrl or task.fileUrl or task.directDownloadUrl or ""
        try:
            subs = normalize_subtitles(task.subtitlesJson, base_url)
        except (ValueError, TypeError) as exc:
            raise SubtitleError(f"Métadonnées de sous-titres invalides : {exc}") from exc
        if not subs and task.subtitleUrl:
            subs = normalize_subtitles([{"url": task.subtitleUrl}], base_url)
        pending = [(index, sub) for index, sub in enumerate(subs) if not sub.get("muxed")]
        if not pending:
            return

        task.phase = "subtitles"
        task.reset_speed()
        self.broadcast_update(task)
        downloaded_paths = []
        errors = []
        refresh_required = False
        parent = Path(task.savePath).parent

        async def validate_request(request):
            if not is_safe_url(str(request.url)):
                raise ValueError("URL de sous-titres non autorisée")

        headers = self.get_headers_for_url(base_url, task.selectedServer)
        if base_url:
            headers["Referer"] = base_url
        try:
            async with self._create_async_client(headers=headers, timeout=30.0) as client:
                client.event_hooks.setdefault("request", []).append(validate_request)
                for index, sub in pending:
                    if task.cancelled or task.paused:
                        return
                    url, label = sub["url"], sub["label"]
                    try:
                        # A completed sidecar survives retries, including an expired CDN URL.
                        cached = Path(sub["path"]) if sub.get("path") else None
                        if cached and is_safe_path(cached, [parent]) and cached.is_file():
                            if 0 < cached.stat().st_size <= 10 * 1024 * 1024:
                                try:
                                    subtitle_extension(cached.read_bytes())
                                    downloaded_paths.append(str(cached))
                                    continue
                                except ValueError:
                                    pass
                        if not is_safe_url(url):
                            raise ValueError("URL de sous-titres non autorisée")
                        request_headers = dict(sub.get("headers") or {})
                        if sub.get("referer"):
                            request_headers["Referer"] = sub["referer"]
                        for attempt in range(3):
                            if task.cancelled or task.paused:
                                return
                            try:
                                resp = await client.get(url, headers=request_headers)
                                resp.raise_for_status()
                                break
                            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                                transient = (not hasattr(exc, "kind") and
                                    (not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in (408, 500, 502, 503, 504)))
                                if (isinstance(exc, httpx.HTTPStatusError) and hasattr(client, "service")
                                        and exc.response.status_code in (502, 503, 504)):
                                    transient = False  # The common transport already retried these.
                                if not transient or attempt == 2:
                                    raise
                                await asyncio.sleep(2 ** attempt)
                        if not resp.content or len(resp.content) > 10 * 1024 * 1024:
                            raise ValueError("Sous-titres vides ou trop volumineux")
                        ext = subtitle_extension(resp.content)
                        clean_label = self.sanitize_file_name(str(label)) or "Sous-titres"
                        sub_name = f"{Path(task.savePath).stem}.sub{index + 1}.{clean_label}{ext}"
                        sub_path = parent / sub_name
                        if not is_safe_path(sub_path, [parent]):
                            raise ValueError("Chemin de sous-titres non autorisé")
                        parent.mkdir(parents=True, exist_ok=True)
                        staging = None
                        try:
                            with tempfile.NamedTemporaryFile(dir=parent, prefix=".animan-sub-", delete=False) as temp:
                                staging = Path(temp.name)
                                temp.write(resp.content)
                            staging.replace(sub_path)
                        finally:
                            if staging:
                                staging.unlink(missing_ok=True)
                        sub["path"] = str(sub_path)
                        downloaded_paths.append(str(sub_path))
                        logger.info("Subtitles downloaded: %s", sub_name)
                    except (VerificationRequired, RateLimited):
                        raise
                    except Exception as exc:
                        if isinstance(exc, httpx.TimeoutException):
                            reason = "Délai réseau dépassé après 3 tentatives"
                        elif isinstance(exc, httpx.HTTPStatusError):
                            reason = f"HTTP {exc.response.status_code}"
                            refresh_required = refresh_required or exc.response.status_code in (401, 403, 404, 410)
                        else:
                            reason = str(exc).strip() or type(exc).__name__
                        errors.append(f"{label}: {reason}")
                        logger.warning("Error downloading subtitles %s: %s", label, reason)
        finally:
            # Persist partial success even when a later track requires verification.
            task.subtitlesJson = json.dumps(subs)
            task.savePathSubtitle = json.dumps(downloaded_paths) if downloaded_paths else None
            library_service.save_task(task)
        if errors:
            raise SubtitleError("Échec du téléchargement des sous-titres : " + "; ".join(errors), refresh_required)

    def is_ffmpeg_available(self) -> bool:
        return media_tools.which("ffmpeg") is not None

    def _mux_subtitles_with_ffmpeg(self, task: DownloadTask):
        if not self.is_ffmpeg_available():
            raise RuntimeError("FFmpeg indisponible")
        video_path = Path(task.savePath)
        if not video_path.is_file():
            raise ValueError("Vidéo introuvable")

        try:
            sub_paths = json.loads(task.savePathSubtitle or "[]")
        except (ValueError, TypeError):
            sub_paths = [task.savePathSubtitle]
        if not isinstance(sub_paths, list):
            sub_paths = [sub_paths]
        existing_subs = [Path(sp) for sp in sub_paths if sp and
                         is_safe_path(Path(sp), [video_path.parent]) and Path(sp).is_file()]
        if not existing_subs or len(existing_subs) != len(sub_paths):
            raise ValueError("Fichier de sous-titres introuvable")
        metadata = {s.get("path"): s for s in normalize_subtitles(task.subtitlesJson)}

        original = verification_service.verify_file(str(video_path), expected_size=task.totalBytes)
        if not original.valid:
            raise ValueError(f"Vidéo source invalide : {original.error}")
        probe_path = media_tools.which("ffprobe")
        if not probe_path:
            raise RuntimeError("FFprobe requis pour valider les pistes fusionnées")

        def probe(path):
            result = media_tools.run([probe_path, "-v", "error", "-show_streams", "-of", "json", str(path)],
                                    capture_output=True, text=True, check=True, timeout=30)
            return json.loads(result.stdout).get("streams", [])

        embedded = [s for s in probe(video_path) if s.get("codec_type") == "subtitle"]
        output_path = video_path.with_suffix(".mkv")
        with tempfile.NamedTemporaryFile(dir=video_path.parent, prefix=".animan-mux-", suffix=".mkv", delete=False) as temp:
            staging = Path(temp.name)
        try:
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(video_path)]
            for sf in existing_subs:
                cmd.extend(["-i", str(sf)])
            cmd.extend(["-map", "0:v", "-map", "0:a?", "-map", "0:s?",
                        "-c:v", "copy", "-c:a", "copy", "-c:s", "copy"])
            for index, stream in enumerate(embedded):
                if stream.get("codec_name") == "mov_text":
                    cmd.extend([f"-c:s:{index}", "srt"])
            for index, sf in enumerate(existing_subs):
                cmd.extend(["-map", f"{index + 1}:s:0"])
                stream_index = len(embedded) + index
                if sf.suffix.lower() == ".vtt":
                    cmd.extend([f"-c:s:{stream_index}", "srt"])
                track = metadata.get(str(sf), {})
                title = track.get("label") or sf.stem
                lang = subtitle_language(track.get("lang") or track.get("srclang"))
                cmd.extend([f"-metadata:s:s:{stream_index}", f"language={lang}",
                            f"-metadata:s:s:{stream_index}", f"title={title}"])
            cmd.append(str(staging))
            result = media_tools.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise RuntimeError(result.stderr.strip()[-1000:] or "FFmpeg a échoué")
            verification = verification_service.verify_file(str(staging))
            if not verification.valid:
                raise ValueError(f"Vidéo fusionnée invalide : {verification.error}")
            subtitles = [s for s in probe(staging) if s.get("codec_type") == "subtitle"]
            if len(subtitles) != len(embedded) + len(existing_subs):
                raise ValueError("Pistes de sous-titres manquantes après fusion")
            if task.cancelled or task.paused:
                return
            if output_path == video_path:
                staging.replace(output_path)
            else:
                # Publish atomically without overwriting another episode or a previous export.
                # link() also handles a destination created concurrently after our check.
                for collision in range(1000):
                    candidate = output_path if collision == 0 else output_path.with_name(
                        f"{output_path.stem}.subtitled-{self.sanitize_file_name(task.id)[:12]}-{collision}.mkv")
                    try:
                        try:
                            os.link(staging, candidate)
                        except OSError as exc:
                            if exc.errno not in (errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP):
                                raise
                            # FAT/removable drives may not support hard links. Reserve
                            # exclusively, then atomically replace only our placeholder.
                            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                            os.close(fd)
                            try:
                                staging.replace(candidate)
                            except BaseException:
                                candidate.unlink(missing_ok=True)
                                raise
                        output_path = candidate
                        break
                    except FileExistsError:
                        continue
                else:
                    raise FileExistsError("Impossible de réserver un nom de fichier pour la fusion")
            task.fileName = output_path.name
            task.savePath = str(output_path)
            task.totalBytes = task.downloadedBytes = output_path.stat().st_size
            task.savePathSubtitle = None
            tracks = normalize_subtitles(task.subtitlesJson)
            for track in tracks:
                if track.get("path") in sub_paths:
                    track["muxed"] = True
            task.subtitlesJson = json.dumps(tracks)
            library_service.save_task(task)
            for obsolete in ([video_path] if video_path != output_path else []) + existing_subs:
                try:
                    obsolete.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Export completed; unable to remove %s", obsolete.name, exc_info=True)
            logger.info("FFmpeg muxing succeeded: %s", output_path.name)
        finally:
            staging.unlink(missing_ok=True)

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
            logger.error("Error generating NFO: %s", e)

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
        try:
            platform_events.progress(task)
        except Exception:
            logger.exception("Native download notification update failed")
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
        now = datetime.now(timezone.utc)
        for t in self.tasks.values():
            if t.status == DownloadStatus.SCHEDULED and t.scheduledStartTime:
                if ensure_utc(t.scheduledStartTime) <= now:
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
        if re.search(r"\.(mp4|mkv|avi|webm|m3u8)(\?.*)?$", url):
            return False
        if extractor_registry.is_known_embed(url):
            return False
        if "vidzy.live" in url or "luluvdo.com" in url or "french-manga.net" in url:
            return True
        if "vidzy.cc" in url and any(x in url for x in ["/e/", "/d/", "embed-"]):
            return True
        return not bool(re.search(r"\.(mp4|mkv|avi|webm|ts|m4v|m3u8)(\?.*)?$", url))

download_manager = DownloadManagerService()
