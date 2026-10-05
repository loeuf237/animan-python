from animan.services.source_http import VerificationRequired
import asyncio
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from animan.models.anime import AnimeResult, AnimeDetail
from animan.security import is_safe_url
from animan.services.library_service import library_service
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.animepahe_service import animepahe_service
from animan.services.extension_service import extension_service
from animan.services.tmdb_service import tmdb_service
from animan.templates_config import templates

logger = logging.getLogger("animan.router.anime")
router = APIRouter()

def detect_source_from_url(url: str, fallback: str = "french-manga") -> str:
    """Détecte automatiquement la source légitime d'un anime d'après son URL."""
    if not url:
        return fallback
    u = url.lower()
    if "animepahe" in u or "kwik." in u or "pahe." in u:
        return "animepahe"
    if "voir-anime" in u or "voiranime" in u:
        return "voir-anime"
    if "french-manga" in u:
        return "french-manga"
    # Vérifie si l'URL correspond à une extension Aniyomi active
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host:
            for src in extension_service.get_enabled_container_sources():
                if src.base_url and host in src.base_url.lower():
                    return src.pkg
    except VerificationRequired:
        raise
    except Exception:
        pass
    return fallback

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    favorites = library_service.get_all_favorites()
    latest_fm = await scraping_service.get_latest_releases()
    latest_va = await voiranime_service.get_latest_releases()
    latest_ap = await animepahe_service.get_latest_releases()
    enabled_extensions = extension_service.get_enabled_container_sources()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "favorites": favorites,
            "latestFrenchManga": latest_fm,
            "latestVoirAnime": latest_va,
            "latestAnimePahe": latest_ap,
            "enabledExtensions": enabled_extensions,
            "results": None,
            "query": "",
            "source": "french-manga",
        }
    )

@router.get("/api/releases/latest")
async def api_latest_releases(source: Optional[str] = None):
    """Retourne les dernières sorties en JSON pour hydratation dynamique instantanée."""
    norm_source = (source or "all").lower().strip()
    if norm_source == "french-manga":
        releases = await scraping_service.get_latest_releases()
        return {"source": "french-manga", "releases": [r.model_dump() for r in releases]}
    elif norm_source == "voir-anime":
        releases = await voiranime_service.get_latest_releases()
        return {"source": "voir-anime", "releases": [r.model_dump() for r in releases]}
    elif norm_source == "animepahe":
        releases = await animepahe_service.get_latest_releases()
        return {"source": "animepahe", "releases": [r.model_dump() for r in releases]}
    else:
        fm = await scraping_service.get_latest_releases()
        va = await voiranime_service.get_latest_releases()
        ap = await animepahe_service.get_latest_releases()
        return {
            "french-manga": [r.model_dump() for r in fm],
            "voir-anime": [r.model_dump() for r in va],
            "animepahe": [r.model_dump() for r in ap],
        }


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query(..., alias="q"),
    source: str = Query("french-manga", alias="source")
):
    norm_source = (source or "french-manga").lower().strip()
    logger.info("Search [%s]: %s", norm_source, q)

    enabled_exts = extension_service.get_enabled_container_sources()
    results: List[AnimeResult] = []

    if norm_source == "all":
        # Multi-sources ordonnées : 1) French-Manga, 2) VoirAnime, 3) AnimePahe, 4) Extensions actives
        tasks = [
            scraping_service.search_anime(q),
            voiranime_service.search_anime(q),
            animepahe_service.search_anime(q),
        ]
        # Ajouter les recherches des extensions actives
        for ext in enabled_exts:
            tasks.append(ext.search_anime(q))

        all_res = await asyncio.gather(*tasks, return_exceptions=True)
        fm_res, va_res, ap_res = all_res[0], all_res[1], all_res[2]
        ext_res_list = all_res[3:]

        if not isinstance(fm_res, Exception) and fm_res:
            for item in fm_res:
                item.source = "french-manga"
            results.extend(fm_res)
        if not isinstance(va_res, Exception) and va_res:
            for item in va_res:
                item.source = "voir-anime"
            results.extend(va_res)
        if not isinstance(ap_res, Exception) and ap_res:
            for item in ap_res:
                item.source = "animepahe"
            results.extend(ap_res)

        for idx, ext_res in enumerate(ext_res_list):
            if not isinstance(ext_res, Exception) and ext_res:
                ext_pkg = enabled_exts[idx].pkg
                for item in ext_res:
                    item.source = ext_pkg
                results.extend(ext_res)

    elif norm_source == "voir-anime":
        va_res = await voiranime_service.search_anime(q)
        for item in va_res:
            item.source = "voir-anime"
        results = va_res
    elif norm_source == "animepahe":
        ap_res = await animepahe_service.search_anime(q)
        for item in ap_res:
            item.source = "animepahe"
        results = ap_res
    elif norm_source == "french-manga":
        fm_res = await scraping_service.search_anime(q)
        for item in fm_res:
            item.source = "french-manga"
        results = fm_res
    else:
        # Recherche ciblée sur une extension importée
        ext_src = extension_service.get_container_source_by_id(norm_source)
        if ext_src:
            results = await ext_src.search_anime(q)
            for item in results:
                item.source = ext_src.pkg
        else:
            fm_res = await scraping_service.search_anime(q)
            for item in fm_res:
                item.source = "french-manga"
            results = fm_res

    favorites = library_service.get_all_favorites()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "results": results,
            "query": q,
            "source": norm_source,
            "favorites": favorites,
            "enabledExtensions": enabled_exts,
            "latestFrenchManga": [],
            "latestVoirAnime": [],
            "latestAnimePahe": [],
        }
    )

@router.get("/api/search")
async def search_api(
    q: str = Query(..., max_length=250),
    source: str = Query("all"),
    include_challenges: bool = Query(False),
):
    """Keep partial results and identify every source awaiting verification."""
    norm_source = (source or "all").lower().strip()
    providers = [("french-manga", scraping_service), ("voir-anime", voiranime_service),
                 ("animepahe", animepahe_service)]
    providers += [(ext.pkg, ext) for ext in extension_service.get_enabled_container_sources()]
    if norm_source != "all":
        ext = extension_service.get_container_source_by_id(norm_source)
        providers = [(sid, service) for sid, service in providers if sid == norm_source]
        if not providers and ext:
            providers = [(ext.pkg, ext)]
        if not providers:
            raise HTTPException(404, "Source introuvable ou désactivée")

    async def run(service):
        return await asyncio.wait_for(service.search_anime(q.strip()), timeout=12)

    responses = await asyncio.gather(*(run(service) for _, service in providers), return_exceptions=True)
    results, challenges, errors, seen = [], [], [], set()
    first_challenge = None
    for (sid, service), response in zip(providers, responses):
        if isinstance(response, VerificationRequired):
            first_challenge = first_challenge or response
            challenges.append({**response.to_dict(), "source": sid})
        elif isinstance(response, BaseException):
            logger.debug("Search source %s failed: %s", sid, response)
            errors.append({"source": sid, "domain": urlparse(service.base_url).hostname or '',
                           "message": "La source est momentanément inaccessible"})
        else:
            for item in response or []:
                item.source = sid
                key = (sid, item.url)
                if key not in seen:
                    seen.add(key)
                    results.append(item)
    if include_challenges is True:
        return {"results": results, "challenges": challenges, "errors": errors}
    if first_challenge:
        raise first_challenge
    return results

async def fetch_enriched_anime_detail(url: str, source: str = "french-manga") -> Optional[Dict[str, Any]]:
    """Récupère et enrichit la fiche complète d'un animé (TMDB, épisodes, favoris, progression)."""
    if not url or not is_safe_url(url):
        return None

    detected_source = detect_source_from_url(url, fallback=source)
    if detected_source != source:
        source = detected_source

    container_source = extension_service.get_container_source_by_id(source)
    if container_source:
        detail = await container_source.get_anime_detail(url)
    elif source == "animepahe":
        detail = await animepahe_service.get_anime_detail(url)
    elif source == "voir-anime":
        detail = await voiranime_service.get_anime_detail(url)
    else:
        detail = await scraping_service.get_anime_detail(url)

    # Repli automatique si résultats vides
    if not detail or not detail.episodes:
        if source not in ("animepahe",) and not container_source:
            alt_source = "voir-anime" if source != "voir-anime" else "french-manga"
            if alt_source == "voir-anime":
                alt_detail = await voiranime_service.get_anime_detail(url)
            else:
                alt_detail = await scraping_service.get_anime_detail(url)
            if alt_detail and alt_detail.episodes:
                detail = alt_detail
                source = alt_source

    if not detail:
        return None

    detail.source = source
    detail = await tmdb_service.enrich_anime_detail(detail)
    downloaded_set = library_service.get_downloaded_episodes_set(url)
    watched_set = library_service.get_watched_episodes_set(url)
    progress_by_episode = {
        (p.episodeNumber, p.version or ""): p
        for p in library_service.get_progress_for_anime(url)
    }
    fav = library_service.get_favorite(url)
    is_favorite = fav is not None
    auto_download = fav.autoDownload if fav else False

    episodes_data = []
    for ep in detail.episodes:
        num = ep.number
        version = ep.version or detail.version or ""
        progress = progress_by_episode.get((num, version))
        if progress is None:
            progress = progress_by_episode.get((num, ""))
        is_dl = bool(progress and progress.downloaded)
        is_watched = bool(progress and progress.watched)
        local_task = library_service.find_downloaded_episode(
            anime_name=detail.title,
            episode_number=num,
            version=ep.version or detail.version or "",
            episode_url=ep.downloadPageUrl or ep.playerUrl or "",
        )
        task_id = local_task.id if local_task else None
        ep_dict = ep.model_dump()
        ep_dict["version"] = version
        ep_dict["isDownloaded"] = is_dl or local_task is not None
        ep_dict["isWatched"] = is_watched
        ep_dict["downloadTaskId"] = task_id
        episodes_data.append(ep_dict)

    anime_dump = detail.model_dump()
    anime_dump["episodes"] = episodes_data

    return {
        "detail_obj": detail,
        "anime": anime_dump,
        "source": source,
        "isFavorite": is_favorite,
        "autoDownload": auto_download,
        "downloadedEpisodes": list(downloaded_set),
        "watchedEpisodes": list(watched_set),
        "totalEpisodes": len(episodes_data),
        "downloadedCount": sum(1 for e in episodes_data if e["isDownloaded"]),
        "watchedCount": sum(1 for e in episodes_data if e["isWatched"]),
    }

@router.get("/anime", response_class=HTMLResponse)
async def anime_detail(
    request: Request,
    url: str = Query(..., alias="url"),
    source: str = Query("french-manga", alias="source")
):
    logger.info("Anime detail requested [%s]: %s", source, url)
    if not is_safe_url(url):
        logger.warning("[anime_detail] SSRF blocked for URL: %s", url)
        favorites = library_service.get_all_favorites()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "URL d'animé invalide ou non sécurisée",
                "favorites": favorites,
                "results": None,
                "latestFrenchManga": [],
                "latestVoirAnime": [],
                "latestAnimePahe": [],
            }
        )

    res = await fetch_enriched_anime_detail(url, source)
    if not res:
        favorites = library_service.get_all_favorites()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "Impossible de charger cet anime ou source non supportée.",
                "favorites": favorites,
                "results": None,
                "latestFrenchManga": [],
                "latestVoirAnime": [],
                "latestAnimePahe": [],
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="anime-detail.html",
        context={
            "anime": res["detail_obj"],
            "source": res["source"],
            "isFavorite": res["isFavorite"],
            "autoDownload": res["autoDownload"],
            "downloadedEpisodes": set(res["downloadedEpisodes"]),
            "watchedEpisodes": set(res["watchedEpisodes"]),
        }
    )

@router.get("/api/anime/detail")
@router.get("/api/anime")
async def api_anime_detail(
    url: str = Query(..., alias="url"),
    source: str = Query("french-manga", alias="source")
):
    """Retourne la fiche anime complète avec épisodes et métadonnées en JSON pur."""
    if not is_safe_url(url):
        raise HTTPException(status_code=400, detail="URL d'animé invalide ou non sécurisée")
    res = await fetch_enriched_anime_detail(url, source)
    if not res:
        raise HTTPException(status_code=404, detail="Anime introuvable ou URL invalide")

    output = dict(res)
    output.pop("detail_obj", None)
    return {"success": True, **output}

@router.get("/api/home/feed")
async def api_home_feed():
    """
    Flux d'accueil consolidé pour le frontend SPA :
    - Dernières sorties des sources natives et extensions
    - Favoris de l'utilisateur
    - Historique récent
    - Extensions actives
    """
    enabled_extensions = extension_service.get_enabled_container_sources()

    async def _safe_fetch(coro, default=None, timeout: float = 6.0):
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[home_feed] Source fetch error: %s", e)
            return default if default is not None else []

    fm_task = _safe_fetch(scraping_service.get_latest_releases())
    va_task = _safe_fetch(voiranime_service.get_latest_releases())
    ap_task = _safe_fetch(animepahe_service.get_latest_releases())

    ext_tasks = []
    for ext in enabled_extensions[:4]:
        if hasattr(ext, "get_latest_releases"):
            ext_tasks.append(_safe_fetch(ext.get_latest_releases(), default=[]))
        else:
            ext_tasks.append(asyncio.sleep(0, result=[]))

    all_res = await asyncio.gather(fm_task, va_task, ap_task, *ext_tasks, return_exceptions=True)
    latest_fm = all_res[0] if not isinstance(all_res[0], Exception) else []
    latest_va = all_res[1] if not isinstance(all_res[1], Exception) else []
    latest_ap = all_res[2] if not isinstance(all_res[2], Exception) else []

    ext_releases = {}
    for idx, ext in enumerate(enabled_extensions[:4]):
        res = all_res[3 + idx]
        if not isinstance(res, Exception) and res:
            ext_releases[ext.pkg] = {
                "name": ext.name,
                "releases": [r.model_dump() for r in res[:24]],
            }

    favorites = [f.to_dict() for f in library_service.get_all_favorites()]
    history_items = [t.to_task().to_dict() for t in library_service.get_history()[:15]]

    releases_map = {
        "french-manga": [r.model_dump() for r in latest_fm],
        "voir-anime": [r.model_dump() for r in latest_va],
        "animepahe": [r.model_dump() for r in latest_ap],
    }
    for pkg, ext_info in ext_releases.items():
        releases_map[pkg] = ext_info["releases"]

    return {
        "success": True,
        "latestReleases": releases_map,
        "latestFrenchManga": [r.model_dump() for r in latest_fm],
        "latestVoirAnime": [r.model_dump() for r in latest_va],
        "latestAnimePahe": [r.model_dump() for r in latest_ap],
        "extensionsReleases": ext_releases,
        "favorites": favorites,
        "recentHistory": history_items,
        "enabledExtensions": [
            {
                "id": ext.pkg,
                "pkg": ext.pkg,
                "name": ext.name,
                "lang": getattr(ext, "lang", "fr"),
                "baseUrl": getattr(ext, "base_url", ""),
            }
            for ext in enabled_extensions
        ],
    }

@router.get("/api/sources/{source_id}/feed")
async def api_source_feed(source_id: str):
    """Retourne les dernières sorties / le catalogue d'une source spécifique."""
    s_clean = source_id.lower().strip()
    if s_clean == "french-manga":
        releases = await scraping_service.get_latest_releases()
        return {"success": True, "source": "french-manga", "releases": [r.model_dump() for r in releases]}
    elif s_clean == "voir-anime":
        releases = await voiranime_service.get_latest_releases()
        return {"success": True, "source": "voir-anime", "releases": [r.model_dump() for r in releases]}
    elif s_clean == "animepahe":
        releases = await animepahe_service.get_latest_releases()
        return {"success": True, "source": "animepahe", "releases": [r.model_dump() for r in releases]}

    container = extension_service.get_container_source_by_id(source_id)
    if container and hasattr(container, "get_latest_releases"):
        releases = await container.get_latest_releases()
        return {"success": True, "source": container.name, "releases": [r.model_dump() for r in releases]}

    return JSONResponse(status_code=404, content={"success": False, "error": f"Source '{source_id}' introuvable"})
