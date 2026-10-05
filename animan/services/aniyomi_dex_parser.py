import io
import logging
import re
import struct
import zipfile
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger("animan.dex_parser")


@dataclass
class SourceRecipe:
    """Recette de scraping extraite depuis le bytecode Dalvik d'une extension Aniyomi."""
    name: str = ""
    pkg: str = ""
    base_url: str = ""
    lang: str = "all"
    supports_latest: bool = True
    
    # Sélecteurs CSS
    popular_selector: str = ""
    popular_next_selector: str = ""
    latest_selector: str = ""
    latest_next_selector: str = ""
    search_selector: str = ""
    search_next_selector: str = ""
    episode_list_selector: str = ""
    
    # Routes & Requêtes
    popular_request_path: str = ""
    latest_request_path: str = ""
    search_request_path: str = ""
    search_query_param: str = "s"  # ex: 's', 'keyword', 'story', 'q'
    search_method: str = "GET"     # 'GET' ou 'POST'
    search_post_params: Dict[str, str] = field(default_factory=dict)
    
    # Extraction d'éléments
    item_title_selector: str = ""
    item_link_selector: str = ""
    item_thumb_selector: str = ""
    
    # Détails & streaming
    details_title_selector: str = ""
    details_synopsis_selector: str = ""
    details_genre_selector: str = ""
    details_status_selector: str = ""
    details_thumb_selector: str = ""
    
    # Épisodes & Lecteurs
    episode_link_selector: str = ""
    episode_name_selector: str = ""
    video_iframe_regex: str = r'<iframe[^>]*\ssrc=["\']([^"\']+)["\']'
    raw_strings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceRecipe":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class AniyomiDexParser:
    """Analyseur pur-Python pour décompiler et convertir les règles de scraping d'un APK Aniyomi."""

    @staticmethod
    def parse_apk(apk_bytes: bytes, pkg_name: str = "", default_base_url: str = "") -> SourceRecipe:
        """Extrait classes.dex depuis un APK et analyse les méthodes de scraping."""
        recipe = SourceRecipe(pkg=pkg_name, base_url=default_base_url)
        try:
            with zipfile.ZipFile(io.BytesIO(apk_bytes)) as z:
                dex_names = [n for n in z.namelist() if n.endswith(".dex")]
                all_dex_data = [z.read(n) for n in dex_names]
        except Exception as e:
            logger.error("[dex_parser] Erreur ouverture ZIP de l'APK: %s", e)
            return recipe

        for dex in all_dex_data:
            try:
                AniyomiDexParser._parse_dex_data(dex, recipe)
            except Exception as e:
                logger.warning("[dex_parser] Erreur analyse DEX: %s", e)

        # Complétion heuristique si certains sélecteurs manquent
        AniyomiDexParser._fill_heuristics(recipe)
        return recipe

    @staticmethod
    def _read_uleb128(data: bytes, pos: int):
        val = 0
        shift = 0
        while True:
            b = data[pos]
            pos += 1
            val |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        return val, pos

    @staticmethod
    def _parse_dex_data(dex: bytes, recipe: SourceRecipe):
        if len(dex) < 0x70 or dex[:4] != b"dex\n":
            return

        # 1. String IDs
        string_ids_size, string_ids_off = struct.unpack_from("<II", dex, 0x38)
        strings = []
        for i in range(string_ids_size):
            off, = struct.unpack_from("<I", dex, string_ids_off + i * 4)
            pos = off
            while dex[pos] & 0x80:
                pos += 1
            pos += 1
            end = dex.find(b"\x00", pos)
            strings.append(dex[pos:end].decode("utf-8", errors="replace"))

        recipe.raw_strings = [s for s in strings if len(s) < 120 and any(c in s for c in [".", "/", "http", "div", "span", "a", "img", "search"])]

        # Recherche de baseUrl dans les chaînes si absente
        if not recipe.base_url:
            for s in strings:
                if (s.startswith("https://") or s.startswith("http://")) and not any(skip in s for skip in ["schemas.android.com", "w3.org", "github.com", "google.com"]):
                    recipe.base_url = s.rstrip("/")
                    break

        # 2. Type IDs
        type_ids_size, type_ids_off = struct.unpack_from("<II", dex, 0x40)
        types = [strings[struct.unpack_from("<I", dex, type_ids_off + i * 4)[0]] for i in range(type_ids_size)]

        # 3. Method IDs
        method_ids_size, method_ids_off = struct.unpack_from("<II", dex, 0x58)
        methods = []
        for i in range(method_ids_size):
            c_idx, p_idx, n_idx = struct.unpack_from("<HHI", dex, method_ids_off + i * 8)
            methods.append((types[c_idx], strings[n_idx]))

        # 4. Class Defs & Méthodes
        class_defs_size, class_defs_off = struct.unpack_from("<II", dex, 0x60)
        method_strings_map: Dict[str, List[str]] = {}

        for c in range(class_defs_size):
            class_idx, access_flags, superclass_idx, interfaces_off, source_file_idx, annotations_off, class_data_off, static_values_off = struct.unpack_from("<IIIIIIII", dex, class_defs_off + c * 32)
            if class_data_off == 0:
                continue

            pos = class_data_off
            num_static_fields, pos = AniyomiDexParser._read_uleb128(dex, pos)
            num_instance_fields, pos = AniyomiDexParser._read_uleb128(dex, pos)
            num_direct_methods, pos = AniyomiDexParser._read_uleb128(dex, pos)
            num_virtual_methods, pos = AniyomiDexParser._read_uleb128(dex, pos)

            # Ignore les champs
            for _ in range(num_static_fields + num_instance_fields):
                _, pos = AniyomiDexParser._read_uleb128(dex, pos)
                _, pos = AniyomiDexParser._read_uleb128(dex, pos)

            # Parcourt les méthodes directes et virtuelles
            for m_count in (num_direct_methods, num_virtual_methods):
                method_idx = 0
                for _ in range(m_count):
                    diff, pos = AniyomiDexParser._read_uleb128(dex, pos)
                    method_idx += diff
                    access_flags, pos = AniyomiDexParser._read_uleb128(dex, pos)
                    code_off, pos = AniyomiDexParser._read_uleb128(dex, pos)
                    if code_off > 0 and method_idx < len(methods):
                        m_class, m_name = methods[method_idx]
                        # Lecture code_item
                        registers_size, ins_size, outs_size, tries_size, debug_info_off, insns_size = struct.unpack_from("<HHHHII", dex, code_off)
                        insns_off = code_off + 16
                        insns = dex[insns_off:insns_off + insns_size * 2]

                        m_strings = []
                        ip = 0
                        while ip < len(insns) - 1:
                            op = insns[ip]
                            if op == 0x1A and ip + 3 < len(insns):  # const-string vAA, string@BBBB
                                str_idx, = struct.unpack_from("<H", insns, ip + 2)
                                if str_idx < len(strings):
                                    m_strings.append(strings[str_idx])
                                ip += 4
                            elif op == 0x1B and ip + 5 < len(insns):  # const-string/jumbo vAA, string@BBBBBBBB
                                str_idx, = struct.unpack_from("<I", insns, ip + 2)
                                if str_idx < len(strings):
                                    m_strings.append(strings[str_idx])
                                ip += 6
                            else:
                                ip += 2

                        if m_strings:
                            method_strings_map[m_name] = m_strings

        # 5. Mapping des chaînes extraites vers la recette
        for m_name, m_strs in method_strings_map.items():
            if "popularAnimeSelector" in m_name:
                recipe.popular_selector = m_strs[0]
            elif "popularAnimeNextPageSelector" in m_name:
                recipe.popular_next_selector = m_strs[0]
            elif "latestUpdatesSelector" in m_name:
                recipe.latest_selector = m_strs[0]
            elif "latestUpdatesNextPageSelector" in m_name:
                recipe.latest_next_selector = m_strs[0]
            elif "searchAnimeSelector" in m_name:
                recipe.search_selector = m_strs[0]
            elif "searchAnimeNextPageSelector" in m_name:
                recipe.search_next_selector = m_strs[0]
            elif "episodeListSelector" in m_name:
                recipe.episode_list_selector = m_strs[0]
            elif "popularAnimeRequest" in m_name:
                paths = [s for s in m_strs if s.startswith("/") or "?" in s]
                if paths:
                    recipe.popular_request_path = paths[-1]
            elif "latestUpdatesRequest" in m_name:
                paths = [s for s in m_strs if s.startswith("/") or "?" in s]
                if paths:
                    recipe.latest_request_path = paths[-1]
            elif "searchAnimeRequest" in m_name:
                for s in m_strs:
                    if s.startswith("/") or "?" in s:
                        recipe.search_request_path = s
                    elif s in ("s", "keyword", "story", "q", "query", "search", "title"):
                        recipe.search_query_param = s
                    if "POST" in m_strs or "FormBody" in m_strs or "do=search" in "".join(m_strs):
                        recipe.search_method = "POST"

        # Expressions régulières vidéo
        for s in strings:
            if "<iframe" in s:
                recipe.video_iframe_regex = s
                break

    @staticmethod
    def _fill_heuristics(recipe: SourceRecipe):
        """Remplit les sélecteurs manquants par déduction intelligente."""
        pkg_lower = (recipe.pkg or "").lower()
        base_lower = (recipe.base_url or "").lower()

        # Profils spécialisés pour les extensions populaires Aniyomi
        if "animesama" in pkg_lower or "anime-sama" in base_lower:
            recipe.search_selector = "#list_catalog > div, #list_catalog > div a, .catalog-card, #containerAjoutsAnimes > div"
            recipe.popular_selector = recipe.search_selector
            recipe.search_request_path = "/catalogue/?search={query}"
            recipe.search_query_param = "search"
            recipe.item_title_selector = ".card-title, h2, h3, img[alt]"
            recipe.item_thumb_selector = "img.card-image, img[src], img[data-src]"
            recipe.item_link_selector = "a[href]"
        elif "animevostfr" in pkg_lower or "animevostfr" in base_lower:
            recipe.search_selector = "div.ml-item, .film_list article"
            recipe.popular_selector = recipe.search_selector
            recipe.search_request_path = "/?s={query}"
            recipe.latest_request_path = "/filter-advance/page/1/?status=ongoing"
            recipe.episode_list_selector = "div#seasonss > div.les-title > a"
            recipe.item_title_selector = "span.mli-info > h2, h3, h2, .title"
            recipe.item_thumb_selector = "div.thumb > img, img[src]"
        elif "vostfree" in pkg_lower or "vostfree" in base_lower:
            recipe.search_method = "POST"
            recipe.search_request_path = "/index.php?do=search"
            recipe.search_selector = "#dle-content .search-result, #dle-content .movie-poster"
            recipe.latest_request_path = "/animes-vostfr/page/1/"
            recipe.popular_selector = recipe.search_selector
            recipe.episode_list_selector = "select.new_player_selector option"
            recipe.details_thumb_selector = "div.slide-poster img"
        elif "anisama" in pkg_lower or "animesz" in base_lower:
            recipe.search_selector = ".film_list article, .film_list .film-item"
            recipe.popular_selector = recipe.search_selector
            recipe.search_request_path = "/filter?keyword={query}"
            recipe.latest_request_path = "/recently-added/?page=1"
            recipe.item_title_selector = ".dynamic-name, h3, h2, .title"
            recipe.item_thumb_selector = ".film-poster-img, img[src]"
        elif "jetanime" in pkg_lower or "jetanime" in base_lower:
            recipe.search_selector = "div#archive-content > article > div.poster, div.search-page > div.result-item, article"
            recipe.popular_selector = recipe.search_selector
            recipe.search_request_path = "/?s={query}"
            recipe.episode_list_selector = "#seasons .episodiotitle a, .episodiotitle a, a[href*='/episodes/']"
        elif "voiranime" in pkg_lower or "voir-anime" in base_lower:
            recipe.search_selector = "div.c-tabs-item__content, article"
            recipe.popular_selector = recipe.search_selector
            recipe.search_request_path = "/?s={query}&post_type=wp-manga"

        # Détection générique depuis raw_strings si encore incomplet
        if not recipe.search_selector or not recipe.popular_selector:
            container_candidates = []
            for s in recipe.raw_strings:
                s_clean = s.strip()
                if not s_clean or len(s_clean) < 3 or len(s_clean) > 80:
                    continue
                if s_clean.startswith(('http', '//', '(', 'L', '[L', '#EXT', '"', '%.', 'data:', 'android.')):
                    continue
                if re.search(r'[\(\)\{\}\*\+\?\$\\\^]', s_clean):
                    continue
                if any(k in s_clean for k in ['#list_catalog', 'containerAjouts', 'catalog-card', 'ml-item', 'film_list', 'archive-content', 'c-tabs-item', 'result-item', 'movie-poster']):
                    container_candidates.append(s_clean)
                elif s_clean.startswith(('#', '.', 'div', 'article')) and any(c in s_clean for c in ['#', '.', '>', ' ']):
                    if any(w in s_clean for w in ['poster', 'card', 'item', 'content', 'article', 'thumb', 'entry']):
                        container_candidates.append(s_clean)

            if container_candidates:
                chosen_selector = ", ".join(dict.fromkeys(container_candidates))
                if not recipe.search_selector:
                    recipe.search_selector = chosen_selector
                if not recipe.popular_selector:
                    recipe.popular_selector = chosen_selector

        if not recipe.search_selector and recipe.popular_selector:
            recipe.search_selector = recipe.popular_selector
        if not recipe.latest_selector and recipe.popular_selector:
            recipe.latest_selector = recipe.popular_selector

        # Format de recherche
        if not recipe.search_request_path:
            if "search" in recipe.raw_strings and "/catalogue/" in recipe.raw_strings:
                recipe.search_request_path = "/catalogue/?search={query}"
                recipe.search_query_param = "search"
            elif recipe.search_query_param:
                recipe.search_request_path = f"/?{recipe.search_query_param}={{query}}"
            else:
                recipe.search_request_path = "/?s={query}"

        # Éléments enfants par défaut
        if not recipe.item_title_selector:
            recipe.item_title_selector = "h3, h2, .title, .post-title, a.title, .entry-title, .card-title, img[alt]"
        if not recipe.item_link_selector:
            recipe.item_link_selector = "a[href]"
        if not recipe.item_thumb_selector:
            recipe.item_thumb_selector = "img[src], img[data-src], img[loading], .poster img"
        if not recipe.episode_link_selector:
            recipe.episode_link_selector = "a[href], option"
        if not recipe.episode_name_selector:
            recipe.episode_name_selector = "a, span, option"
