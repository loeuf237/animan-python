from urllib.parse import quote
from fastapi.templating import Jinja2Templates
from animan.config import settings

templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))

def proxy_img_filter(url: str) -> str:
    if not url:
        return ""
    if any(d in url for d in ["voir-anime", "voembed", "vidmoly", "french-manga", "animepahe"]) and not url.startswith("/api/media/image-proxy"):
        return f"/api/media/image-proxy?url={quote(url, safe=':/?&=%')}"
    return url

templates.env.filters["proxy_img"] = proxy_img_filter
