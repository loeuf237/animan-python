import asyncio
from contextlib import contextmanager
import json
import logging
import os
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse, urljoin
import httpx

from animan.config import settings
from animan.services.aniyomi_dex_parser import AniyomiDexParser, SourceRecipe
from animan.services.aniyomi_container import AniyomiContainerSource

logger = logging.getLogger("animan.extensions")

EXTENSIONS_DIR = Path.home() / ".animan" / "extensions"
APKS_DIR = EXTENSIONS_DIR / "apks"
EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
APKS_DIR.mkdir(parents=True, exist_ok=True)


class ExtensionService:
    """Service de gestion des dépôts et extensions Aniyomi compatibles."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self._active_container_sources: Dict[str, AniyomiContainerSource] = {}
        self._init_db()
        self._load_enabled_sources()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initialise les tables de dépôts et d'extensions dans SQLite."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS extension_repos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS imported_extensions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_id INTEGER NOT NULL,
                    pkg TEXT NOT NULL,
                    name TEXT NOT NULL,
                    lang TEXT NOT NULL,
                    version TEXT,
                    apk_url TEXT,
                    base_url TEXT,
                    icon_url TEXT,
                    sources_meta TEXT,
                    is_enabled INTEGER DEFAULT 0,
                    recipe_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (repo_id) REFERENCES extension_repos(id) ON DELETE CASCADE,
                    UNIQUE(repo_id, pkg)
                );
            """)
            conn.commit()

    # -------------------------------------------------------------------------
    # Gestion des dépôts
    # -------------------------------------------------------------------------

    async def import_repository(self, repo_url: str) -> Dict[str, Any]:
        """Importe massivement un catalogue d'extensions depuis une URL compatible Aniyomi (index.min.json).
        RÈGLE : Le dépôt nouvellement importé devient le seul magasin actif.
        RÈGLE : Toutes les sources importées sont désactivées par défaut (is_enabled = 0).
        """
        clean_url = repo_url.strip()
        if not clean_url:
            raise ValueError("L'URL du magasin d'extensions ne peut pas être vide.")

        # Normalisation si l'URL ne pointe pas directement vers index.min.json
        if not clean_url.endswith(".json"):
            clean_url = clean_url.rstrip("/") + "/index.min.json"

        logger.info("[extensions] Téléchargement du magasin d'extensions: %s", clean_url)

        # Téléchargement de l'index
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=settings.SSL_VERIFY, follow_redirects=True) as client:
                resp = await client.get(clean_url, headers={"User-Agent": settings.DEFAULT_USER_AGENT})
                if resp.status_code != 200:
                    raise ValueError(f"Impossible de joindre le magasin (HTTP {resp.status_code})")
                data = resp.json()
        except Exception as e:
            logger.error("[extensions] Échec téléchargement index: %s", e)
            raise ValueError(f"Erreur lors de la récupération du catalogue: {e}")

        if not isinstance(data, list):
            raise ValueError("Le format de l'index du magasin est invalide (liste attendue).")

        # Déduction du nom du dépôt et de la racine des APKs
        parsed_url = urlparse(clean_url)
        path_parts = parsed_url.path.strip("/").split("/")
        repo_name = "Magasin Aniyomi"
        if len(path_parts) >= 2:
            repo_name = f"{path_parts[0]}/{path_parts[1]}"
        elif parsed_url.netloc:
            repo_name = f"Dépôt {parsed_url.netloc}"

        # Racine relative pour les APKs
        # Ex: https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json -> https://raw.githubusercontent.com/yuzono/anime-repo/repo/apk/
        repo_base = clean_url.rsplit("/", 1)[0]
        apk_base_dir = f"{repo_base}/apk"

        # Insertion en base et bascule du magasin actif
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 1. RÈGLE : Désactive tous les dépôts existants
            cursor.execute("UPDATE extension_repos SET is_active = 0;")

            # 2. Insère ou réactive le dépôt ciblé
            cursor.execute("""
                INSERT INTO extension_repos (url, name, is_active, created_at)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(url) DO UPDATE SET
                    name = excluded.name,
                    is_active = 1,
                    created_at = CURRENT_TIMESTAMP;
            """, (clean_url, repo_name))

            cursor.execute("SELECT id FROM extension_repos WHERE url = ?;", (clean_url,))
            repo_id = cursor.fetchone()["id"]

            # 3. Importe massivement toutes les extensions (désactivées par défaut)
            imported_count = 0
            for item in data:
                pkg = item.get("pkg") or ""
                name = item.get("name") or pkg
                lang = item.get("lang") or "all"
                version = item.get("version") or str(item.get("code") or "1.0")
                raw_apk = item.get("apk") or ""

                if raw_apk.startswith("http"):
                    apk_url = raw_apk
                elif raw_apk:
                    apk_url = f"{apk_base_dir}/{raw_apk}"
                else:
                    apk_url = ""

                sources = item.get("sources") or []
                base_url = ""
                if sources and isinstance(sources, list) and isinstance(sources[0], dict):
                    base_url = sources[0].get("baseUrl") or ""

                icon_url = ""
                icon_file = item.get("icon")
                if icon_file:
                    icon_url = f"{repo_base}/icon/{icon_file}" if not icon_file.startswith("http") else icon_file

                cursor.execute("""
                    INSERT INTO imported_extensions (
                        repo_id, pkg, name, lang, version, apk_url, base_url, icon_url, sources_meta, is_enabled
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(repo_id, pkg) DO UPDATE SET
                        name = excluded.name,
                        lang = excluded.lang,
                        version = excluded.version,
                        apk_url = excluded.apk_url,
                        base_url = excluded.base_url,
                        icon_url = excluded.icon_url,
                        sources_meta = excluded.sources_meta;
                """, (
                    repo_id, pkg, name, lang, version, apk_url, base_url, icon_url, json.dumps(sources)
                ))
                imported_count += 1

            conn.commit()

        # Réinitialise le cache des sources en mémoire pour ne conserver que celles du dépôt actif
        self._load_enabled_sources()

        logger.info("[extensions] %d extensions importées depuis %s (Toutes désactivées par défaut)", imported_count, repo_name)
        return {
            "success": True,
            "repo_id": repo_id,
            "repo_name": repo_name,
            "repo_url": clean_url,
            "count": imported_count,
        }

    def get_active_repository(self) -> Optional[Dict[str, Any]]:
        """Retourne le dernier magasin d'extensions ajouté (seul actif)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM extension_repos WHERE is_active = 1 ORDER BY id DESC LIMIT 1;")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_visible_extensions(self, query: Optional[str] = None, lang: Optional[str] = None, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """Retourne uniquement les extensions présentes dans le dernier magasin ajouté."""
        active_repo = self.get_active_repository()
        if not active_repo:
            return []

        repo_id = active_repo["id"]
        sql = "SELECT * FROM imported_extensions WHERE repo_id = ?"
        params: List[Any] = [repo_id]

        if query:
            sql += " AND (name LIKE ? OR pkg LIKE ? OR base_url LIKE ?)"
            q_like = f"%{query.strip()}%"
            params.extend([q_like, q_like, q_like])

        if lang and lang != "all":
            sql += " AND lang = ?"
            params.append(lang.lower().strip())

        if enabled_only:
            sql += " AND is_enabled = 1"

        sql += " ORDER BY is_enabled DESC, lang = 'fr' DESC, name ASC;"

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Activation & Compilation de Recette
    # -------------------------------------------------------------------------

    async def toggle_extension(self, ext_id: int, enabled: bool) -> Dict[str, Any]:
        """Active ou désactive manuellement une extension du magasin actif."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM imported_extensions WHERE id = ?;", (ext_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("Extension introuvable.")

            ext_data = dict(row)
            pkg = ext_data["pkg"]

            if enabled:
                # Si activée et recette non encore compilée, télécharger l'APK et compiler
                recipe_dict = None
                if ext_data.get("recipe_json"):
                    try:
                        recipe_dict = json.loads(ext_data["recipe_json"])
                    except Exception:
                        pass

                if not recipe_dict:
                    recipe_dict = await self._compile_extension_recipe(ext_data)
                    cursor.execute("UPDATE imported_extensions SET recipe_json = ?, is_enabled = 1 WHERE id = ?;", (json.dumps(recipe_dict), ext_id))
                else:
                    cursor.execute("UPDATE imported_extensions SET is_enabled = 1 WHERE id = ?;", (ext_id,))

                recipe = SourceRecipe.from_dict(recipe_dict)
                self._active_container_sources[pkg] = AniyomiContainerSource(recipe)
                logger.info("[extensions] Extension activée: %s (%s)", ext_data["name"], pkg)
            else:
                cursor.execute("UPDATE imported_extensions SET is_enabled = 0 WHERE id = ?;", (ext_id,))
                self._active_container_sources.pop(pkg, None)
                logger.info("[extensions] Extension désactivée: %s (%s)", ext_data["name"], pkg)

            conn.commit()

        return {
            "success": True,
            "id": ext_id,
            "pkg": pkg,
            "is_enabled": enabled,
            "name": ext_data["name"],
        }

    async def _compile_extension_recipe(self, ext_data: Dict[str, Any]) -> Dict[str, Any]:
        """Télécharge l'APK et extrait la recette de scraping via AniyomiDexParser."""
        apk_url = ext_data.get("apk_url") or ""
        pkg = ext_data.get("pkg") or ""
        base_url = ext_data.get("base_url") or ""
        name = ext_data.get("name") or pkg
        lang = ext_data.get("lang") or "all"

        apk_bytes = b""
        local_apk = APKS_DIR / f"{pkg}.apk"

        if local_apk.exists() and local_apk.stat().st_size > 1000:
            apk_bytes = local_apk.read_bytes()
        elif apk_url:
            logger.info("[extensions] Téléchargement APK pour %s depuis %s", name, apk_url)
            try:
                async with httpx.AsyncClient(timeout=25.0, verify=settings.SSL_VERIFY, follow_redirects=True) as client:
                    resp = await client.get(apk_url, headers={"User-Agent": settings.DEFAULT_USER_AGENT})
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        apk_bytes = resp.content
                        local_apk.write_bytes(apk_bytes)
            except Exception as e:
                logger.warning("[extensions] Échec téléchargement APK pour %s: %s", name, e)

        if apk_bytes:
            recipe = AniyomiDexParser.parse_apk(apk_bytes, pkg_name=pkg, default_base_url=base_url)
        else:
            # Recette heuristique basée sur les métadonnées déclarées
            recipe = SourceRecipe(pkg=pkg, base_url=base_url)
            AniyomiDexParser._fill_heuristics(recipe)

        recipe.name = name
        recipe.lang = lang
        return recipe.to_dict()

    def _load_enabled_sources(self):
        """Charge au démarrage toutes les sources activées du magasin actif."""
        self._active_container_sources.clear()
        active_repo = self.get_active_repository()
        if not active_repo:
            return

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM imported_extensions WHERE repo_id = ? AND is_enabled = 1;", (active_repo["id"],))
            rows = cursor.fetchall()
            for r in rows:
                ext = dict(r)
                if ext.get("recipe_json"):
                    try:
                        recipe_data = json.loads(ext["recipe_json"])
                        recipe = SourceRecipe.from_dict(recipe_data)
                        self._active_container_sources[ext["pkg"]] = AniyomiContainerSource(recipe)
                    except Exception as e:
                        logger.warning("[extensions] Erreur chargement source %s: %s", ext["name"], e)

        logger.info("[extensions] %d source(s) Aniyomi activée(s) en mémoire", len(self._active_container_sources))

    # -------------------------------------------------------------------------
    # Accesseurs pour le coeur d'Animan
    # -------------------------------------------------------------------------

    def get_enabled_container_sources(self) -> List[AniyomiContainerSource]:
        """Retourne la liste des conteneurs de sources actuellement activés."""
        return list(self._active_container_sources.values())

    def get_container_source_by_id(self, source_id: str) -> Optional[AniyomiContainerSource]:
        """Recherche une source active par identifiant ou nom de package."""
        if not source_id:
            return None
        sid = source_id.lower().strip()
        for k, src in self._active_container_sources.items():
            if k.lower() == sid or src.name.lower() == sid or src.pkg.lower() == sid or sid in k.lower():
                return src
        return None

    def get_allowed_domains(self) -> Set[str]:
        """Retourne les domaines des sources activées pour la whitelist SSRF."""
        domains = set()
        for src in self._active_container_sources.values():
            if src.base_url:
                try:
                    host = urlparse(src.base_url).hostname
                    if host:
                        domains.add(host.lower())
                except Exception:
                    pass
        return domains


extension_service = ExtensionService()
