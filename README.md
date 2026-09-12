# Animan (Python Edition)

Animan est une application web moderne développée avec **FastAPI** et **Python 3** pour rechercher des animes, explorer leurs épisodes, gérer une bibliothèque personnelle et télécharger des épisodes avec reprise, contrôle de débit et gestion multi-flux.

Cette version Python remplace l'implémentation Java/Spring Boot d'origine en conservant 100% de la parité fonctionnelle, de l'interface utilisateur et des APIs, tout en offrant une architecture légère, réactive et sans dépendances lourdes (aucun navigateur headless ou Playwright requis).

---

## ✨ Fonctionnalités

- **Sources multiples** : Scraping asynchrone et résilient pour `french-manga.net` et `voir-anime.to`.
- **Catalogue & Recherche** : Recherche instantanée d'animes, consultation des fiches, versions (VOSTFR, VF) et listings d'épisodes.
- **Téléchargement avancé** :
  - File d'attente asynchrone (`asyncio.Queue`) avec gestion de la concurrence.
  - Reprise de téléchargement partiel via en-têtes HTTP `Range` (`Content-Range`).
  - Téléchargement et concaténation automatique des flux segmentés (`.ts` / myTV).
  - Téléchargement des pistes de sous-titres et muxing automatique en conteneur `.mkv` via FFmpeg (si disponible).
  - Génération de fichiers d'informations `.nfo` pour organisation Plex / Jellyfin.
  - Limitation de bande passante globale et par tâche (token bucket throttling).
  - Planification horaire des téléchargements.
- **Streaming & Lecteur intégré** :
  - Lecteur vidéo web avec prise en charge complète du seeking (`HTTP 206 Partial Content`).
  - Diffusion des pistes de sous-titres (`/api/media/subtitle/{id}`).
- **Bibliothèque & Suivi** :
  - Suivi des animes favoris et progression de lecture / téléchargement.
  - Tâche de fond périodique (Watchdog) pour télécharger automatiquement les nouveaux épisodes des séries suivies.
  - Historique complet des téléchargements avec persistance SQLite.
- **Temps réel** : Mises à jour de la file de téléchargement et de la vitesse transmises en direct via **Server-Sent Events (SSE)**.

---

## 🛠️ Stack Technique

- **Langage** : Python 3.10+ (compatible Python 3.14)
- **Framework Web** : [FastAPI](https://fastapi.tiangolo.com/) & [Uvicorn](https://www.uvicorn.org/)
- **Moteur de Templates** : [Jinja2](https://jinja.palletsprojects.com/)
- **Client HTTP Asynchrone** : [HTTPX](https://www.python-httpx.org/)
- **Parsing & Scraping** : [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) & [lxml](https://lxml.de/)
- **Base de Données & ORM** : SQLite & [SQLAlchemy](https://www.sqlalchemy.org/)
- **Streaming & Tâches** : Python standard `asyncio` & SSE (`sse-starlette`)
- **Tests** : [pytest](https://docs.pytest.org/) & [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)

---

## 🚀 Installation & Démarrage

### 1. Prérequis

- Python 3.10 ou supérieur (`python3 --version`)
- FFmpeg (optionnel, uniquement pour le muxing de sous-titres dans les fichiers vidéo)

### 2. Installation des dépendances

Dans le répertoire du projet :

```bash
pip install -r requirements.txt
```

### 3. Lancement du serveur

Utilisez le script `run.sh` ou directement `run.py` :

```bash
./run.sh
```

ou :

```bash
python3 run.py
```

L'application démarre sur :
👉 **http://localhost:8080**

---

## 📁 Architecture du Projet

```text
Animan/
├── animan/                     # Package principal Python
│   ├── config.py               # Paramètres de configuration (dossiers, timeouts, ports)
│   ├── database.py             # Session SQLAlchemy & initialisation SQLite
│   ├── models/                 # Modèles SQLAlchemy & Pydantic
│   │   ├── anime.py            # DTOs Anime, Episode, QualityInfo
│   │   ├── download_task.py    # Entités et tâches de téléchargement
│   │   ├── favorite.py         # Table des favoris
│   │   └── watch_progress.py   # Table de progression de visionnage
│   ├── routers/                # Contrôleurs Web & API REST
│   │   ├── anime.py            # Pages /, /search, /anime et API de recherche
│   │   ├── download.py         # Pages /downloads et API de téléchargement / SSE
│   │   ├── library.py          # Pages /library, /history, /voiranime et API favoris
│   │   └── media.py            # Streaming HTTP 206 et sous-titres
│   ├── services/               # Services métier
│   │   ├── download_manager.py # Téléchargement asynchrone, reprise, muxing, throttling
│   │   ├── library_service.py  # CRUD favoris, historique, progression
│   │   ├── proxy_service.py    # Rotation User-Agents & proxies
│   │   ├── scraping_service.py # Scraping french-manga.net & résolveur Vidzy
│   │   ├── voiranime_service.py# Scraping voir-anime.to (HTTP pur, sans Playwright)
│   │   ├── watchdog_service.py # Surveillance automatique des nouveaux épisodes
│   │   └── unpacking.py        # Décodeur Dean Edwards P.A.C.K.E.R.
│   ├── static/                 # Fichiers CSS et JavaScript (app.js, style.css)
│   └── templates/              # Gabarits HTML Jinja2
├── tests/                      # Suite de tests automatisés
│   ├── test_api.py             # Tests d'intégration FastAPI & routes
│   ├── test_database.py        # Tests CRUD base SQLite
│   ├── test_media.py           # Tests du streaming vidéo HTTP 206 Partial Content
│   └── test_scraping.py        # Tests des algorithmes de scraping et déballage
├── requirements.txt            # Dépendances Python
├── run.py                      # Point d'entrée de l'application
├── run.sh                      # Script de démarrage Shell
└── README.md
```

---

## ⚙️ Configuration

Les paramètres par défaut sont définis dans `animan/config.py` et peuvent être surchargés par variables d'environnement :

| Paramètre | Défaut | Description |
|-----------|---------|-------------|
| `PORT` | `8080` | Port d'écoute du serveur web |
| `DOWNLOAD_DIR` | `~/Downloads/Animan` | Répertoire de destination des vidéos |
| `DB_PATH` | `~/.animan/db/animan.sqlite3` | Emplacement du fichier SQLite |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Nombre de téléchargements simultanés |
| `PLEX_ORGANIZATION` | `false` | Organisation en dossiers `Nom/Season 01/` |
| `FRENCH_MANGA_BASE_URL` | `https://w16.french-manga.net` | URL miroir french-manga |
| `VOIR_ANIME_BASE_URL` | `https://voir-anime.to` | URL miroir voir-anime |

---

## 🧪 Tests

Exécutez l'ensemble de la suite de tests automatisés :

```bash
python3 -m pytest -v
```

Tous les modules (APIs, base de données SQLite, streaming HTTP 206, parsers Vidzy / Dean Edwards et routage) sont couverts.
