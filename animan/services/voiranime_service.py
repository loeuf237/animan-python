import asyncio
import json
import logging
import re
import time
import urllib.parse
from typing import List, Optional, Dict, Tuple
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from animan.config import settings
from animan.models.anime import AnimeResult, AnimeDetail, Episode
from animan.services.proxy_service import proxy_service

logger = logging.getLogger("animan.voiranime")

class VoirAnimeScrapingService:
    def __init__(self):
        self.base_url = settings.VOIR_ANIME_URL
        self.default_server = settings.VOIRANIME_DEFAULT_SERVER
        self.latest_cache: List[AnimeResult] = []
        self.last_cache_time: float = 0.0

    def _get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        return {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": referer or (self.base_url + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _get_client(self, follow_redirects: bool = True, referer: Optional[str] = None) -> httpx.Client:
        headers = self._get_headers(referer)
        proxy = proxy_service.get_random_proxy()
        return httpx.Client(
            headers=headers,
            proxy=proxy,
            timeout=httpx.Timeout(settings.READ_TIMEOUT, connect=settings.CONNECTION_TIMEOUT),
            follow_redirects=follow_redirects,
            verify=False,
        )

    def _get_async_client(self, follow_redirects: bool = True, referer: Optional[str] = None) -> httpx.AsyncClient:
        headers = self._get_headers(referer)
        proxy = proxy_service.get_random_proxy()
        return httpx.AsyncClient(
            headers=headers,
            proxy=proxy,
            timeout=httpx.Timeout(settings.READ_TIMEOUT, connect=settings.CONNECTION_TIMEOUT),
            follow_redirects=follow_redirects,
            verify=False,
        )

    async def get_latest_releases(self) -> List[AnimeResult]:
        now = time.time()
        if not self.latest_cache or (now - self.last_cache_time > 15 * 60):
            await self.refresh_cache()
        return list(self.latest_cache)

    async def refresh_cache(self):
        try:
            logger.info("[voir-anime] Chargement des dernières sorties depuis %s", self.base_url)
            async with self._get_async_client() as client:
                resp = await client.get(self.base_url)
                if resp.status_code == 200:
                    results = self.parse_cards(resp.text)
                    if results:
                        self.latest_cache = results
                        self.last_cache_time = time.time()
                        logger.info("[voir-anime] Cache mis à jour (%d animés)", len(self.latest_cache))
        except Exception as e:
            logger.error("[voir-anime] Erreur mise à jour cache: %s", e)

    def parse_asp_html(self, html: str, default_version: str = "VOSTFR") -> List[AnimeResult]:
        if not html:
            return []
        if "___ASPSTART_HTML___" in html:
            html = html.split("___ASPSTART_HTML___")[1].split("___ASPEND_HTML___")[0]
        soup = BeautifulSoup(html, "html.parser")
        results: List[AnimeResult] = []

        for rank, item in enumerate(soup.select(".item")):
            try:
                title_el = item.select_one("h3 a.asp_res_url, h3, a.asp_res_url")
                if not title_el:
                    continue
                # Supprimer les éventuels spans d'overlap générés par ASP
                for span in title_el.select(".overlap"):
                    span.decompose()
                title = title_el.get_text().strip()
                if not title:
                    continue

                link = item.select_one("a.asp_res_url, a.asp_res_image_url, a")
                url = link.get("href", "").strip() if link else ""
                if not url:
                    continue
                if not url.startswith("http"):
                    url = urljoin(self.base_url, url)

                img = item.select_one(".asp_image img, img")
                image_url = (img.get("src") or img.get("data-src") or "").strip() if img else ""
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

                version = default_version
                if "(VF)" in title.upper() or "-vf/" in url.lower() or "/vf/" in url.lower():
                    version = "VF"
                elif "(VOSTFR)" in title.upper() or "-vostfr/" in url.lower():
                    version = "VOSTFR"

                m_id = re.search(r"/anime/([^/]+)/?", url)
                anime_id = m_id.group(1) if m_id else str(hash(url))[:8]

                anime_res = AnimeResult(
                    id=anime_id,
                    title=title,
                    imageUrl=image_url,
                    url=url,
                    version=version,
                    type="Anime",
                    episodeInfo="",
                )
                setattr(anime_res, "_asp_rank", rank)
                results.append(anime_res)
            except Exception as e:
                logger.debug("Erreur parsing item ASP: %s", e)
        return results

    async def search_via_asp(self, query: str) -> List[AnimeResult]:
        user_wants_vf = bool(re.search(r"\bvf\b", query, re.IGNORECASE))
        user_wants_vostfr = bool(re.search(r"\bvostfr\b", query, re.IGNORECASE))
        q_clean = re.sub(r"\b(vf|vostfr)\b", "", query, flags=re.IGNORECASE).strip() or query
        q_lower = q_clean.lower()

        options_str = urllib.parse.urlencode([
            ("current_page_id", "15"),
            ("qtranslate_lang", "0"),
            ("filters_changed", "0"),
            ("filters_initial", "1"),
            ("asp_gen[]", "title"),
            ("asp_gen[]", "content"),
            ("asp_gen[]", "excerpt"),
            ("aspf[vf__1]", "vf"),
        ])

        asp_endpoint = f"{self.base_url}/wp-admin/admin-ajax.php"
        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": f"{self.base_url}/",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(settings.READ_TIMEOUT, connect=settings.CONNECTION_TIMEOUT),
            follow_redirects=True,
            verify=False
        ) as client:
            async def fetch_asp(asid: int) -> str:
                try:
                    data = {
                        "action": "ajaxsearchpro_search",
                        "aspp": q_clean,
                        "asid": str(asid),
                        "asp_inst_id": f"{asid}_1",
                        "options": options_str,
                    }
                    resp = await client.post(asp_endpoint, data=data)
                    if resp.status_code == 200:
                        return resp.text
                except Exception as e:
                    logger.warning("[voir-anime] Erreur fetch ASP asid=%d: %s", asid, e)
                return ""

            # asid=2 pour instance VF, asid=3 pour instance VOSTFR
            resp_vf, resp_vostfr = await asyncio.gather(fetch_asp(2), fetch_asp(3))

        vf_items = self.parse_asp_html(resp_vf, default_version="VF")
        vostfr_items = self.parse_asp_html(resp_vostfr, default_version="VOSTFR")

        # Fusionner selon l'intention de l'utilisateur
        combined: List[AnimeResult] = []
        seen_urls = set()

        if user_wants_vf:
            order = vf_items + vostfr_items
        elif user_wants_vostfr:
            order = vostfr_items + vf_items
        else:
            # Si aucune version spécifiée : entrelacer VF et VOSTFR en respectant le rang natif du site
            order = []
            max_len = max(len(vf_items), len(vostfr_items))
            for i in range(max_len):
                if i < len(vf_items):
                    order.append(vf_items[i])
                if i < len(vostfr_items):
                    order.append(vostfr_items[i])

        for it in order:
            if it.url not in seen_urls:
                seen_urls.add(it.url)
                combined.append(it)

        # Tri intelligent par pertinence du titre tout en préservant le classement original d'Ajax Search Pro
        def sort_key(item: AnimeResult):
            cleaned = re.sub(r"\s*\((VF|VOSTFR)\)", "", item.title, flags=re.IGNORECASE).strip().lower()
            ver_pref = 0
            if user_wants_vf and item.version != "VF":
                ver_pref = 1
            elif user_wants_vostfr and item.version != "VOSTFR":
                ver_pref = 1

            if cleaned == q_lower:
                match_rank = 0
            elif cleaned.startswith(q_lower):
                match_rank = 1
            elif re.search(r"\b" + re.escape(q_lower) + r"\b", cleaned):
                match_rank = 2
            elif q_lower in cleaned:
                match_rank = 3
            else:
                match_rank = 4

            asp_rank = getattr(item, "_asp_rank", 999)
            return (ver_pref, match_rank, asp_rank)

        return sorted(combined, key=sort_key)

    async def search_anime(self, query: str) -> List[AnimeResult]:
        logger.info("[voir-anime] Recherche: '%s'", query)
        results: List[AnimeResult] = []
        try:
            # 1. Moteur officiel Ajax Search Pro (identique au moteur live du site voir-anime.to)
            results = await self.search_via_asp(query)
        except Exception as e:
            logger.error("[voir-anime] Erreur recherche ASP: %s", e)

        # 2. Fallback vers la recherche standard WordPress si ASP ne renvoie rien
        if not results:
            try:
                search_url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
                async with self._get_async_client() as client:
                    resp = await client.get(search_url)
                    if resp.status_code == 200:
                        results = self.parse_cards(resp.text)
                    if not results:
                        fallback_url = f"{self.base_url}/?s={query.replace(' ', '+')}"
                        resp2 = await client.get(fallback_url)
                        if resp2.status_code == 200:
                            results = self.parse_cards(resp2.text)
            except Exception as e:
                logger.error("[voir-anime] Erreur recherche fallback: %s", e)

        logger.info("[voir-anime] %d résultat(s) pour '%s'", len(results), query)
        return results

    def parse_cards(self, html: str) -> List[AnimeResult]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".page-item-detail, .c-tabs-item__content, .search-wrap .row, .page-listing-item, .flw-item")
        results: List[AnimeResult] = []
        seen_urls = set()

        for card in cards:
            try:
                link_el = card.select_one(".item-thumb a, .tab-thumb a, .post-title a, h3 a, h4 a, a.film-poster-ahref")
                if not link_el:
                    continue

                url = link_el.get("href", "").strip()
                if not url:
                    continue
                if not url.startswith("http"):
                    url = urljoin(self.base_url, url)

                # Si c'est un lien direct d'épisode, retrouver l'URL de la série si possible
                ep_match = re.search(r"^(.*/anime/[^/]+/).*$", url)
                if ep_match and url != ep_match.group(1):
                    main_link = card.select_one("a[href*='/anime/']:not([href*='-vostfr']):not([href*='-vf'])")
                    if main_link and main_link.get("href"):
                        m_href = main_link["href"]
                        url = m_href if m_href.startswith("http") else urljoin(self.base_url, m_href)
                    else:
                        url = ep_match.group(1)

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title_el = card.select_one(".post-title a, h3.h4 a, h3 a, h4 a, .item-title a, .dynamic-name")
                title = ""
                if title_el:
                    title = title_el.get_text().strip()
                if not title:
                    title = link_el.get("title", "").strip()
                if not title or title.upper() in ["VF", "VOSTFR"]:
                    title_attr = card.select_one("[title]")
                    if title_attr and title_attr.get("title"):
                        title = title_attr["title"].strip()

                if not title:
                    continue

                # Image / poster
                img = card.select_one("img")
                image_url = ""
                if img:
                    image_url = img.get("src", "") or img.get("data-src", "")
                    if not image_url and img.get("srcset"):
                        image_url = img["srcset"].split()[0]
                    if image_url and not image_url.startswith("http"):
                        image_url = urljoin(self.base_url, image_url)

                # Episode badge
                ep_el = card.select_one(".btn-link, .chapter-item, .chapter, .tick-eps, .latest-chap")
                ep_info = ""
                if ep_el:
                    ep_text = ep_el.get_text().strip()
                    ep_info = ep_text.split("\n")[0].strip()
                    if ep_info and not ep_info.lower().startswith("ep"):
                        ep_info = f"Ep {ep_info}"

                # Version
                version = "VOSTFR"
                vf_flag = card.select_one(".manga-vf-flag, .badge-vf")
                if vf_flag or "(vf)" in title.lower() or "-vf" in url.lower():
                    version = "VF"

                # ID
                m_id = re.search(r"/anime/([^/]+)/?", url)
                anime_id = m_id.group(1) if m_id else str(hash(url))[:8]

                results.append(
                    AnimeResult(
                        id=anime_id,
                        title=title,
                        imageUrl=image_url,
                        url=url,
                        version=version,
                        type="Anime",
                        episodeInfo=ep_info,
                    )
                )
            except Exception as e:
                logger.debug("Erreur parsing card voir-anime: %s", e)

        return results

    async def get_anime_detail(self, anime_url: str) -> Optional[AnimeDetail]:
        logger.info("[voir-anime] Détail anime: %s", anime_url)
        try:
            async with self._get_async_client() as client:
                resp = await client.get(anime_url)
                if resp.status_code != 200:
                    logger.warning("[voir-anime] HTTP %d pour %s", resp.status_code, anime_url)
                    return None

                soup = BeautifulSoup(resp.text, "html.parser")
                title_el = soup.select_one(".post-title h1, h1.entry-title, h2.film-name, h1")
                title = title_el.get_text().strip() if title_el else ""
                if not title and soup.title:
                    title = soup.title.string.split("|")[0].split("-")[0].strip()

                img = soup.select_one(".summary_image img, .film-poster img, img.img-responsive")
                image_url = ""
                if img:
                    image_url = img.get("src", "") or img.get("data-src", "")
                    if not image_url and img.get("srcset"):
                        image_url = img["srcset"].split()[0]
                    if image_url and not image_url.startswith("http"):
                        image_url = urljoin(self.base_url, image_url)

                syn_el = soup.select_one(".description-summary .summary__content, .description-summary, .film-description .text")
                synopsis = syn_el.get_text().strip() if syn_el else ""

                genres = [g.get_text().strip() for g in soup.select(".genres-content a, .item-list a[href*=genre]") if g.get_text().strip()]

                version = "VF" if ("(vf)" in title.lower() or "-vf" in anime_url.lower()) else "VOSTFR"

                episodes = await self.fetch_episodes(anime_url, soup, client)

                return AnimeDetail(
                    title=title,
                    imageUrl=image_url,
                    synopsis=synopsis,
                    genres=genres,
                    url=anime_url,
                    version=version,
                    episodes=episodes,
                )
        except Exception as e:
            logger.error("[voir-anime] Erreur détail anime: %s", e)
            return None

    def _parse_episode_number(self, title: str, url: str, fallback: int) -> int:
        # Pattern 1: format explicite dans le titre " - 11" ou "VOSTFR - 11"
        m = re.search(r"(?:VOSTFR|VF|\bEp|\bEpisode|\bÉpisode|-)\s*[:#-]?\s*(\d+)\b", title, re.IGNORECASE)
        if m:
            return int(m.group(1))
        # Pattern 2: slug d'URL (ex: "...-11-vostfr/")
        m_url = re.search(r"[-_](\d+)[-_](?:vostfr|vf)/?$", url, re.IGNORECASE)
        if m_url:
            return int(m_url.group(1))
        # Pattern 3: nombre en fin d'URL
        m_url_end = re.search(r"[-_](\d+)/?$", url)
        if m_url_end:
            return int(m_url_end.group(1))
        # Pattern 4: dernier nombre trouvé dans le titre
        nums = re.findall(r"\b\d+\b", title)
        if nums:
            return int(nums[-1])
        return fallback

    async def fetch_episodes(self, anime_url: str, soup: BeautifulSoup, client: Optional[httpx.AsyncClient] = None) -> List[Episode]:
        episodes: List[Episode] = []
        try:
            # 1. Sélecteur principal WordPress Madara
            ep_items = soup.select("li.wp-manga-chapter, .wp-manga-chapter, li.chapter-li")

            # 2. Fallback liens directs d'épisodes
            if not ep_items:
                ep_items = soup.select("a[href*='/anime/'][href*='-vostfr'], a[href*='/anime/'][href*='-vf'], .ep-item, a[href*=regarder]")

            seen = set()
            for idx, item in enumerate(ep_items, start=1):
                link = item if item.name == "a" else item.select_one("a")
                if not link or not link.get("href"):
                    continue

                ep_url = link["href"].strip()
                if not ep_url.startswith("http"):
                    ep_url = urljoin(self.base_url, ep_url)

                raw_title = link.get_text().strip()
                ep_num = self._parse_episode_number(raw_title, ep_url, fallback=idx)

                ep_version = "VF" if ("(vf)" in raw_title.lower() or "-vf" in ep_url.lower()) else "VOSTFR"
                clean_title = f"Épisode {ep_num}"
                if "film" in raw_title.lower():
                    clean_title = f"Film - {ep_num}"
                elif "oav" in raw_title.lower():
                    clean_title = f"OAV - {ep_num}"

                key = (ep_num, ep_version)
                if key in seen:
                    continue
                seen.add(key)

                episodes.append(
                    Episode(
                        number=ep_num,
                        title=clean_title,
                        playerUrl=ep_url,
                        downloadPageUrl=ep_url,
                        version=ep_version,
                    )
                )
        except Exception as e:
            logger.error("[voir-anime] fetch_episodes error: %s", e)

        # Trier en ordre chronologique ascendant (1, 2, ... N)
        episodes.sort(key=lambda x: (x.number, x.version))
        return episodes

    def get_episode_servers(self, episode_url: str) -> Dict[str, Any]:
        """Retourne rapidement la liste des serveurs disponibles pour un épisode sans résoudre les flux vidéo."""
        try:
            with self._get_client(follow_redirects=True, referer=self.base_url) as client:
                resp = client.get(episode_url)
                if resp.status_code != 200:
                    return {"servers": ["myTV"], "defaultServer": self.default_server}
                sources = self._parse_episode_sources(resp.text)
                server_keys = list(sources.keys()) if sources else ["myTV"]
                return {
                    "servers": server_keys,
                    "defaultServer": self.default_server
                }
        except Exception as e:
            logger.debug("[voir-anime] get_episode_servers error: %s", e)
            return {"servers": ["myTV"], "defaultServer": self.default_server}

    def _parse_episode_sources(self, html: str) -> Dict[str, str]:
        """Extrait la cartographie {nom_serveur: embed_url} depuis les scripts ou iframes de la page."""
        sources: Dict[str, str] = {}
        m = re.search(r"var\s+thisChapterSources\s*=\s*(\{.+?\});", html, re.DOTALL)
        if m:
            try:
                raw_dict = json.loads(m.group(1))
                for k, v in raw_dict.items():
                    raw_src = ""
                    src_m = re.search(r"""src=["\x27]([^"\x27]+)["\x27]""", v)
                    if src_m:
                        raw_src = src_m.group(1).replace(r"\/", "/")
                    elif v.strip().startswith("http") or v.strip().startswith("//") or "/e/" in v:
                        raw_src = v.strip().replace(r"\/", "/")
                    if raw_src:
                        if not raw_src.startswith("http"):
                            raw_src = urljoin(self.base_url, raw_src)
                        norm_k = k.replace("LECTEUR", "").strip()
                        key = "myTV" if "mytv" in norm_k.lower() else (
                            "stape" if any(s in norm_k.lower() for s in ["stape", "streamtape"]) else (
                                "voe" if "voe" in norm_k.lower() else (
                                    "fhd1" if "fhd" in norm_k.lower() else (
                                        "moon" if "moon" in norm_k.lower() else norm_k
                                    )
                                )
                            )
                        )
                        sources[key] = raw_src
            except Exception as e:
                logger.debug("[voir-anime] Erreur parsing thisChapterSources: %s", e)

        if not sources:
            soup = BeautifulSoup(html, "html.parser")
            for ifr in soup.select("iframe"):
                src = ifr.get("src") or ifr.get("data-src")
                if src and not src.startswith("about:"):
                    if not src.startswith("http"):
                        src = urljoin(self.base_url, src)
                    s_lower = src.lower()
                    if any(h in s_lower for h in ["voembed", "vidmoly"]):
                        sources["myTV"] = src
                    elif any(h in s_lower for h in ["streamtape", "stape"]):
                        sources["stape"] = src
                    elif "voe" in s_lower:
                        sources["voe"] = src
                    elif "mail.ru" in s_lower:
                        sources["fhd1"] = src
                    elif "gn1r5n" in s_lower or "byse" in s_lower:
                        sources["moon"] = src
                    else:
                        sources[f"server_{len(sources)+1}"] = src
        return sources

    def extract_download_info(
        self,
        episode_url: str,
        preferred_server: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info("[voir-anime] extract_download_info: %s (pref_server=%s, pref_quality=%s)",
                    episode_url, preferred_server, preferred_quality)
        result = {
            "videoUrl": "",
            "videoChunks": "[]",
            "videoQualities": "{}",
            "subtitleUrl": "",
            "serverType": "unknown",
            "availableServers": "[]",
            "selectedQuality": "",
        }

        try:
            with self._get_client(follow_redirects=True, referer=self.base_url) as client:
                resp = client.get(episode_url)
                if resp.status_code != 200:
                    return result
                html = resp.text

                # 1. Identifier tous les serveurs disponibles
                sources = self._parse_episode_sources(html)
                avail_servers = list(sources.keys())
                result["availableServers"] = json.dumps(avail_servers)

                if not sources:
                    return result

                # 2. Déterminer l'ordre des serveurs à tenter
                target_server = preferred_server or self.default_server
                if target_server and target_server.lower() == "auto":
                    target_server = None

                default_priority = ["myTV", "stape", "voe", "fhd1", "moon"]
                try_order: List[str] = []

                # Si un serveur préféré est spécifié et disponible, le tenter en premier
                if target_server:
                    for s_key in sources.keys():
                        if s_key.lower() == target_server.lower():
                            try_order.append(s_key)
                            break

                # Ajouter les autres serveurs disponibles dans l'ordre de priorité
                for s_prio in default_priority:
                    for s_key in sources.keys():
                        if s_key.lower() == s_prio.lower() and s_key not in try_order:
                            try_order.append(s_key)

                # Ajouter les éventuels serveurs restants
                for s_key in sources.keys():
                    if s_key not in try_order:
                        try_order.append(s_key)

                best_url = ""
                qualities: Dict[str, str] = {}
                subtitle_url = ""
                resolved_server = "unknown"

                # 3. Résolution selon l'ordre de priorité (avec fallback automatique si indisponible)
                for s_name in try_order:
                    s_url = sources[s_name]
                    logger.info("[voir-anime] Tentative de résolution sur serveur '%s' (%s)", s_name, s_url)
                    s_lower = s_name.lower()

                    if s_lower == "mytv" or any(h in s_url for h in ["voembed", "vidmoly"]):
                        u, q, sub = self._resolve_mytv(s_url, episode_url, client)
                        if u:
                            best_url, qualities, subtitle_url = u, q, sub
                            resolved_server = "myTV"
                            break

                    elif s_lower in ["stape", "streamtape"] or "streamtape" in s_url:
                        mp4_url = self._resolve_streamtape(s_url, episode_url, client)
                        if mp4_url:
                            best_url = mp4_url
                            qualities = {"1080p (Streamtape)": mp4_url}
                            resolved_server = "stape"
                            break

                    elif s_lower == "voe" or "voe" in s_url:
                        u, q = self._resolve_voe(s_url, episode_url, client)
                        if u:
                            best_url, qualities = u, q
                            resolved_server = "voe"
                            break

                    elif s_lower == "fhd1" or "mail.ru" in s_url:
                        u, q = self._resolve_fhd1(s_url, episode_url, client)
                        if u:
                            best_url, qualities = u, q
                            resolved_server = "fhd1"
                            break

                    elif s_lower == "moon" or "gn1r5n" in s_url or "byse" in s_url:
                        u, q = self._resolve_moon(s_url, episode_url, client)
                        if u:
                            best_url, qualities = u, q
                            resolved_server = "moon"
                            break

                # 4. Sélection de la qualité souhaitée
                selected_q_label = ""
                if qualities:
                    if preferred_quality:
                        for q_k, q_v in qualities.items():
                            if preferred_quality.lower() in q_k.lower():
                                best_url = q_v
                                selected_q_label = q_k
                                break

                    if not selected_q_label:
                        for q_cand in ["1080p", "720p", "480p", "360p"]:
                            for q_k, q_v in qualities.items():
                                if q_cand in q_k.lower():
                                    best_url = q_v
                                    selected_q_label = q_k
                                    break
                            if selected_q_label:
                                break

                    if not selected_q_label:
                        selected_q_label = next(iter(qualities.keys()))
                        best_url = qualities[selected_q_label]

                result["videoUrl"] = best_url
                result["videoQualities"] = json.dumps(qualities)
                result["videoChunks"] = json.dumps([best_url] if best_url else [])
                result["subtitleUrl"] = subtitle_url
                result["serverType"] = resolved_server
                result["selectedQuality"] = selected_q_label

        except Exception as e:
            logger.error("[voir-anime] extract_download_info error: %s", e)

        return result

    def _resolve_mytv(self, ifr_url: str, episode_url: str, client: httpx.Client) -> Tuple[str, Dict[str, str], str]:
        """Résout le lecteur myTV (Voembed / Vidmoly) en playlist HLS m3u8 et extrait toutes les résolutions."""
        code_m = re.search(r"embed-([a-zA-Z0-9]+)\.html", ifr_url)
        file_code = code_m.group(1) if code_m else ""

        domains = ["voembed.net", "vidmoly.to", "vidmoly.me", "vidmoly.biz"]
        tried_urls = [ifr_url]
        if file_code:
            for d in domains:
                cand = f"https://{d}/embed-{file_code}.html"
                if cand not in tried_urls:
                    tried_urls.append(cand)

        embed_html = ""
        for cand_url in tried_urls:
            try:
                emb_resp = client.get(cand_url, headers={"Referer": episode_url}, timeout=10)
                if emb_resp.status_code == 200 and len(emb_resp.text) > 500:
                    embed_html = emb_resp.text
                    js_redir = re.search(r"window\.location\.replace\(\x27([^\x27]+)\x27\)", embed_html)
                    if js_redir:
                        redir_resp = client.get(js_redir.group(1), headers={"Referer": episode_url}, timeout=10)
                        if redir_resp.status_code == 200:
                            embed_html = redir_resp.text
                    break
            except Exception:
                pass

        qualities: Dict[str, str] = {}
        best_url = ""
        subtitle_url = ""

        if embed_html:
            m_sources = re.search(r"sources\s*:\s*\[\s*\{\s*file\s*:\s*[\x27\x22]([^\x27\x22]+)[\x27\x22]", embed_html)
            master_m3u8 = m_sources.group(1) if m_sources else ""
            if not master_m3u8:
                m_gen = re.search(r"[\x27\x22](https?://[^\x27\x22]+\.m3u8[^\x27\x22]*)[\x27\x22]", embed_html)
                if m_gen:
                    master_m3u8 = m_gen.group(1)

            if master_m3u8:
                parsed = self._extract_qualities_from_m3u8(master_m3u8, client)
                if parsed:
                    qualities.update(parsed)
                    for q_key in ["1080p", "720p", "480p", "360p"]:
                        if q_key in qualities:
                            best_url = qualities[q_key]
                            break
                    if not best_url:
                        best_url = next(iter(qualities.values()))
                else:
                    best_url = master_m3u8
                    qualities["Auto"] = master_m3u8

            sub_m = re.search(r"[\x27\x22](https?://[^\x27\x22]+\.(?:vtt|srt)[^\x27\x22]*)[\x27\x22]", embed_html, re.IGNORECASE)
            if sub_m:
                subtitle_url = sub_m.group(1)

        return best_url, qualities, subtitle_url

    def _resolve_streamtape(self, ifr_url: str, referer: str, client: httpx.Client) -> Optional[str]:
        """Résout l'URL directe d'une vidéo Streamtape."""
        try:
            st_resp = client.get(ifr_url, headers={"Referer": referer}, timeout=12)
            if st_resp.status_code != 200:
                return None
            st_html = st_resp.text
            if "Video not found" in st_html or "deleted by the creator" in st_html or "has been removed" in st_html:
                return None

            pattern = r"innerHTML\s*=\s*['\"]([^'\"]+)['\"]\s*\+\s*(?:''\s*\+\s*)?\(\s*['\"]([^'\"]+)['\"]\s*\)((?:\s*\.substring\(\s*\d+\s*\))+)"
            for m in re.finditer(pattern, st_html):
                prefix = m.group(1)
                raw_str = m.group(2)
                sub_ops = re.findall(r"\.substring\((\d+)\)", m.group(3))
                s = raw_str
                for op in sub_ops:
                    s = s[int(op):]
                cand = prefix + s
                if cand.startswith("//"):
                    cand = "https:" + cand
                elif cand.startswith("/"):
                    cand = "https://" + cand.lstrip("/")

                if "streamtape.com/get_video?" in cand:
                    try:
                        redir_resp = client.get(cand, headers={"Referer": ifr_url}, follow_redirects=False, timeout=8)
                        if redir_resp.status_code in [301, 302, 303, 307, 308]:
                            final_url = redir_resp.headers.get("location")
                            if final_url:
                                return final_url
                        return cand
                    except Exception:
                        return cand

            m_tape = re.search(r"document\.getElementById\(['\"]videolink['\"]\)\.innerHTML\s*=\s*['\"]([^'\"]+)['\"]", st_html)
            if m_tape:
                cand = "https:" + m_tape.group(1) if m_tape.group(1).startswith("//") else m_tape.group(1)
                return cand
        except Exception as e:
            logger.debug("[voir-anime] Erreur résolution Streamtape: %s", e)
        return None

    def _resolve_voe(self, ifr_url: str, referer: str, client: httpx.Client) -> Tuple[str, Dict[str, str]]:
        """Résout le lecteur VOE vers sa source vidéo."""
        try:
            resp = client.get(ifr_url, headers={"Referer": referer}, timeout=10)
            if resp.status_code != 200:
                return "", {}
            html = resp.text
            redir_m = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", html)
            if redir_m:
                voe_url = redir_m.group(1)
                redir_resp = client.get(voe_url, headers={"Referer": ifr_url}, timeout=10)
                if redir_resp.status_code == 200:
                    html = redir_resp.text

            m3u8_matches = re.findall(r"['\"](https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*)['\"]", html)
            mp4_matches = re.findall(r"['\"](https?://[^\s'\"<>]+\.mp4[^\s'\"<>]*)['\"]", html)

            valid_mp4 = [u for u in mp4_matches if "test-videos" not in u and "google" not in u]
            valid_m3u8 = [u for u in m3u8_matches if "google" not in u]

            if valid_m3u8:
                m3u8_url = valid_m3u8[0]
                qualities = self._extract_qualities_from_m3u8(m3u8_url, client)
                if not qualities:
                    qualities["Auto (VOE)"] = m3u8_url
                best = qualities.get("1080p") or qualities.get("720p") or next(iter(qualities.values()))
                return best, qualities
            elif valid_mp4:
                return valid_mp4[0], {"Original (VOE)": valid_mp4[0]}

            m_src = re.search(r"sources\s*=\s*(\{[^{}]+\})", html)
            if m_src:
                try:
                    data = json.loads(m_src.group(1))
                    hls = data.get("hls") or data.get("mp4")
                    if hls:
                        return hls, {"VOE": hls}
                except Exception:
                    pass
        except Exception as e:
            logger.debug("[voir-anime] _resolve_voe error: %s", e)
        return "", {}

    def _resolve_fhd1(self, ifr_url: str, referer: str, client: httpx.Client) -> Tuple[str, Dict[str, str]]:
        """Résout le lecteur FHD1 (Mail.ru) vers les résolutions MP4."""
        try:
            m_id = re.search(r"/video/embed/(\d+)", ifr_url)
            if not m_id:
                return "", {}
            vid_id = m_id.group(1)
            meta_url = f"https://my.mail.ru/+/video/meta/{vid_id}"
            headers = {"User-Agent": proxy_service.get_user_agent(), "Referer": ifr_url}
            r = client.get(meta_url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                videos = data.get("videos", [])
                qualities: Dict[str, str] = {}
                for v in videos:
                    key = str(v.get("key", "HD"))
                    label = f"{key}p" if key.isdigit() else key
                    u = v.get("url")
                    if u:
                        if u.startswith("//"):
                            u = "https:" + u
                        qualities[label] = u
                if qualities:
                    best = qualities.get("1080p") or qualities.get("720p") or next(iter(qualities.values()))
                    return best, qualities
        except Exception as e:
            logger.debug("[voir-anime] _resolve_fhd1 error: %s", e)
        return "", {}

    def _resolve_moon(self, ifr_url: str, referer: str, client: httpx.Client) -> Tuple[str, Dict[str, str]]:
        """Résout le lecteur MOON (Byse) vers son flux de streaming."""
        try:
            m_code = re.search(r"/e/([a-zA-Z0-9]+)", ifr_url)
            if not m_code:
                return "", {}
            code = m_code.group(1)
            base_moon = "https://gn1r5n.org"
            headers = {
                "User-Agent": proxy_service.get_user_agent(),
                "Referer": ifr_url,
                "X-Embed-Origin": "voir-anime.to",
                "X-Embed-Referer": self.base_url + "/",
                "X-Embed-Parent": self.base_url + "/",
            }
            det_url = f"{base_moon}/api/videos/{code}/embed/details"
            r_det = client.get(det_url, headers=headers, timeout=8)
            if r_det.status_code == 200:
                stream_url = f"{base_moon}/api/videos/stream/{code}"
                return stream_url, {"1080p (MOON)": stream_url}
        except Exception as e:
            logger.debug("[voir-anime] _resolve_moon error: %s", e)
        return "", {}

    def _extract_qualities_from_m3u8(self, master_url: str, client: httpx.Client) -> Dict[str, str]:
        qualities: Dict[str, str] = {}
        try:
            resp = client.get(master_url, headers={"Referer": "https://voembed.net/"})
            if resp.status_code == 200:
                lines = resp.text.strip().split("\n")
                for i, line in enumerate(lines):
                    if line.startswith("#EXT-X-STREAM-INF:"):
                        res_m = re.search(r"RESOLUTION=\d+x(\d+)", line)
                        label = f"{res_m.group(1)}p" if res_m else "Stream"
                        if i + 1 < len(lines):
                            stream_url = lines[i + 1].strip()
                            if not stream_url.startswith("#"):
                                qualities[label] = urljoin(master_url, stream_url)
        except Exception as e:
            logger.debug("[voir-anime] _extract_qualities_from_m3u8: %s", e)
        return qualities

    def extract_video_chunks(self, episode_url: str) -> List[str]:
        info = self.extract_download_info(episode_url)
        try:
            return json.loads(info.get("videoChunks", "[]"))
        except Exception:
            return []

    def extract_video_qualities(self, episode_url: str) -> Dict[str, str]:
        info = self.extract_download_info(episode_url)
        try:
            return json.loads(info.get("videoQualities", "{}"))
        except Exception:
            return {}

voiranime_service = VoirAnimeScrapingService()
