import json
import logging
import re
import time
from typing import List, Optional, Dict
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from animan.config import settings
from animan.models.anime import AnimeResult, AnimeDetail, Episode
from animan.services.proxy_service import proxy_service
from animan.services.unpacking import try_unpack

logger = logging.getLogger("animan.scraping")

NEWSID_PATTERN = re.compile(r"newsid=(\d+)")
JS_ARRAY_PATTERN = re.compile(r"var\s+(defined_\w+)\s*=\s*\[([^\]]+)\]", re.IGNORECASE)
VIDZY_URL_PATTERN = re.compile(r"(https?://(?:vidzy\.[a-z0-9]+|luluvdo\.[a-z0-9]+)[^\"'\s]+)", re.IGNORECASE)

class ScrapingService:
    def __init__(self):
        self.base_url = settings.BASE_URL
        self.latest_cache: List[AnimeResult] = []
        self.last_cache_time: float = 0.0
        self.is_refreshing: bool = False

    def _get_client(self, follow_redirects: bool = True) -> httpx.Client:
        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": self.base_url + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        proxy = proxy_service.get_random_proxy()
        return httpx.Client(
            headers=headers,
            proxy=proxy,
            timeout=httpx.Timeout(settings.READ_TIMEOUT, connect=settings.CONNECTION_TIMEOUT),
            follow_redirects=follow_redirects,
            verify=False,
        )

    def _get_async_client(self, follow_redirects: bool = True) -> httpx.AsyncClient:
        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": self.base_url + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        proxy = proxy_service.get_random_proxy()
        return httpx.AsyncClient(
            headers=headers,
            proxy=proxy,
            timeout=httpx.Timeout(settings.READ_TIMEOUT, connect=settings.CONNECTION_TIMEOUT),
            follow_redirects=follow_redirects,
            verify=False,
        )

    # -------------------------------------------------------------------------
    # Dernières sorties & Cache
    # -------------------------------------------------------------------------

    async def get_latest_releases(self) -> List[AnimeResult]:
        now = time.time()
        if not self.latest_cache or (now - self.last_cache_time > 15 * 60):
            await self.refresh_cache()
        return list(self.latest_cache)

    async def refresh_cache(self):
        try:
            logger.info("Chargement des dernières sorties depuis %s", self.base_url)
            async with self._get_async_client() as client:
                resp = await client.get(self.base_url)
                if resp.status_code == 200:
                    results = self.parse_search_results(resp.text)
                    if results:
                        self.latest_cache = results
                        self.last_cache_time = time.time()
                        logger.info("Cache mis à jour (french-manga: %d animés)", len(self.latest_cache))
        except Exception as e:
            logger.error("Erreur lors de la mise à jour du cache french-manga: %s", e)

    # -------------------------------------------------------------------------
    # Recherche
    # -------------------------------------------------------------------------

    async def search_anime(self, query: str) -> List[AnimeResult]:
        logger.info("Recherche anime: '%s'", query)
        results: List[AnimeResult] = []

        try:
            search_url = f"{self.base_url}/engine/ajax/search.php"
            async with self._get_async_client() as client:
                resp = await client.post(
                    search_url,
                    data={"query": query, "page": "1"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code == 200:
                    results = self.parse_search_results(resp.text)

            if not results:
                results = await self.search_via_listing(query)
        except Exception as e:
            logger.error("Erreur lors de la recherche french-manga: %s", e)
            results = await self.search_via_listing(query)

        logger.info("Trouvé %d résultat(s) pour '%s'", len(results), query)
        return results

    async def search_via_listing(self, query: str) -> List[AnimeResult]:
        results: List[AnimeResult] = []
        lower_q = query.lower()

        try:
            async with self._get_async_client() as client:
                for page in range(1, 6):
                    url = (
                        f"{self.base_url}/manga-streaming-1/"
                        if page == 1
                        else f"{self.base_url}/index.php?cstart={page}&do=cat&category=manga-streaming-1"
                    )
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        page_results = self.parse_search_results(resp.text)
                        for r in page_results:
                            if lower_q in r.title.lower():
                                results.append(r)
                    if len(results) >= 20:
                        break
        except Exception as e:
            logger.error("Erreur fallback listing: %s", e)

        return results

    def parse_search_results(self, html: str) -> List[AnimeResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: List[AnimeResult] = []

        articles = soup.select(".short, .mov, .shortstory, .short-story, article, .anime-card, .movie-item, .story-item, .search-item")
        if not articles:
            links = soup.select("a[href*=newsid]")
            articles = []
            for l in links:
                p = l.parent
                if p and p.parent:
                    articles.append(p.parent)

        seen_urls = set()
        for article in articles:
            try:
                res = self.parse_anime_card(article)
                if res and res.title and res.url and res.url not in seen_urls:
                    seen_urls.add(res.url)
                    results.append(res)
            except Exception as e:
                logger.debug("Erreur parsing carte anime: %s", e)

        return results

    def parse_anime_card(self, card) -> Optional[AnimeResult]:
        url, title, image_url, version, anime_type, episode_info, anime_id = "", "", "", "", "Anime", "", ""

        classes = card.get("class", [])
        if "search-item" in classes or card.get("onclick"):
            onclick = card.get("onclick", "")
            m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
            if m:
                url = m.group(1)
                if url.startswith("/"):
                    url = urljoin(self.base_url, url)
            else:
                return None

            title_el = card.select_one(".search-title")
            if title_el:
                title = title_el.get_text().strip()

            img = card.select_one(".search-poster img")
            if img:
                image_url = img.get("src", "")
                if not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)
        else:
            link = card.select_one("a[href*=newsid]")
            if not link:
                link = card.select_one("a[href$='.html']:not([href*=xfsearch]):not([href*=do=search])")
            if not link:
                return None

            url = link.get("href", "")
            if not url or "xfsearch" in url or "do=search" in url:
                return None
            if not url.startswith("http"):
                url = urljoin(self.base_url, url)

            title_el = card.select_one("h2, h3, h4, .title, .movie-title, .short-title")
            if title_el:
                title = title_el.get_text().strip()
            else:
                title = link.get("title", "").strip() or link.get_text().strip()

            img = card.select_one("img[src]")
            if img:
                image_url = img.get("src", "") or img.get("data-src", "")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            ver_el = card.select_one("a[href*=version-serie], .version, .quality")
            if ver_el:
                version = ver_el.get_text().strip()

            type_el = card.select_one("a[href*='xf=Film'], a[href*='xf=Anime']")
            if type_el:
                anime_type = type_el.get_text().strip()

        if not title or len(title) < 2:
            return None

        m_newsid = NEWSID_PATTERN.search(url)
        if m_newsid:
            anime_id = m_newsid.group(1)
        else:
            m_id = re.search(r"/(\d+)-", url)
            anime_id = m_id.group(1) if m_id else str(hash(url))[:8]

        return AnimeResult(
            id=anime_id,
            title=title,
            imageUrl=image_url,
            url=url,
            version=version,
            type=anime_type,
            episodeInfo=episode_info,
        )

    # -------------------------------------------------------------------------
    # Détail d'un animé
    # -------------------------------------------------------------------------

    async def get_anime_detail(self, anime_url: str) -> Optional[AnimeDetail]:
        logger.info("Chargement détails anime: %s", anime_url)
        try:
            async with self._get_async_client() as client:
                resp = await client.get(anime_url)
                if resp.status_code != 200:
                    return None

                soup = BeautifulSoup(resp.text, "html.parser")
                title_el = soup.select_one("h1, .full-title, .movie-title, #news-title")
                title = title_el.get_text().strip() if title_el else (soup.title.string.split("|")[0].strip() if soup.title else "")

                poster_img = soup.select_one(".full-story img[src], .fstory img[src], .movie-poster img[src], .poster img[src], .short-img img[src]")
                image_url = ""
                if poster_img:
                    image_url = poster_img.get("src", "")
                    if image_url and not image_url.startswith("http"):
                        image_url = urljoin(self.base_url, image_url)

                synopsis = ""
                syn_el = soup.select_one(".full-story .full-text, .fstory .ftext, .movie-description, .story-text, .fdesc")
                if syn_el:
                    synopsis = syn_el.get_text().strip()
                else:
                    paras = soup.select(".full-story p, .fstory p, #dle-content p")
                    parts = [p.get_text().strip() for p in paras if len(p.get_text().strip()) > 50 and "Genre" not in p.text and "Studio" not in p.text]
                    synopsis = " ".join(parts).strip()

                original_title = None
                studio = None
                all_text = soup.select(".full-story li, .fstory li, .movie-info li, .finfo li, .full-story span, .fstory span")
                for el in all_text:
                    t = el.get_text()
                    if "Titre Original" in t:
                        original_title = t.split(":")[-1].strip()
                    if "Studio" in t:
                        studio = t.split(":")[-1].strip()

                genres = list(dict.fromkeys(g.get_text().strip() for g in soup.select("a[href*=manga_genre]") if g.get_text().strip()))
                directors = list(dict.fromkeys(d.get_text().strip() for d in soup.select("a[href*=director]") if d.get_text().strip()))
                actors = list(dict.fromkeys(a.get_text().strip() for a in soup.select("a[href*=actors]") if a.get_text().strip()))

                version_el = soup.select_one("a[href*=version-serie]")
                version = version_el.get_text().strip() if version_el else ""

                newsid = self.extract_news_id(anime_url, soup)
                episodes: List[Episode] = []

                if newsid:
                    api_url = f"{self.base_url}/engine/ajax/manga_episodes_api.php?id={newsid}"
                    try:
                        api_resp = await client.get(api_url, headers={"Referer": anime_url})
                        if api_resp.status_code == 200:
                            episodes = self.parse_episodes_from_json(api_resp.text)
                    except Exception as e:
                        logger.warning("API épisodes échouée, repli DOM: %s", e)

                if not episodes:
                    episodes = self.parse_episodes_from_dom(soup)

                return AnimeDetail(
                    title=title,
                    originalTitle=original_title,
                    synopsis=synopsis,
                    imageUrl=image_url,
                    version=version,
                    studio=studio,
                    url=anime_url,
                    genres=genres,
                    directors=directors,
                    actors=actors,
                    episodes=episodes,
                )
        except Exception as e:
            logger.error("Erreur chargement anime french-manga: %s", e)
            return None

    def extract_news_id(self, url: str, soup: BeautifulSoup) -> str:
        m = NEWSID_PATTERN.search(url)
        if m:
            return m.group(1)
        m2 = re.search(r"/(\d+)-", url)
        if m2:
            return m2.group(1)

        canon = soup.select_one("link[rel=canonical]")
        if canon and canon.get("href"):
            c_url = canon["href"]
            mc = NEWSID_PATTERN.search(c_url)
            if mc:
                return mc.group(1)
            mc2 = re.search(r"/(\d+)-", c_url)
            if mc2:
                return mc2.group(1)
        return ""

    def parse_episodes_from_json(self, json_str: str) -> List[Episode]:
        episodes: List[Episode] = []
        try:
            data = json.loads(json_str)
            for v_key in ["vf", "vostfr"]:
                v_node = data.get(v_key)
                if not isinstance(v_node, dict):
                    continue

                display_version = v_key.upper()
                for ep_str, players in v_node.items():
                    if not isinstance(players, dict):
                        continue
                    try:
                        ep_num = int(ep_str)
                    except ValueError:
                        continue

                    player_url = ""
                    download_page_url = ""
                    for p_name, p_url in players.items():
                        if not p_url:
                            continue
                        if not player_url:
                            player_url = p_url
                        if "vidzy" in p_name.lower() or "vidzy" in p_url.lower():
                            player_url = p_url
                            break

                    if player_url:
                        if "vidzy" in player_url:
                            download_page_url = (
                                player_url.replace("/embed-", "/d/")
                                .replace(".html", "")
                                .replace("/e/", "/d/")
                            )
                            if not download_page_url.endswith("_n"):
                                download_page_url += "_n"

                        ep_title = f"Épisode {ep_num}"
                        info_node = data.get("info", {})
                        if isinstance(info_node, dict) and ep_str in info_node:
                            ep_info = info_node[ep_str]
                            if isinstance(ep_info, dict) and ep_info.get("title"):
                                ep_title = ep_info["title"]

                        episodes.append(
                            Episode(
                                number=ep_num,
                                title=ep_title,
                                playerUrl=player_url,
                                downloadPageUrl=download_page_url,
                                version=display_version,
                            )
                        )
        except Exception as e:
            logger.error("Erreur parsing JSON épisodes: %s", e)

        episodes.sort(key=lambda x: (x.version, x.number))
        return episodes

    def parse_episodes_from_dom(self, soup: BeautifulSoup) -> List[Episode]:
        episodes: List[Episode] = []
        global_version = ""
        ver_el = soup.select_one("a[href*=version-serie]")
        if ver_el:
            global_version = ver_el.get_text().strip()

        version_urls: Dict[str, List[str]] = {}
        for script in soup.select("script"):
            data = script.string or ""
            if not data:
                continue

            for m in JS_ARRAY_PATTERN.finditer(data):
                var_name = m.group(1).lower()
                arr_content = m.group(2)
                ver = "VF" if "vf" in var_name and "vostfr" not in var_name else "VOSTFR"
                urls = self._extract_urls_from_js_array(arr_content)
                if urls:
                    version_urls[ver] = urls

            if not version_urls:
                vidzy_urls = list(dict.fromkeys(VIDZY_URL_PATTERN.findall(data)))
                if vidzy_urls:
                    version_urls[global_version or "VOSTFR"] = vidzy_urls

        if version_urls:
            for ver, urls in version_urls.items():
                for idx, url in enumerate(urls):
                    dl_page = (
                        url
                        if "/d/" in url
                        else url.replace("/e/", "/d/")
                        if ("/e/" in url and ("vidzy." in url or "luluvdo." in url))
                        else url if ("vidzy." in url or "luluvdo." in url)
                        else ""
                    )
                    episodes.append(
                        Episode(
                            number=idx + 1,
                            title=f"Épisode {idx + 1}",
                            playerUrl=url,
                            downloadPageUrl=dl_page,
                            version=ver,
                        )
                    )

        if not episodes:
            seen = set()
            ep_links = soup.select("a[href*=vidzy], a[href*=luluvdo], .ep-title a[href], a.btn-download[href], a[href*='/d/']")
            ep_num = 1
            for link in ep_links:
                href = link.get("href", "")
                if not href or href in seen or "xfsearch" in href or "manga_genre" in href:
                    continue
                seen.add(href)
                text = link.get_text().strip()
                m = re.search(r"(?:Episode|Ep|EP|Épisode)\s*(\d+)", text, re.IGNORECASE)
                num = int(m.group(1)) if m else ep_num
                episodes.append(
                    Episode(
                        number=num,
                        title=text or f"Épisode {num}",
                        playerUrl=href,
                        downloadPageUrl=href if "vidzy" in href else "",
                        version=global_version or "VOSTFR",
                    )
                )
                ep_num = num + 1

        episodes.sort(key=lambda x: (x.version, x.number))
        return episodes

    def _extract_urls_from_js_array(self, content: str) -> List[str]:
        urls = []
        for m in re.finditer(r"['\"]([^'\"]+)['\"]", content):
            u = m.group(1).strip()
            if u.startswith("//"):
                u = "https:" + u
            if u.startswith("http"):
                urls.append(u)
        return urls

    # -------------------------------------------------------------------------
    # Extraction du lien de téléchargement Vidzy
    # -------------------------------------------------------------------------

    def extract_download_info(self, vidzy_url: str) -> Dict[str, str]:
        logger.info("Extraction lien direct depuis: %s", vidzy_url)
        result = {
            "videoUrl": "",
            "subtitleUrl": "",
            "subtitles": "[]",
        }

        domain = "https://vidzy.live"
        m_domain = re.search(r"(https?://[^/]+)", vidzy_url)
        if m_domain:
            domain = m_domain.group(1)

        video_id = self._extract_vidzy_id(vidzy_url)
        if not video_id:
            raise ValueError(f"Impossible d'extraire le video_id depuis {vidzy_url}")

        download_url = f"{domain}/d/{video_id}_n"
        embed_url = f"{domain}/embed-{video_id}.html"

        # 1. Extraction vidéo directe depuis la page de téléchargement (prioritaire)
        try:
            with self._get_client(follow_redirects=True) as client:
                dl_page_resp = client.get(download_url, headers={"Referer": f"{domain}/"})
                dl_html = dl_page_resp.text

                op, req_id, mode, h_val = "download_orig", video_id, "n", ""
                soup = BeautifulSoup(dl_html, "html.parser")
                form = soup.select_one("form#F1, form[action]")
                if form:
                    op_el = form.select_one("input[name=op]")
                    if op_el:
                        op = op_el.get("value", op)
                    id_el = form.select_one("input[name=id]")
                    if id_el:
                        req_id = id_el.get("value", req_id)
                    mode_el = form.select_one("input[name=mode]")
                    if mode_el:
                        mode = mode_el.get("value", mode)
                    h_el = form.select_one("input[name=hash]")
                    if h_el:
                        h_val = h_el.get("value", "")
                else:
                    m_hash = re.search(r"name=['\"]hash['\"]\s+value=['\"]([^'\"]+)['\"]", dl_html)
                    if m_hash:
                        h_val = m_hash.group(1)

                if h_val:
                    logger.info("Hash trouvé: '%s'. Envoi POST...", h_val)
                    # Use client without automatic redirect to catch 302 location
                    with self._get_client(follow_redirects=False) as no_redir_client:
                        post_resp = no_redir_client.post(
                            download_url,
                            data={"op": op, "id": req_id, "mode": mode, "hash": h_val},
                            headers={"Referer": download_url},
                        )
                        if post_resp.status_code in [301, 302]:
                            loc = post_resp.headers.get("Location")
                            if loc and not loc.startswith(f"{domain}/d/"):
                                logger.info("Lien MP4 résolu (302): %s", loc)
                                result["videoUrl"] = loc
                        elif post_resp.status_code == 200:
                            direct_url = self._extract_video_from_html(post_resp.text)
                            if direct_url and not direct_url.startswith(f"{domain}/d/"):
                                logger.info("Lien MP4 extrait (200): %s", direct_url)
                                result["videoUrl"] = direct_url
        except Exception as e:
            logger.error("Erreur lors de l'extraction de la vidéo sur %s: %s", download_url, e)

        # 2. Extraction des sous-titres (optionnelle, isolée avec timeout court)
        try:
            headers = {
                "User-Agent": proxy_service.get_user_agent(),
                "Referer": self.base_url + "/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            with httpx.Client(headers=headers, timeout=5.0, follow_redirects=True, verify=False) as sub_client:
                embed_resp = sub_client.get(embed_url)
                if embed_resp.status_code == 200:
                    search_source = try_unpack(embed_resp.text)
                    subtitles_list = self._extract_all_subtitles(search_source, embed_resp.text)
                    result["subtitles"] = json.dumps(subtitles_list)
                    if subtitles_list:
                        result["subtitleUrl"] = subtitles_list[0].get("url", "")
        except Exception as e:
            logger.debug("Sous-titres non disponibles ou timeout sur %s: %s", embed_url, e)

        # 3. Vérification stricte : refuser si aucune URL vidéo valide n'est extraite
        if not result.get("videoUrl"):
            raise ValueError(f"Impossible d'extraire le lien direct vidéo depuis {vidzy_url} (résolution échouée)")

        return result

    def _extract_vidzy_id(self, url: str) -> str:
        if "embed-" in url:
            start = url.find("embed-") + 6
            end = url.find(".html", start)
            return url[start:end] if end != -1 else url[start:]
        last_slash = url.rfind("/")
        if last_slash != -1:
            return url[last_slash + 1:].replace("_n", "").replace("_o", "").replace(".html", "")
        return ""

    def _extract_all_subtitles(self, source: str, html: str) -> List[Dict[str, str]]:
        subs = []
        seen = set()

        # JS tracks regex
        tracks_match = re.search(r"tracks\s*[=:]\s*\[([^\]]+)\]", source, re.DOTALL | re.IGNORECASE)
        if tracks_match:
            block = tracks_match.group(1)
            for em in re.finditer(r"file\s*:\s*['\"]([^'\"]+)['\"](?:.*?label\s*:\s*['\"]([^'\"]*)['\"])?", block, re.DOTALL):
                url = em.group(1)
                label = em.group(2) or "Sous-titres"
                if re.search(r"\.(vtt|srt|ass)(\?.*)?$", url) and url not in seen:
                    seen.add(url)
                    lang = "fr" if "fr" in label.lower() else "und"
                    subs.append({"url": url, "label": label, "lang": lang})

        if not subs:
            for vm in re.finditer(r"(https?://[^'\"\s]+\.(?:vtt|srt)(?:[^'\"\s]*)?)", source, re.IGNORECASE):
                url = vm.group(1)
                if url not in seen:
                    seen.add(url)
                    lang = "fr" if "fre" in url or "fr" in url else "und"
                    subs.append({"url": url, "label": f"Sous-titres {len(subs) + 1}", "lang": lang})

        soup = BeautifulSoup(html, "html.parser")
        for track in soup.select("track[src]"):
            kind = track.get("kind", "").lower()
            if not kind or "subtitle" in kind or "caption" in kind:
                src = track.get("src", "")
                if src and src not in seen:
                    seen.add(src)
                    label = track.get("label", "") or track.get("srclang", "Sous-titres")
                    subs.append({"url": src, "label": label, "lang": track.get("srclang", "und")})

        return subs

    def _extract_video_from_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        link = soup.select_one("a[href*='.mp4'], a[href*='.mkv'], a[href*='.avi']")
        if link and link.get("href"):
            return link["href"]
        m = re.search(r"href=['\"]([^'\"]+\.(?:mp4|mkv|avi)[^'\"]*)['\"]", html, re.IGNORECASE)
        return m.group(1) if m else ""

scraping_service = ScrapingService()
