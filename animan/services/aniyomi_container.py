import asyncio
import logging
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, quote_plus, urlparse
from bs4 import BeautifulSoup
import httpx

from animan.config import settings
from animan.models.anime import AnimeResult, AnimeDetail, Episode
from animan.security import is_safe_url
from animan.services.aniyomi_dex_parser import SourceRecipe
from animan.services.proxy_service import proxy_service

logger = logging.getLogger("animan.container")


def _clean_selector(sel: Optional[str]) -> str:
    if not sel:
        return ""
    # Nettoie les virgules orphelines ou espaces en fin de chaîne
    return sel.strip().rstrip(",; ").strip()

def _safe_select(parent: Any, selector: str) -> List[Any]:
    s = _clean_selector(selector)
    if not s:
        return []
    try:
        return parent.select(s)
    except Exception:
        # Si le sélecteur composé échoue (syntaxe invalide), essayer chaque sous-sélecteur séparé par virgule
        valid: List[Any] = []
        for part in s.split(","):
            p = _clean_selector(part)
            if p:
                try:
                    for el in parent.select(p):
                        if el not in valid:
                            valid.append(el)
                except Exception:
                    pass
        return valid

def _safe_select_one(parent: Any, selector: str) -> Optional[Any]:
    s = _clean_selector(selector)
    if not s:
        return None
    try:
        return parent.select_one(s)
    except Exception:
        for part in s.split(","):
            p = _clean_selector(part)
            if p:
                try:
                    res = parent.select_one(p)
                    if res:
                        return res
                except Exception:
                    pass
        return None


class AniyomiContainerSource:
    """Conteneur d'exécution dynamique qui exécute une SourceRecipe extraite d'une extension Aniyomi."""

    def __init__(self, recipe: SourceRecipe):
        self.recipe = recipe
        self.name = recipe.name or recipe.pkg.split(".")[-1].capitalize()
        self.base_url = recipe.base_url.rstrip("/")
        self.pkg = recipe.pkg
        self.lang = recipe.lang
        self.source_id = recipe.pkg  # Identifiant unique de la source

    def _get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        return {
            "User-Agent": settings.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer or (self.base_url + "/"),
        }

    async def _fetch_html(self, url: str, method: str = "GET", data: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> str:
        """Effectue une requête HTTP sécurisée vers la source."""
        headers = self._get_headers(referer=self.base_url + "/")
        try:
            proxy = proxy_service.get_active_proxy()
            # Essai curl_cffi pour bypasser Cloudflare basique si disponible
            try:
                from curl_cffi.requests import AsyncSession
                async with AsyncSession(impersonate="chrome124", proxy=proxy) as session:
                    if method.upper() == "POST":
                        resp = await session.post(url, data=data, headers=headers, timeout=timeout, allow_redirects=False)
                        if resp.status_code in (301, 302, 307, 308) and "location" in resp.headers:
                            redir_url = urljoin(url, resp.headers["location"])
                            p = urlparse(redir_url)
                            if p.netloc:
                                self.base_url = f"{p.scheme}://{p.netloc}"
                            resp = await session.post(redir_url, data=data, headers=self._get_headers(referer=self.base_url + "/"), timeout=timeout)
                    else:
                        resp = await session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
                    if resp.status_code == 200:
                        return resp.text
            except Exception:
                pass

            async with httpx.AsyncClient(timeout=timeout, verify=settings.SSL_VERIFY, follow_redirects=False, proxy=proxy) as client:
                if method.upper() == "POST":
                    resp = await client.post(url, data=data, headers=headers)
                    # Si redirection (ex: vostfree.ws -> ipv4.vostfree.ws), conserver POST vers la nouvelle adresse
                    if resp.is_redirect and resp.headers.get("location"):
                        redirect_url = urljoin(url, resp.headers["location"])
                        parsed_redirect = urlparse(redirect_url)
                        if parsed_redirect.netloc:
                            self.base_url = f"{parsed_redirect.scheme}://{parsed_redirect.netloc}"
                        resp = await client.post(redirect_url, data=data, headers=self._get_headers(referer=self.base_url + "/"))
                else:
                    resp = await client.get(url, headers=headers, follow_redirects=True)
                if resp.status_code == 200:
                    return resp.text
        except Exception as e:
            logger.debug("[container:%s] Erreur fetch %s: %s", self.name, url, e)
        return ""

    # -------------------------------------------------------------------------
    # Recherche
    # -------------------------------------------------------------------------

    async def search_anime(self, query: str) -> List[AnimeResult]:
        clean_q = query.strip()
        if not clean_q or not self.base_url:
            return []

        logger.info("[container:%s] Recherche: '%s'", self.name, clean_q)
        results: List[AnimeResult] = []

        method = self.recipe.search_method or "GET"
        post_data = None
        if method == "POST":
            target_url = urljoin(self.base_url, self.recipe.search_request_path or "/index.php?do=search")
            post_data = {
                "do": "search",
                "subaction": "search",
                "search_start": "1",
                "story": clean_q,
                "full_search": "0",
                "result_from": "1"
            }
        else:
            path_tmpl = self.recipe.search_request_path or f"/?{self.recipe.search_query_param or 's'}={{query}}"
            if "{query}" in path_tmpl:
                rel_path = path_tmpl.replace("{query}", quote_plus(clean_q))
            else:
                sep = "&" if "?" in path_tmpl else "?"
                param = self.recipe.search_query_param or "s"
                rel_path = f"{path_tmpl}{sep}{param}={quote_plus(clean_q)}"
            target_url = urljoin(self.base_url, rel_path)

        html = await self._fetch_html(target_url, method=method, data=post_data)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        selector = self.recipe.search_selector or self.recipe.popular_selector or ".search-result, .movie-poster, .anime-card, article, .item"
        items = _safe_select(soup, selector)

        # Si le sélecteur strict n'a rien trouvé, repli heuristique étendu
        if not items:
            fallbacks = [
                "#list_catalog > div", "#list_catalog > div a", ".catalog-card",
                "#containerAjoutsAnimes > div", "div.ml-item", ".film_list article",
                "div#archive-content > article", ".search-page .result-item",
                ".c-tabs-item__content", "div.movie-poster", ".search-result",
                "article", ".short-story", ".item"
            ]
            for fallback_sel in fallbacks:
                items = _safe_select(soup, fallback_sel)
                if items:
                    break

        seen_hrefs = set()
        for it in items[:30]:
            link_el = _safe_select_one(it, self.recipe.item_link_selector or "a[href]") or (it if it.name == "a" else None)
            if not link_el or not link_el.get("href"):
                continue

            href = urljoin(self.base_url, link_el.get("href"))
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            img_el = _safe_select_one(it, self.recipe.item_thumb_selector or "img[src], img[data-src], img")
            img_url = ""
            if img_el:
                raw_img = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src", "")
                if raw_img:
                    img_url = urljoin(self.base_url, raw_img)

            title = ""
            title_el = _safe_select_one(it, self.recipe.item_title_selector or "h2, h3, .title, .movie-title, .card-title")
            if title_el:
                title = title_el.get_text().strip()
            if not title and link_el.get("title"):
                title = link_el.get("title").strip()
            if not title and link_el.get("aria-label"):
                title = link_el.get("aria-label").strip()
            if not title and img_el and img_el.get("alt"):
                title = img_el.get("alt").strip()
            if not title:
                title = link_el.get_text().strip()

            if title:
                results.append(
                    AnimeResult(
                        id=str(hash(href))[-8:],
                        title=title,
                        imageUrl=img_url,
                        url=href,
                        version=self.lang.upper(),
                        type="Anime",
                        episodeInfo=self.name,
                        source=self.source_id,
                    )
                )

        logger.info("[container:%s] Trouvé %d résultat(s)", self.name, len(results))
        return results

    # -------------------------------------------------------------------------
    # Dernières sorties
    # -------------------------------------------------------------------------

    async def get_latest_releases(self) -> List[AnimeResult]:
        if not self.base_url:
            return []

        rel_path = self.recipe.latest_request_path or self.recipe.popular_request_path or "/"
        target_url = urljoin(self.base_url, rel_path)
        html = await self._fetch_html(target_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        selector = self.recipe.latest_selector or self.recipe.popular_selector or ".movie-poster, .c-tabs-item__content, article"
        items = _safe_select(soup, selector)

        results: List[AnimeResult] = []
        for it in items[:18]:
            link_el = _safe_select_one(it, "a[href]") or (it if it.name == "a" else None)
            if not link_el or not link_el.get("href"):
                continue
            href = urljoin(self.base_url, link_el.get("href"))
            title_el = _safe_select_one(it, "h2, h3, .title, .movie-title") or link_el
            title = title_el.get_text().strip() if title_el else ""
            img_el = _safe_select_one(it, "img[src], img[data-src]")
            img_url = urljoin(self.base_url, img_el.get("src") or img_el.get("data-src", "")) if img_el else ""

            if title:
                results.append(
                    AnimeResult(
                        id=str(hash(href))[-8:],
                        title=title,
                        imageUrl=img_url,
                        url=href,
                        version=self.lang.upper(),
                        type="Anime",
                        episodeInfo="Récents",
                        source=self.source_id,
                    )
                )
        return results

    # -------------------------------------------------------------------------
    # Détails & Épisodes
    # -------------------------------------------------------------------------

    async def get_anime_detail(self, anime_url: str) -> Optional[AnimeDetail]:
        if not is_safe_url(anime_url):
            return None

        html = await self._fetch_html(anime_url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # Titre
        title_el = _safe_select_one(soup, self.recipe.details_title_selector or "h1.title, h1.entry-title, h1, .movie-title")
        title = title_el.get_text().strip() if title_el else (soup.title.string if soup.title else self.name)

        # Synopsis
        syn_el = _safe_select_one(soup, self.recipe.details_synopsis_selector or ".synopsis, .description, .entry-content p, #dle-content .full-text")
        synopsis = syn_el.get_text().strip() if syn_el else ""

        # Affiche
        img_el = _safe_select_one(soup, self.recipe.details_thumb_selector or ".poster img, .fposter img, meta[property='og:image']")
        img_url = ""
        if img_el:
            img_src = img_el.get("content") if img_el.name == "meta" else (img_el.get("src") or img_el.get("data-src"))
            if img_src:
                img_url = urljoin(self.base_url, img_src)

        # Genres
        genres = [g.get_text().strip() for g in _safe_select(soup, ".genre a, .genres a, a[href*='/genre/']") if g.get_text().strip()]

        # Épisodes
        episodes: List[Episode] = []
        ep_selector = self.recipe.episode_list_selector or "li.wp-manga-chapter, select.new_player_selector option, .episodes a, a[href*='episode']"
        ep_items = _safe_select(soup, ep_selector)

        ep_idx = 1
        for ep_el in ep_items:
            href = ""
            ep_title = ep_el.get_text().strip()
            if ep_el.name == "option":
                val = ep_el.get("value") or ""
                # Si option a une url ou un index d'épisode
                if val.startswith("http") or val.startswith("/"):
                    href = urljoin(self.base_url, val)
                else:
                    href = f"{anime_url}?episode={val or ep_idx}"
            else:
                a_tag = ep_el if ep_el.name == "a" else ep_el.select_one("a[href]")
                if a_tag and a_tag.get("href"):
                    href = urljoin(self.base_url, a_tag.get("href"))

            if not href:
                continue

            # Numéro d'épisode extrait par regex
            num_match = re.search(r"(?:ep|épisode|episode|ch)[\s\-_]*(\d+)", ep_title, re.IGNORECASE)
            ep_num = int(num_match.group(1)) if num_match else ep_idx

            episodes.append(
                Episode(
                    number=ep_num,
                    title=ep_title or f"Épisode {ep_num}",
                    version=self.lang.upper(),
                    downloadPageUrl=href,
                    playerUrl=href,
                    thumbnailUrl=img_url,
                )
            )
            ep_idx += 1

        # Extraction spécifique Anime-Sama via panneauAnime et episodes.js
        if not episodes and ("anime-sama" in self.base_url or "animesama" in (self.pkg or "").lower()):
            panneaux = re.findall(r'panneauAnime\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)', html)
            valid_panneaux = [(p_title, p_rel) for p_title, p_rel in panneaux if p_rel != "url" and not p_rel.startswith("http")]
            if not valid_panneaux:
                valid_panneaux = [("Saison 1 (VOSTFR)", "saison1/vostfr")]
            for p_title, p_rel in valid_panneaux:
                p_url = urljoin(anime_url.rstrip("/") + "/", p_rel.rstrip("/") + "/episodes.js")
                js_content = await self._fetch_html(p_url)
                if js_content and "eps" in js_content:
                    arr_matches = re.findall(r"var\s+eps\d*\s*=\s*\[(.*?)\];", js_content, re.DOTALL)
                    if arr_matches:
                        ep_urls = re.findall(r"['\"]([^'\"]+)['\"]", arr_matches[0])
                        for i, ep_u in enumerate(ep_urls, 1):
                            episodes.append(
                                Episode(
                                    number=i,
                                    title=f"{p_title} - Épisode {i}",
                                    version=self.lang.upper(),
                                    downloadPageUrl=ep_u,
                                    playerUrl=ep_u,
                                    thumbnailUrl=img_url,
                                )
                            )
                        if episodes:
                            break

        # Si aucun épisode trouvé via sélecteur, créer un épisode 1 par défaut sur la page
        if not episodes:
            episodes.append(
                Episode(
                    number=1,
                    title="Épisode 1",
                    url=anime_url,
                    version=self.lang.upper(),
                    downloadPageUrl=anime_url,
                    playerUrl=anime_url,
                    thumbnailUrl=img_url,
                    animeId=str(hash(anime_url))[-8:],
                )
            )

        return AnimeDetail(
            id=str(hash(anime_url))[-8:],
            title=title,
            imageUrl=img_url,
            synopsis=synopsis,
            genres=genres[:6],
            episodes=episodes,
            source=self.source_id,
            url=anime_url,
            version=self.lang.upper(),
        )

    # -------------------------------------------------------------------------
    # Sources Vidéo & Hébergeurs
    # -------------------------------------------------------------------------

    async def get_episode_sources(self, play_url: str) -> List[Dict[str, Any]]:
        if not is_safe_url(play_url):
            return []

        html = await self._fetch_html(play_url)
        if not html:
            return []

        sources: List[Dict[str, Any]] = []

        # 1. Détection des balises iframe vidéo
        regex = self.recipe.video_iframe_regex or r'<iframe[^>]*\ssrc=["\']([^"\']+)["\']'
        iframes = re.findall(regex, html, re.IGNORECASE)

        # 2. Détection d'hébergeurs courants (Vidmoly, Streamtape, Uqload, Sendvid, Sibnet, Voe, etc.)
        for iframe_url in set(iframes):
            if iframe_url.startswith("//"):
                iframe_url = "https:" + iframe_url
            elif not iframe_url.startswith("http"):
                iframe_url = urljoin(self.base_url, iframe_url)

            # Identification du nom de l'hébergeur
            host_name = "Lecteur Externe"
            domain = urlparse(iframe_url).netloc.lower()
            if "vidmoly" in domain:
                host_name = "Vidmoly"
            elif "streamtape" in domain or "stape" in domain:
                host_name = "Streamtape"
            elif "uqload" in domain:
                host_name = "Uqload"
            elif "sendvid" in domain:
                host_name = "Sendvid"
            elif "sibnet" in domain:
                host_name = "Sibnet"
            elif "voe" in domain:
                host_name = "VOE"
            elif "kwik" in domain:
                host_name = "Kwik"
            else:
                host_name = domain.replace("www.", "").split(".")[0].capitalize()

            sources.append({
                "name": f"{self.name} - {host_name}",
                "url": iframe_url,
                "quality": "HD",
                "format": "iframe",
            })

        return sources
