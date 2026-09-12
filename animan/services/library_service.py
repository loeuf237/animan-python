from datetime import datetime, timezone
from typing import List, Optional, Set
from sqlalchemy.orm import Session

from animan.database import SessionLocal
from animan.models.favorite import FavoriteAnime
from animan.models.watch_progress import WatchProgress
from animan.models.download_task import DownloadTask, DownloadTaskEntity, DownloadStatus

class LibraryService:
    # -------------------------------------------------------------------------
    # FAVORIS
    # -------------------------------------------------------------------------

    def add_favorite(self, url: str, title: str, image_url: str = "", source: str = "french-manga") -> FavoriteAnime:
        with SessionLocal() as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            if fav:
                return fav
            fav = FavoriteAnime(
                url=url,
                title=title,
                imageUrl=image_url,
                source=source,
                addedAt=datetime.now(timezone.utc),
            )
            db.add(fav)
            db.commit()
            db.refresh(fav)
            return fav

    def remove_favorite(self, url: str):
        with SessionLocal() as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            if fav:
                db.delete(fav)
                db.commit()

    def remove_all_favorites(self):
        with SessionLocal() as db:
            db.query(FavoriteAnime).delete()
            db.commit()

    def is_favorite(self, url: str) -> bool:
        with SessionLocal() as db:
            return db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first() is not None

    def get_all_favorites(self) -> List[FavoriteAnime]:
        with SessionLocal() as db:
            return db.query(FavoriteAnime).order_by(FavoriteAnime.addedAt.desc()).all()

    def update_auto_download(self, url: str, auto_download: bool) -> Optional[FavoriteAnime]:
        with SessionLocal() as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            if fav:
                fav.autoDownload = auto_download
                db.commit()
                db.refresh(fav)
                return fav
            return None

    def update_last_known_episode(self, url: str, episode_count: int):
        with SessionLocal() as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            if fav:
                fav.lastKnownEpisode = episode_count
                fav.lastCheckedAt = datetime.now(timezone.utc)
                db.commit()

    # -------------------------------------------------------------------------
    # PROGRESSION
    # -------------------------------------------------------------------------

    def mark_as_downloaded(self, anime_url: str, anime_name: str, episode_number: int, version: str = "") -> WatchProgress:
        with SessionLocal() as db:
            prog = db.query(WatchProgress).filter(
                WatchProgress.animeUrl == anime_url,
                WatchProgress.episodeNumber == episode_number,
                WatchProgress.version == version
            ).first()
            if not prog:
                prog = WatchProgress(
                    animeUrl=anime_url,
                    animeName=anime_name,
                    episodeNumber=episode_number,
                    version=version
                )
                db.add(prog)
            prog.downloaded = True
            prog.downloadedAt = datetime.now(timezone.utc)
            db.commit()
            db.refresh(prog)
            return prog

    def mark_as_watched(self, anime_url: str, anime_name: str, episode_number: int, version: str = "") -> WatchProgress:
        with SessionLocal() as db:
            prog = db.query(WatchProgress).filter(
                WatchProgress.animeUrl == anime_url,
                WatchProgress.episodeNumber == episode_number,
                WatchProgress.version == version
            ).first()
            if not prog:
                prog = WatchProgress(
                    animeUrl=anime_url,
                    animeName=anime_name,
                    episodeNumber=episode_number,
                    version=version
                )
                db.add(prog)
            prog.watched = True
            prog.watchedAt = datetime.now(timezone.utc)
            db.commit()
            db.refresh(prog)
            return prog

    def get_progress_for_anime(self, anime_url: str) -> List[WatchProgress]:
        with SessionLocal() as db:
            return db.query(WatchProgress).filter(WatchProgress.animeUrl == anime_url).all()

    def get_downloaded_episodes_set(self, anime_url: str) -> Set[str]:
        with SessionLocal() as db:
            progs = db.query(WatchProgress).filter(
                WatchProgress.animeUrl == anime_url,
                WatchProgress.downloaded == True
            ).all()
            return {f"{p.episodeNumber}-{p.version}" for p in progs}

    def get_watched_episodes_set(self, anime_url: str) -> Set[str]:
        with SessionLocal() as db:
            progs = db.query(WatchProgress).filter(
                WatchProgress.animeUrl == anime_url,
                WatchProgress.watched == True
            ).all()
            return {f"{p.episodeNumber}-{p.version}" for p in progs}

    # -------------------------------------------------------------------------
    # HISTORIQUE & PERSISTANCE DES TÂCHES
    # -------------------------------------------------------------------------

    def _populate_entity(self, entity: DownloadTaskEntity, task: DownloadTask):
        entity.animeName = task.animeName
        entity.episodeNumber = task.episodeNumber
        entity.fileName = task.fileName
        entity.fileUrl = task.fileUrl
        entity.savePath = task.savePath
        entity.savePathSubtitle = task.savePathSubtitle
        entity.downloadPageUrl = task.downloadPageUrl
        entity.directDownloadUrl = task.directDownloadUrl
        entity.subtitleUrl = task.subtitleUrl
        entity.subtitlesJson = task.subtitlesJson
        entity.error = task.error
        entity.status = task.status.value
        entity.progress = task.progress
        entity.downloadedBytes = task.downloadedBytes
        entity.totalBytes = task.totalBytes
        entity.maxSpeedLimit = task.maxSpeedLimit
        entity.retryCount = task.retryCount
        entity.downloadSubtitles = task.downloadSubtitles
        entity.scheduledStartTime = task.scheduledStartTime
        entity.completedAt = task.completedAt
        entity.source = task.source
        entity.verificationStatus = task.verificationStatus
        entity.videoDuration = task.videoDuration
        entity.verifiedAt = task.verifiedAt
        entity.verificationError = task.verificationError

    def save_task(self, task: DownloadTask):
        with SessionLocal() as db:
            entity = db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id == task.id).first()
            if entity:
                self._populate_entity(entity, task)
            else:
                db.add(task.to_entity())
            db.commit()

    def save_tasks_batch(self, tasks: List[DownloadTask]):
        if not tasks:
            return
        with SessionLocal() as db:
            task_ids = [t.id for t in tasks]
            existing_entities = {
                e.id: e for e in db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id.in_(task_ids)).all()
            }
            for task in tasks:
                entity = existing_entities.get(task.id)
                if entity:
                    self._populate_entity(entity, task)
                else:
                    db.add(task.to_entity())
            db.commit()

    def get_history(self, anime_name: Optional[str] = None) -> List[DownloadTaskEntity]:
        with SessionLocal() as db:
            q = db.query(DownloadTaskEntity)
            if anime_name:
                q = q.filter(DownloadTaskEntity.animeName == anime_name)
            return q.order_by(DownloadTaskEntity.createdAt.desc()).all()

    def get_task_entity(self, task_id: str) -> Optional[DownloadTaskEntity]:
        with SessionLocal() as db:
            return db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id == task_id).first()

    def delete_task_entity(self, task_id: str) -> bool:
        with SessionLocal() as db:
            entity = db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id == task_id).first()
            if entity:
                db.delete(entity)
                db.commit()
                return True
            return False

    def clear_history(self, status: Optional[str] = None, anime_name: Optional[str] = None):
        with SessionLocal() as db:
            q = db.query(DownloadTaskEntity)
            if anime_name:
                q = q.filter(DownloadTaskEntity.animeName == anime_name)
            if status:
                statuses = [s.strip() for s in status.split(",") if s.strip()]
                q = q.filter(DownloadTaskEntity.status.in_(statuses))
            q.delete(synchronize_session=False)
            db.commit()

    def get_unfinished_tasks(self) -> List[DownloadTaskEntity]:
        with SessionLocal() as db:
            return db.query(DownloadTaskEntity).filter(
                DownloadTaskEntity.status.in_([
                    DownloadStatus.PENDING.value,
                    DownloadStatus.SCHEDULED.value,
                    DownloadStatus.DOWNLOADING.value,
                    DownloadStatus.RETRYING.value,
                    DownloadStatus.PAUSED.value
                ])
            ).all()

library_service = LibraryService()
