from urllib.parse import quote
from jinja2 import pass_context
from fastapi.templating import Jinja2Templates
from animan.config import settings
from animan.services.i18n_service import i18n_service, current_request_lang

templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))

def proxy_img_filter(url: str) -> str:
    if not url:
        return ""
    if any(d in url for d in ["voir-anime", "voembed", "vidmoly", "french-manga", "animepahe", "anime-sama", "jetanime"]) and not url.startswith("/api/media/image-proxy"):
        return f"/api/media/image-proxy?url={quote(url, safe=':/?&=%')}"
    return url

templates.env.filters["proxy_img"] = proxy_img_filter

from markupsafe import Markup

@pass_context
def t_helper(context, key: str, **kwargs) -> str:
    request = context.get("request")
    lang = getattr(getattr(request, "state", None), "lang", None)
    if not lang and request and hasattr(request, "cookies"):
        lang = request.cookies.get("animan_lang")
    if not lang:
        lang = current_request_lang.get() or settings.DEFAULT_LANGUAGE
    return Markup(i18n_service.translate(key, lang, **kwargs))

@pass_context
def current_lang_helper(context) -> str:
    request = context.get("request")
    lang = getattr(getattr(request, "state", None), "lang", None)
    if not lang and request and hasattr(request, "cookies"):
        lang = request.cookies.get("animan_lang")
    return lang or current_request_lang.get() or settings.DEFAULT_LANGUAGE

templates.env.globals["t"] = t_helper
templates.env.globals["current_lang"] = current_lang_helper

def get_enabled_extensions_helper():
    try:
        from animan.services.extension_service import extension_service
        return extension_service.get_enabled_container_sources()
    except Exception:
        return []

templates.env.globals["get_enabled_extensions"] = get_enabled_extensions_helper
