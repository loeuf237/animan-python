from animan.services.source_http import source_http, VerificationRequired
import html
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
import httpx

from animan.models.anime import AnimeDetail, AnimeResult, Episode
from animan.services.container_adapters.base import BaseSourceAdapter
from animan.services.proxy_service import proxy_service

logger = logging.getLogger(__name__)

class AnimeSamaAdapter(BaseSourceAdapter):
    name = "Anime-Sama"
    pkg_prefixes = ["eu.kanade.tachiyomi.animeextension.fr.animesama", "animesama"]
    domains = ["anime-sama.fr", "anime-sama.me", "anime-sama.to"]

    async def _fetch_text(self, url: str, container: Any) -> str:
        if hasattr(container, "_fetch_html"):
            try:
                res = await container._fetch_html(url)
                if res:
                    return res
            except VerificationRequired:
                raise
            except Exception as e:
                logger.debug("[animesama_adapter] container._fetch_html error on %s: %s", url, e)

        try:
            proxy = proxy_service.get_proxy()
            headers = {
                "User-Agent": proxy_service.get_user_agent(),
                "Referer": getattr(container, "base_url", "https://anime-sama.fr/") + "/",
            }
            async with source_http.async_client(timeout=12.0, proxy=proxy, headers=headers, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[animesama_adapter] Erreur fetch %s: %s", url, e)
        return ""

    async def search_anime(self, query: str, container: Any) -> List[AnimeResult]:
        clean_q = query.strip()
        if not clean_q:
            return []

        base_url = getattr(container, "base_url", "https://anime-sama.fr")
        req_path = getattr(container.recipe, "search_request_path", None) or "/catalogue/?search={query}"
        search_url = urljoin(base_url, req_path.replace("{query}", quote_plus(clean_q)))

        page_html = await self._fetch_text(search_url, container)
        if not page_html:
            catalogue_url = urljoin(base_url, "/catalogue/")
            page_html = await self._fetch_text(catalogue_url, container)
        if not page_html:
            page_html = await self._fetch_text(base_url, container)

        if not page_html:
            return []

        soup = BeautifulSoup(page_html, "html.parser")
        results: List[AnimeResult] = []
        q_lower = clean_q.lower()

        sel = getattr(container.recipe, "search_selector", None) or "#list_catalog > div, .catalog-card, .carte, .card, div[class*='anime']"
        cards = soup.select(sel)
        if not cards:
            cards = soup.find_all("a", href=re.compile(r"/catalogue/[^/]+/?$"))

        seen_hrefs = set()
        for card in cards:
            link = card if card.name == "a" else card.find("a", href=True)
            if not link:
                continue

            href = urljoin(base_url, link.get("href", ""))
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            img_el = card.find("img")
            img_alt = img_el.get("alt", "").strip() if img_el else ""
            img_url = ""
            if img_el:
                img_url = urljoin(base_url, img_el.get("src") or img_el.get("data-src", ""))

            title_el = card.find(["h1", "h2", "h3", "h4", "p", "span"], class_=re.compile(r"titre|title|name|card-title", re.I))
            title = ""
            if title_el:
                title = title_el.get_text().strip()
            if not title and img_alt:
                title = img_alt
            if not title and link and link.get_text().strip():
                title = link.get_text().strip()
            if not title:
                title = href.rstrip("/").split("/")[-1].replace("-", " ").capitalize()

            is_search_page = "?search=" in search_url or "/search" in search_url
            if is_search_page or (q_lower in title.lower() or q_lower in href.lower()):
                results.append(
                    AnimeResult(
                        id=str(hash(href))[-8:],
                        title=title,
                        imageUrl=img_url,
                        url=href,
                        version="VOSTFR",
                        type="Anime",
                        episodeInfo="Anime-Sama",
                        source=container.source_id,
                    )
                )
                if len(results) >= 40:
                    break

        logger.info("[animesama_adapter] Trouvé %d résultat(s) pour '%s'", len(results), clean_q)
        return results

    async def get_latest_releases(self, container: Any) -> List[AnimeResult]:
        base_url = getattr(container, "base_url", "https://anime-sama.fr")
        html = await self._fetch_text(base_url, container)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[AnimeResult] = []
        seen_hrefs = set()

        cards = soup.select(".catalog-card, .carte, .card, div[class*='recent'], div[class*='sortie']")
        for card in cards[:24]:
            link = card if card.name == "a" else card.find("a", href=True)
            if not link:
                continue

            href = urljoin(base_url, link.get("href", ""))
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            title_el = card.find(["h1", "h2", "h3", "h4", "p"], class_=re.compile(r"titre|title", re.I)) or link
            title = title_el.get_text().strip() if title_el else href.rstrip("/").split("/")[-1].replace("-", " ").capitalize()
            img_el = card.find("img")
            img_url = ""
            if img_el:
                img_url = urljoin(base_url, img_el.get("src") or img_el.get("data-src", ""))

            results.append(
                AnimeResult(
                    id=str(hash(href))[-8:],
                    title=title,
                    imageUrl=img_url,
                    url=href,
                    version="VOSTFR",
                    type="Anime",
                    episodeInfo="Récents",
                    source=container.source_id,
                )
            )

        return results

    def _extract_js_player_arrays(self, html_content: str) -> Dict[str, List[str]]:
        player_arrays: Dict[str, List[str]] = {}
        array_matches = re.finditer(
            r"(?:var|let|const)\s+(eps[a-zA-Z0-9_-]*)\s*=\s*\[(.*?)\];",
            html_content,
            re.DOTALL,
        )
        for m in array_matches:
            var_name = m.group(1)
            raw_elements = m.group(2)
            urls = re.findall(r"['\"](https?://[^'\"]+)['\"]", raw_elements)
            if urls:
                player_arrays[var_name] = urls

        return player_arrays

    async def get_anime_detail(self, anime_url: str, container: Any) -> Optional[AnimeDetail]:
        html = await self._fetch_text(anime_url, container)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        base_url = getattr(container, "base_url", "https://anime-sama.fr")

        # Titre
        title_el = soup.find(["h1", "h2"], id=re.compile(r"titre|title", re.I)) or soup.find("h1") or soup.find("title")
        title = ""
        if title_el:
            title = title_el.get_text().strip()
            # Nettoyer ":: Anime-Sama"
            title = re.sub(r"::\s*Anime-Sama.*", "", title, flags=re.IGNORECASE).strip()
        if not title:
            title = anime_url.rstrip("/").split("/")[-1].replace("-", " ").capitalize()

        # Image de couverture
        img_el = soup.find("img", id=re.compile(r"cover|poster", re.I)) or soup.find("img", class_=re.compile(r"cover|poster", re.I))
        img_url = urljoin(base_url, img_el.get("src") or img_el.get("data-src", "")) if img_el else ""

        # Synopsis
        synopsis_el = soup.find("p", id=re.compile(r"synopsis", re.I)) or soup.find("div", class_=re.compile(r"synopsis", re.I))
        synopsis = synopsis_el.get_text().strip() if synopsis_el else ""

        # Genres
        genres = []
        for g_el in soup.find_all("a", href=re.compile(r"/genre/")):
            gt = g_el.get_text().strip()
            if gt and gt not in genres:
                genres.append(gt)

        # Extraction des tableaux JS d'épisodes
        player_arrays = self._extract_js_player_arrays(html)

        # Si pas de tableaux dans la page principale, chercher les sous-pages de saison ou episodes.js
        if not player_arrays:
            # 1. Sous-pages de saison via panneauAnime
            saison_subpaths = re.findall(r'panneauAnime\([^,]+,\s*["\']([^"\']+)["\']\)', html)
            for sp in saison_subpaths:
                sp_clean = sp.strip().strip("/")
                if sp_clean and sp_clean != "url":
                    s_url = urljoin(anime_url if anime_url.endswith("/") else anime_url + "/", f"{sp_clean}/")
                    s_html = await self._fetch_text(s_url, container)
                    if s_html:
                        p_arr = self._extract_js_player_arrays(s_html)
                        if p_arr:
                            player_arrays.update(p_arr)
                            break
                        # Chercher episodes.js dans la sous-page de saison
                        ep_js_url = urljoin(s_url, "episodes.js")
                        ep_js = await self._fetch_text(ep_js_url, container)
                        if ep_js:
                            p_arr = self._extract_js_player_arrays(ep_js)
                            if p_arr:
                                player_arrays.update(p_arr)
                                break

            # 2. Chercher episodes.js direct
            if not player_arrays:
                ep_js_url = urljoin(anime_url if anime_url.endswith("/") else anime_url + "/", "episodes.js")
                ep_js = await self._fetch_text(ep_js_url, container)
                if ep_js:
                    p_arr = self._extract_js_player_arrays(ep_js)
                    if p_arr:
                        player_arrays.update(p_arr)

        episodes: List[Episode] = []

        if player_arrays:
            from animan.services.extractors import extractor_registry
            import json

            max_count = max(len(arr) for arr in player_arrays.values())
            for idx in range(max_count):
                ep_num = idx + 1
                servers_map: Dict[str, str] = {}
                best_url = ""
                for p_name, urls in player_arrays.items():
                    if idx < len(urls) and urls[idx]:
                        u = urls[idx].strip()
                        if not best_url:
                            best_url = u
                        ext = extractor_registry.find_extractor(u)
                        s_name = ext.name if ext else (
                            "Sibnet" if "sibnet" in u.lower() else
                            "Vidmoly" if any(k in u.lower() for k in ["vidmoly", "ansembed", "voembed"]) else
                            "Sendvid" if "sendvid" in u.lower() else p_name
                        )
                        if s_name not in servers_map:
                            servers_map[s_name] = u

                ep_url = best_url or anime_url
                if len(servers_map) > 1:
                    ep_url = f"{best_url}#servers={quote_plus(json.dumps(servers_map))}"

                episodes.append(
                    Episode(
                        number=ep_num,
                        title=f"Épisode {ep_num:02d}",
                        downloadPageUrl=ep_url,
                        playerUrl=best_url or anime_url,
                        thumbnailUrl=img_url,
                        version="VOSTFR",
                    )
                )

        if not episodes:
            episodes = [
                Episode(
                    number=1,
                    title="Épisode 01",
                    downloadPageUrl=anime_url,
                    playerUrl=anime_url,
                    thumbnailUrl=img_url,
                    version="VOSTFR",
                )
            ]

        return AnimeDetail(
            title=title,
            imageUrl=img_url,
            synopsis=synopsis,
            genres=genres,
            episodes=episodes,
            source=container.source_id,
            url=anime_url,
            version="VOSTFR",
        )

    async def get_episode_sources(self, play_url: str, container: Any) -> List[Dict[str, Any]]:
        from animan.services.extractors import extractor_registry
        import json
        from urllib.parse import unquote_plus

        # Si des serveurs alternatifs sont encodés dans le hash fragment
        if "#servers=" in play_url:
            base_part, _, srv_raw = play_url.partition("#servers=")
            try:
                srv_dict = json.loads(unquote_plus(srv_raw))
                sources: List[Dict[str, Any]] = []
                for s_name, s_url in srv_dict.items():
                    ext = extractor_registry.find_extractor(s_url)
                    real_srv = ext.name if ext else s_name
                    sources.append({
                        "name": f"{container.name} - {real_srv}",
                        "server": real_srv,
                        "url": s_url,
                        "quality": "HD",
                        "format": "embed",
                    })
                if sources:
                    return sources
            except VerificationRequired:
                raise
            except Exception as e:
                logger.debug("[animesama_adapter] Error decoding servers fragment: %s", e)

        clean_url = play_url.split("#")[0].strip()
        extractor = extractor_registry.find_extractor(clean_url)
        if extractor:
            return [{
                "name": f"{container.name} - {extractor.name}",
                "server": extractor.name,
                "url": clean_url,
                "quality": "HD",
                "format": "embed",
            }]

        return [{
            "name": f"{container.name} - Lecteur",
            "server": "AnimeSama",
            "url": clean_url,
            "quality": "HD",
            "format": "embed",
        }]
