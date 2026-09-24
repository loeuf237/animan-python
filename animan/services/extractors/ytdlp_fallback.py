import asyncio
import logging
from typing import Optional

from animan.services.extractors.base import BaseVideoExtractor, ExtractorResult

logger = logging.getLogger(__name__)

class _YtdlQuietLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass

class YtDlpFallbackExtractor(BaseVideoExtractor):
    name = "yt-dlp"
    domains = []

    def matches(self, url: str) -> bool:
        # Utilisé explicitement comme repli par le registre
        return False

    async def extract(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ExtractorResult]:
        try:
            import yt_dlp

            def _extract_sync():
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "logger": _YtdlQuietLogger(),
                }
                if referer:
                    ydl_opts["http_headers"] = {"Referer": referer}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            info = await asyncio.to_thread(_extract_sync)
            if not info:
                return None

            direct = info.get("url")
            if not direct and info.get("formats"):
                valid_fmts = [f for f in info["formats"] if f.get("url")]
                if valid_fmts:
                    direct = valid_fmts[-1]["url"]

            if not direct:
                return None

            sz = info.get("filesize") or info.get("filesize_approx") or -1
            extractor_name = info.get("extractor", "yt-dlp")
            headers = {}
            if referer:
                headers["Referer"] = referer

            return ExtractorResult(
                video_url=direct,
                server_name=extractor_name,
                quality="HD",
                qualities={"HD": direct},
                headers=headers,
                size=sz if sz and sz > 0 else -1,
            )
        except Exception as e:
            logger.debug("Extraction yt-dlp échouée pour %s: %s", url, e)
            return None
