import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from sqlalchemy import Column, Integer, BigInteger, Float, String, Boolean, DateTime
from animan.database import Base

class DownloadStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    DOWNLOADING = "DOWNLOADING"
    RETRYING = "RETRYING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    MUXING = "MUXING"

def format_bytes(b: int) -> str:
    if b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(b)
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"

def format_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds <= 0:
        return ""
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs}h {mins:02d}m {secs:02d}s"
    elif mins > 0:
        return f"{mins}m {secs:02d}s"
    else:
        return f"{secs}s"

class DownloadTaskEntity(Base):
    __tablename__ = "download_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    animeName = Column(String, nullable=False)
    episodeNumber = Column(Integer, default=0)
    fileName = Column(String, nullable=False)
    fileUrl = Column(String, nullable=True)
    savePath = Column(String, nullable=True)
    savePathSubtitle = Column(String, nullable=True)
    downloadPageUrl = Column(String, nullable=True)
    directDownloadUrl = Column(String, nullable=True)
    subtitleUrl = Column(String, nullable=True)
    subtitlesJson = Column(String, default="[]")
    error = Column(String, nullable=True)
    status = Column(String, default=DownloadStatus.PENDING.value, nullable=False)
    progress = Column(Float, default=0.0)
    downloadedBytes = Column(BigInteger, default=0)
    totalBytes = Column(BigInteger, default=0)
    maxSpeedLimit = Column(BigInteger, default=0)
    retryCount = Column(Integer, default=0)
    downloadSubtitles = Column(Boolean, default=False)
    scheduledStartTime = Column(DateTime, nullable=True)
    createdAt = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completedAt = Column(DateTime, nullable=True)
    source = Column(String, default="french-manga")
    verificationStatus = Column(String, default="UNVERIFIED", nullable=False)
    videoDuration = Column(Float, nullable=True)
    verifiedAt = Column(DateTime, nullable=True)
    verificationError = Column(String, nullable=True)
    selectedServer = Column(String, nullable=True)
    selectedQuality = Column(String, nullable=True)

    def to_task(self) -> "DownloadTask":
        return DownloadTask(
            id=self.id,
            animeName=self.animeName,
            episodeNumber=self.episodeNumber,
            fileName=self.fileName,
            fileUrl=self.fileUrl or "",
            savePath=self.savePath,
            savePathSubtitle=self.savePathSubtitle,
            downloadPageUrl=self.downloadPageUrl,
            directDownloadUrl=self.directDownloadUrl,
            subtitleUrl=self.subtitleUrl,
            subtitlesJson=self.subtitlesJson or "[]",
            error=self.error,
            status=DownloadStatus(self.status),
            progress=self.progress,
            downloadedBytes=self.downloadedBytes,
            totalBytes=self.totalBytes,
            maxSpeedLimit=self.maxSpeedLimit,
            retryCount=self.retryCount,
            downloadSubtitles=self.downloadSubtitles,
            scheduledStartTime=self.scheduledStartTime,
            createdAt=self.createdAt,
            completedAt=self.completedAt,
            source=self.source,
            verificationStatus=self.verificationStatus or "UNVERIFIED",
            videoDuration=self.videoDuration,
            verifiedAt=self.verifiedAt,
            verificationError=self.verificationError,
            selectedServer=self.selectedServer,
            selectedQuality=self.selectedQuality,
        )

class DownloadTask:
    def __init__(
        self,
        id: Optional[str] = None,
        animeName: str = "",
        episodeNumber: int = 0,
        fileName: str = "",
        fileUrl: str = "",
        savePath: Optional[str] = None,
        savePathSubtitle: Optional[str] = None,
        downloadPageUrl: Optional[str] = None,
        directDownloadUrl: Optional[str] = None,
        subtitleUrl: Optional[str] = None,
        subtitlesJson: str = "[]",
        error: Optional[str] = None,
        status: DownloadStatus = DownloadStatus.PENDING,
        progress: float = 0.0,
        downloadedBytes: int = 0,
        totalBytes: int = 0,
        maxSpeedLimit: int = 0,
        retryCount: int = 0,
        downloadSubtitles: bool = False,
        scheduledStartTime: Optional[datetime] = None,
        createdAt: Optional[datetime] = None,
        completedAt: Optional[datetime] = None,
        source: str = "french-manga",
        verificationStatus: str = "UNVERIFIED",
        videoDuration: Optional[float] = None,
        verifiedAt: Optional[datetime] = None,
        verificationError: Optional[str] = None,
        selectedServer: Optional[str] = None,
        selectedQuality: Optional[str] = None,
    ):
        self.id = id or str(uuid.uuid4())
        self.animeName = animeName
        self.episodeNumber = episodeNumber
        self.fileName = fileName
        self.fileUrl = fileUrl
        self.savePath = savePath
        self.savePathSubtitle = savePathSubtitle
        self.downloadPageUrl = downloadPageUrl
        self.directDownloadUrl = directDownloadUrl
        self.subtitleUrl = subtitleUrl
        self.subtitlesJson = subtitlesJson
        self.error = error
        self.status = status
        self.progress = progress
        self.downloadedBytes = downloadedBytes
        self.totalBytes = totalBytes
        self.speed: int = 0  # bytes/sec
        self.maxSpeedLimit = maxSpeedLimit
        self.retryCount = retryCount
        self.downloadSubtitles = downloadSubtitles
        self.scheduledStartTime = scheduledStartTime
        self.createdAt = createdAt or datetime.now(timezone.utc)
        self.completedAt = completedAt
        self.source = source
        self.verificationStatus = verificationStatus
        self.videoDuration = videoDuration
        self.verifiedAt = verifiedAt
        self.verificationError = verificationError
        self.selectedServer = selectedServer
        self.selectedQuality = selectedQuality

        # Runtime control flags
        self.cancelled: bool = False
        self.paused: bool = False
        self.supportsResume: bool = False
        self.throttleBytesWritten: int = 0
        self.throttleStartTimeMs: float = 0.0

    @property
    def formattedTotalSize(self) -> str:
        if self.totalBytes <= 0:
            return "Taille inconnue"
        return format_bytes(self.totalBytes)

    @property
    def formattedDownloadedSize(self) -> str:
        return format_bytes(self.downloadedBytes)

    @property
    def formattedSpeed(self) -> str:
        if self.speed <= 0:
            return "0 B/s"
        return f"{format_bytes(self.speed)}/s"

    @property
    def formattedDuration(self) -> str:
        return format_duration(self.videoDuration)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "animeName": self.animeName,
            "episodeNumber": self.episodeNumber,
            "fileName": self.fileName,
            "status": self.status.value,
            "progress": round(self.progress, 1),
            "downloadedBytes": self.downloadedBytes,
            "totalBytes": self.totalBytes,
            "downloadedSize": self.formattedDownloadedSize,
            "totalSize": self.formattedTotalSize,
            "speed": self.formattedSpeed,
            "speedBytes": self.speed,
            "error": self.error,
            "savePath": self.savePath,
            "scheduledStartTime": self.scheduledStartTime.isoformat() if self.scheduledStartTime else None,
            "downloadPageUrl": self.downloadPageUrl,
            "directDownloadUrl": self.directDownloadUrl,
            "downloadSubtitles": self.downloadSubtitles,
            "maxSpeedLimit": self.maxSpeedLimit,
            "verificationStatus": self.verificationStatus,
            "videoDuration": self.videoDuration,
            "formattedDuration": self.formattedDuration,
            "verifiedAt": self.verifiedAt.isoformat() if self.verifiedAt else None,
            "verificationError": self.verificationError,
            "selectedServer": self.selectedServer,
            "selectedQuality": self.selectedQuality,
        }

    def to_entity(self) -> DownloadTaskEntity:
        return DownloadTaskEntity(
            id=self.id,
            animeName=self.animeName,
            episodeNumber=self.episodeNumber,
            fileName=self.fileName,
            fileUrl=self.fileUrl,
            savePath=self.savePath,
            savePathSubtitle=self.savePathSubtitle,
            downloadPageUrl=self.downloadPageUrl,
            directDownloadUrl=self.directDownloadUrl,
            subtitleUrl=self.subtitleUrl,
            subtitlesJson=self.subtitlesJson,
            error=self.error,
            status=self.status.value,
            progress=self.progress,
            downloadedBytes=self.downloadedBytes,
            totalBytes=self.totalBytes,
            maxSpeedLimit=self.maxSpeedLimit,
            retryCount=self.retryCount,
            downloadSubtitles=self.downloadSubtitles,
            scheduledStartTime=self.scheduledStartTime,
            createdAt=self.createdAt,
            completedAt=self.completedAt,
            source=self.source,
            verificationStatus=self.verificationStatus,
            videoDuration=self.videoDuration,
            verifiedAt=self.verifiedAt,
            verificationError=self.verificationError,
            selectedServer=self.selectedServer,
            selectedQuality=self.selectedQuality,
        )
