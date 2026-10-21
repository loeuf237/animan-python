from animan.services.extension_observability import save_recipe_revision,extension_observability,HEALTH_MESSAGES
from animan.database import init_db, sqlite_connection
from animan.services.source_http import source_http, VerificationRequired
import asyncio
import json
import logging
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse, urljoin
import httpx

from animan.security import is_safe_url
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

    def _get_conn(self):
        return sqlite_connection(self.db_path)

    def _init_db(self):
        init_db(self.db_path)

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
        if not urlparse(clean_url).path.endswith(".json"):
            clean_url = clean_url.rstrip("/") + "/index.min.json"

        logger.info("[extensions] Downloading extension repository: %s", clean_url)

        # Téléchargement de l'index
        try:
            async with source_http.async_client(timeout=15.0, verify=settings.SSL_VERIFY, follow_redirects=True, event_hooks={"request": [self._validate_request]}) as client:
                resp = await client.get(clean_url, headers={"User-Agent": settings.DEFAULT_USER_AGENT})
                if resp.status_code != 200:
                    raise ValueError(f"Impossible de joindre le magasin (HTTP {resp.status_code})")
                data = resp.json()
        except VerificationRequired:
            raise
        except Exception as e:
            logger.error("[extensions] Failed downloading repository index: %s", e)
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
            seen_packages = set()
            for item in data:
                if not isinstance(item, dict):
                    continue
                pkg = item.get("pkg") or ""
                if not isinstance(pkg, str) or not re.fullmatch(r"[A-Za-z0-9_.]+", pkg) or pkg in seen_packages:
                    continue
                seen_packages.add(pkg)
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
                        recipe_json = CASE WHEN version IS NOT excluded.version OR base_url IS NOT excluded.base_url OR apk_url IS NOT excluded.apk_url THEN NULL ELSE recipe_json END,
                        version = excluded.version,
                        apk_url = excluded.apk_url,
                        base_url = excluded.base_url,
                        icon_url = excluded.icon_url,
                        sources_meta = excluded.sources_meta;
                """, (
                    repo_id, pkg, name, lang, version, apk_url, base_url, icon_url, json.dumps(sources)
                ))
                imported_count += 1

            if not seen_packages:
                raise ValueError("Le dépôt ne contient aucune extension valide.")
            placeholders = ",".join("?" for _ in seen_packages)
            cursor.execute(f"DELETE FROM imported_extensions WHERE repo_id = ? AND pkg NOT IN ({placeholders})", (repo_id, *seen_packages))
            conn.commit()

        # Réinitialise le cache des sources en mémoire pour ne conserver que celles du dépôt actif
        self._load_enabled_sources()

        logger.info("[extensions] %d extensions imported from %s (All disabled by default)", imported_count, repo_name)
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
            entries=[dict(r) for r in rows]
            for entry in entries:
                entry['health']=extension_observability.health(conn,entry['id'])
            return entries

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
            active = self.get_active_repository()
            if not active or active["id"] != ext_data["repo_id"]:
                raise ValueError("Cette extension appartient à un dépôt inactif.")
            pkg = ext_data["pkg"]

            if enabled:
                # Si activée et recette non encore compilée, télécharger l'APK et compiler
                recipe_dict = None
                if ext_data.get("recipe_json"):
                    try:
                        recipe_dict = json.loads(ext_data["recipe_json"])
                    except VerificationRequired:
                        raise
                    except Exception:
                        pass

                if not recipe_dict:
                    recipe_dict = await self._compile_extension_recipe(ext_data)
                    cursor.execute("UPDATE imported_extensions SET recipe_json = ?, is_enabled = 1 WHERE id = ?;", (json.dumps(recipe_dict), ext_id))
                else:
                    cursor.execute("UPDATE imported_extensions SET is_enabled = 1 WHERE id = ?;", (ext_id,))

                recipe = SourceRecipe.from_dict(recipe_dict)
                if not recipe.base_url or not await asyncio.to_thread(is_safe_url, recipe.base_url):
                    raise ValueError("Aucune adresse de source valide : configurez sa recette avant activation.")
                source=AniyomiContainerSource(recipe)
                source._diagnostics_db_path=self.db_path
                source._diagnostics_recipe_revision=save_recipe_revision(conn,ext_id,source.recipe.to_dict(),'activate')
                self._active_container_sources[pkg] = source
                logger.info("[extensions] Extension enabled: %s (%s)", ext_data["name"], pkg)
            else:
                cursor.execute("UPDATE imported_extensions SET is_enabled = 0 WHERE id = ?;", (ext_id,))
                self._active_container_sources.pop(pkg, None)
                logger.info("[extensions] Extension disabled: %s (%s)", ext_data["name"], pkg)

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
        import hashlib
        cache_id = hashlib.sha256(f"{pkg}:{ext_data.get('version')}:{apk_url}".encode()).hexdigest()
        local_apk = APKS_DIR / f"{cache_id}.apk"

        if local_apk.exists() and local_apk.stat().st_size > 1000:
            apk_bytes = local_apk.read_bytes()
        elif apk_url:
            logger.info("[extensions] Downloading APK for %s from %s", name, apk_url)
            try:
                async with source_http.async_client(timeout=25.0, verify=settings.SSL_VERIFY, follow_redirects=True, event_hooks={"request": [self._validate_request]}) as client:
                    resp = await client.get(apk_url, headers={"User-Agent": settings.DEFAULT_USER_AGENT})
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        apk_bytes = resp.content
                        local_apk.write_bytes(apk_bytes)
            except VerificationRequired:
                raise
            except Exception as e:
                logger.warning("[extensions] Failed downloading APK for %s: %s", name, e)

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
        loaded = {}
        failures = []
        active_repo = self.get_active_repository()
        if not active_repo:
            self._active_container_sources = loaded
            return

        with self._get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM imported_extensions WHERE repo_id = ? AND is_enabled = 1;", (active_repo["id"],))
            rows = cursor.fetchall()
            for r in rows:
                ext = dict(r)
                if not ext.get("recipe_json"):
                    recipe = SourceRecipe(pkg=ext["pkg"], name=ext["name"], base_url=ext["base_url"] or "", lang=ext["lang"])
                    AniyomiDexParser._fill_heuristics(recipe)
                    if recipe.base_url:
                        loaded[ext["pkg"]] = AniyomiContainerSource(recipe)
                        effective=loaded[ext['pkg']].recipe.to_dict()
                        conn.execute('UPDATE imported_extensions SET recipe_json=? WHERE id=?',(json.dumps(effective),ext['id']))
                        loaded[ext['pkg']]._diagnostics_recipe_revision=save_recipe_revision(conn,ext['id'],effective,'load')
                        conn.execute("DELETE FROM extension_health WHERE ext_id=? AND operation='load'",(ext['id'],))
                if ext.get("recipe_json"):
                    try:
                        recipe_data = json.loads(ext["recipe_json"])
                        recipe = SourceRecipe.from_dict(recipe_data)
                        AniyomiDexParser._fill_heuristics(recipe)
                        # Keep user-defined paths/selectors; fill only missing values.
                        recipe = SourceRecipe.from_dict({**recipe.to_dict(), **{key: value for key, value in recipe_data.items() if value not in ("", None, [])}})
                        updated_dict = recipe.to_dict()
                        if updated_dict != recipe_data:
                            save_recipe_revision(conn,ext['id'],recipe_data,'legacy')
                            cursor.execute("UPDATE imported_extensions SET recipe_json = ? WHERE id = ?;", (json.dumps(updated_dict), ext["id"]))
                        loaded[ext["pkg"]] = AniyomiContainerSource(recipe)
                        effective=loaded[ext['pkg']].recipe.to_dict()
                        cursor.execute('UPDATE imported_extensions SET recipe_json=? WHERE id=?',(json.dumps(effective),ext['id']))
                        loaded[ext['pkg']]._diagnostics_recipe_revision=save_recipe_revision(conn,ext['id'],effective,'load')
                        conn.execute("DELETE FROM extension_health WHERE ext_id=? AND operation='load'",(ext['id'],))
                    except Exception as e:
                        failures.append((ext, e))
                        logger.warning("[extensions] Error loading source %s: %s", ext["name"], type(e).__name__)

        for ext,error in failures:
            extension_observability.record(ext['pkg'],'load',error=error,db_path=self.db_path)
        for source in loaded.values(): source._diagnostics_db_path = self.db_path
        self._active_container_sources = loaded
        logger.info("[extensions] %d Aniyomi source(s) enabled in memory", len(self._active_container_sources))

    # -------------------------------------------------------------------------
    # Accesseurs pour le coeur d'Animan
    # -------------------------------------------------------------------------

    @staticmethod
    async def _validate_request(request):
        if not await asyncio.to_thread(is_safe_url, str(request.url)):
            raise ValueError("URL du dépôt ou de l’APK non autorisée.")

    async def configure_extension(self, ext_id: int, data: Dict[str, Any], *, revision_reason='configure', force_revision=False):
        unknown = set(data) - set(SourceRecipe.__dataclass_fields__)
        if unknown:
            raise ValueError("Champs de recette inconnus : " + ", ".join(sorted(unknown)))
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM imported_extensions WHERE id = ?", (ext_id,)).fetchone()
            active = self.get_active_repository()
            if not row or not active or row["repo_id"] != active["id"]:
                raise ValueError("Extension introuvable dans le dépôt actif.")
            existing = json.loads(row["recipe_json"] or "{}")
            previous = dict(existing)
            existing.update(data)
            existing.update(pkg=row["pkg"], name=row["name"], lang=row["lang"])
            recipe = SourceRecipe.from_dict(existing)
            if not isinstance(recipe.base_url, str) or not await asyncio.to_thread(is_safe_url, recipe.base_url):
                raise ValueError("URL de source invalide.")
            from bs4 import BeautifulSoup
            import re
            for key, value in recipe.to_dict().items():
                if key.endswith("selector"):
                    if not isinstance(value, str):
                        raise ValueError("Les sélecteurs doivent être du texte.")
                    if value:
                        try:
                            BeautifulSoup("", "html.parser").select(value)
                        except VerificationRequired:
                            raise
                        except Exception as exc:
                            raise ValueError(f"Sélecteur invalide : {key}") from exc
            try:
                re.compile(recipe.video_iframe_regex)
            except (TypeError, re.error) as exc:
                raise ValueError("Expression de lecteur invalide.") from exc
            conn.execute('BEGIN IMMEDIATE')
            if previous: save_recipe_revision(conn,ext_id,previous,'legacy')
            conn.execute("UPDATE imported_extensions SET recipe_json = ?, base_url = ? WHERE id = ?",
                         (json.dumps(recipe.to_dict()), recipe.base_url, ext_id))
            save_recipe_revision(conn,ext_id,recipe.to_dict(),revision_reason,force=force_revision)
        self._load_enabled_sources()
        return {"success": True, "id": ext_id}

    async def diagnose_extension(self, ext_id: int):
        ext = next((ext for ext in self.get_visible_extensions() if ext["id"] == ext_id), None)
        if not ext:
            raise ValueError("Extension introuvable dans le dépôt actif.")
        recipe = SourceRecipe.from_dict(json.loads(ext["recipe_json"])) if ext.get("recipe_json") else SourceRecipe(
            pkg=ext["pkg"], name=ext["name"], base_url=ext["base_url"] or "", lang=ext["lang"])
        stored = recipe.to_dict()
        AniyomiDexParser._fill_heuristics(recipe)
        if ext.get("recipe_json"):
            recipe = SourceRecipe.from_dict({**recipe.to_dict(), **{k: v for k, v in stored.items() if v not in ("", None, [])}})
        source = AniyomiContainerSource(recipe)
        from animan.services.source_registry import source_registry
        from animan.services.extension_observability import classify
        source._diagnostics_db_path=self.db_path
        source._diagnostics_recipe_revision=ext['recipe_revision']
        provider=source_registry.describe(ext['pkg'],source)
        try:
            results = await asyncio.wait_for(provider.get_latest_releases(), timeout=20)
        except VerificationRequired:
            raise
        except Exception as exc:
            status,code=classify(exc)
            from animan.api_errors import APIProblem
            if isinstance(exc,(TimeoutError,APIProblem)):
                extension_observability.record(ext['pkg'],'latest',error=exc,db_path=self.db_path,base_url=source.base_url,recipe_revision=ext['recipe_revision'])
            return {'success':False,'count':0,'status':status,'code':code,'message':HEALTH_MESSAGES[status]}
        return {'success':bool(results),'count':len(results),'status':'healthy' if results else 'empty',
                'message':HEALTH_MESSAGES['healthy' if results else 'empty']}

    def recipe_history(self,ext_id):
        if not any(ext['id']==ext_id for ext in self.get_visible_extensions()):
            raise ValueError('Extension introuvable dans le dépôt actif.')
        with self._get_conn() as conn:
            return {'revisions':extension_observability.history(conn,ext_id)}

    async def restore_recipe(self,ext_id,revision):
        self.recipe_history(ext_id)
        with self._get_conn() as conn:
            row=conn.execute('SELECT recipe_json FROM extension_recipe_versions WHERE ext_id=? AND revision=?',(ext_id,revision)).fetchone()
        if not row: raise ValueError('Révision de recette introuvable.')
        # Restore creates a new revision; the historical snapshot is immutable.
        return await self.configure_extension(ext_id,json.loads(row['recipe_json']),revision_reason='restore',force_revision=True)

    def get_enabled_container_sources(self) -> List[AniyomiContainerSource]:
        """Retourne la liste des conteneurs de sources actuellement activés."""
        return list(self._active_container_sources.values())

    def get_container_source_by_id(self, source_id: str) -> Optional[AniyomiContainerSource]:
        """Recherche une source active par identifiant ou nom de package."""
        if not source_id:
            return None
        sid = source_id.lower().strip()
        for k, src in self._active_container_sources.items():
            if k.lower() == sid or src.name.lower() == sid or src.pkg.lower() == sid:
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
