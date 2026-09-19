import json
import logging
import sqlite3
from typing import Dict, Any, List, Optional
from animan.config import settings

logger = logging.getLogger("animan.sources")


class SourceSettingsService:
    """Service de gestion et de persistance des configurations par source d'anime.
    Prend en charge les sources natives d'Animan (voir-anime, animepahe, french-manga)
    ainsi que l'ensemble des sources/extensions importées (conteneurs Aniyomi).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Crée la table source_settings si elle n'existe pas encore."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS source_settings (
                        source_id TEXT PRIMARY KEY,
                        settings_json TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
        except Exception as e:
            logger.error("[source_settings] Erreur initialisation table: %s", e)

    def get_source_settings(self, source_id: str) -> Dict[str, Any]:
        """Retourne les paramètres enregistrés pour une source spécifique."""
        sid = (source_id or "").strip().lower()
        if not sid:
            return {}

        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT settings_json FROM source_settings WHERE LOWER(source_id) = ?;", (sid,))
                row = cursor.fetchone()
                if row and row["settings_json"]:
                    return json.loads(row["settings_json"])
        except Exception as e:
            logger.debug("[source_settings] Erreur lecture settings pour %s: %s", sid, e)

        # Paramètres par défaut selon la source
        if sid in ["voir-anime", "voiranime"]:
            return {
                "quality_strategy": "highest",  # "highest" ou "lowest"
                "default_server": "auto",
            }
        return {}

    def save_source_settings(self, source_id: str, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Enregistre ou met à jour les paramètres d'une source."""
        sid = (source_id or "").strip().lower()
        if not sid:
            raise ValueError("L'identifiant de la source ne peut pas être vide.")

        current = self.get_source_settings(sid)
        current.update(new_settings)

        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO source_settings (source_id, settings_json, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(source_id) DO UPDATE SET
                        settings_json = excluded.settings_json,
                        updated_at = CURRENT_TIMESTAMP;
                """, (sid, json.dumps(current)))
                conn.commit()
            logger.info("[source_settings] Paramètres enregistrés pour source '%s': %s", sid, current)
        except Exception as e:
            logger.error("[source_settings] Erreur enregistrement settings pour %s: %s", sid, e)
            raise

        return current

    def get_all_sources_with_settings(self) -> List[Dict[str, Any]]:
        """Retourne l'ensemble des sources disponibles (natives et extensions importées)
        avec leurs métadonnées et paramètres actuels.
        """
        sources_list: List[Dict[str, Any]] = []

        # 1. Sources natives d'Animan
        native_sources = [
            {
                "id": "voir-anime",
                "name": "VoirAnime",
                "type": "native",
                "lang": "fr",
                "icon": "https://voir-anime.to/favicon.ico",
                "badge": "Français (VF / VOSTFR)",
                "description": "Source francophone avec multiples lecteurs (myTV, VOE, Streamtape, FHD1, MOON).",
                "has_custom_settings": True,
            },
            {
                "id": "animepahe",
                "name": "AnimePahe",
                "type": "native",
                "lang": "en",
                "icon": "https://animepahe.ru/favicon.ico",
                "badge": "Multilingue (Kwik)",
                "description": "Plateforme ultra-rapide avec flux encodés légers Kwik.",
                "has_custom_settings": False,
            },
            {
                "id": "french-manga",
                "name": "French-Manga",
                "type": "native",
                "lang": "fr",
                "icon": "https://french-manga.net/favicon.ico",
                "badge": "Français (VF / VOSTFR)",
                "description": "Catalogue anime historique Vidzy et lecteurs directs.",
                "has_custom_settings": False,
            },
        ]

        for s in native_sources:
            s["settings"] = self.get_source_settings(s["id"])
            sources_list.append(s)

        # 2. Extensions Aniyomi importées
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, pkg, name, lang, version, apk_url, base_url, icon_url, is_enabled
                    FROM imported_extensions
                    ORDER BY is_enabled DESC, name ASC;
                """)
                rows = cursor.fetchall()
                for r in rows:
                    ext = dict(r)
                    ext_id = ext["pkg"]
                    sources_list.append({
                        "id": ext_id,
                        "name": ext["name"],
                        "type": "imported",
                        "lang": ext["lang"],
                        "version": ext["version"],
                        "icon": ext["icon_url"] or "",
                        "baseUrl": ext["base_url"] or "",
                        "badge": f"Extension Aniyomi ({ext['lang'].upper()})",
                        "isEnabled": bool(ext["is_enabled"]),
                        "description": f"Extension Aniyomi importée ({ext['pkg']}).",
                        "has_custom_settings": False,
                        "settings": self.get_source_settings(ext_id),
                    })
        except Exception as e:
            logger.debug("[source_settings] Impossible de lister les extensions importées: %s", e)

        return sources_list


source_settings_service = SourceSettingsService()
