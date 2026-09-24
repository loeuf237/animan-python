# Animan (Python Edition) 🎬

[![GitHub Release](https://img.shields.io/github/v/release/loeuf237/animan-python?color=9d6fff&label=Release)](https://github.com/loeuf237/animan-python/releases/latest)
[![Tests](https://img.shields.io/badge/Tests-178%20passed-34d399.svg)](tests/)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.12%20%7C%203.14-38bdf8.svg)](https://www.python.org/)
[![PWA](https://img.shields.io/badge/PWA-Ready-f59e0b.svg)](animan/static/manifest.json)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Android%20%7C%20Linux%20%7C%20Web-a855f7.svg)](#-téléchargements--applications)

**Animan** est une application moderne et haute performance de streaming et de téléchargement d'animés (VF et VOSTFR), développée avec **FastAPI**, **Python 3** et une interface **Web / PWA / Native**.

Disponible sous forme d'**application Android (.apk)**, d'**exécutable de bureau Windows (.exe)**, de **Progressive Web App (PWA)** ou de **serveur local Python**.

---

## 📥 Téléchargements & Applications

Retrouvez tous les binaires compilés sur la page des [Releases GitHub](https://github.com/loeuf237/animan-python/releases/latest) :

| Plateforme | Format | Lien direct | Description |
| :--- | :---: | :--- | :--- |
| **Android** | `.apk` | [📲 **Animan-v2.1.0.apk**](https://github.com/loeuf237/animan-python/releases/download/v2.1.0/Animan-v2.1.0.apk) *(~48.7 Mo)* | Application Android **100% autonome** avec serveur Python (FastAPI/Uvicorn) embarqué via Chaquopy, lecteur immersif et téléchargements. |
| **Windows** | `.exe` | [💻 **Animan-Windows-x64.zip**](https://github.com/loeuf237/animan-python/releases/download/v2.1.0/Animan-Windows-x64.zip) *(~34.8 Mo)* | Exécutable Windows autonome avec interface native WebView2 (Edge), sans installation de Python requise. |
| **Web / Mobile** | `PWA` | [🌐 **Installer depuis le navigateur**](#-installation-pwa-progressive-web-app) | Installation instantanée plein écran sans barre d'adresse sur Chrome, Edge, Safari iOS et Android. |
| **Linux / Serveur** | `Python` | [🐧 **Lancer via Python**](#-démarrage-local-python) | Démarrage classique via Uvicorn / script `run.py`. |

---

## ✨ Fonctionnalités Principales

### 📡 Sources & Extraction vidéo
- **Sources intégrées** : Scraping asynchrone ultra-rapide pour `french-manga.net`, `voir-anime.to` et `animepahe.pw`.
- **Hub d'extracteurs vidéo modulaires (Axe 1)** : Résolution directe des flux pour *Vidmoly*, *Sibnet*, *Sendvid*, *Streamtape*, *VOE*, *Uqload*, et repli intelligent sur *yt-dlp*.
- **Adaptateurs de conteneurs (Axe 2)** : Support d'extensions et sources dynamiques (*Hanime Astro SPA*, *Anime-Sama JS*).

### ⚡ Téléchargement & Reprise
- File d'attente asynchrone (`asyncio.Queue`) avec gestion fine de la concurrence.
- Reprise automatique des téléchargements interrompus via en-têtes HTTP `Range` (`Content-Range`).
- Concaténation de flux vidéo segmentés HLS (`.m3u8` / `.ts`).
- Organisation automatique pour **Plex / Jellyfin** (`Titre/Season 01/S01E01.mp4`).
- Limitation de bande passante globale et priorisation des séries.

### 🎥 Streaming & Expérience Vidéo
- Lecteur vidéo moderne (Plyr) avec prise en charge complète du seeking (`HTTP 206 Partial Content`).
- Basculement automatique en plein écran paysage sur mobile et tablette.
- Sélection des pistes de sous-titres et résolutions disponibles.

### 📚 Bibliothèque & Synchronisation
- Favoris, progression de visionnage par épisode et historique persistant sous SQLite.
- Mode sombre AMOLED moderne et responsive inspiré des interfaces Mihon / Aniyomi.
- Suivi en temps réel de la progression via **Server-Sent Events (SSE)**.

---

## 📱 Application Android (.apk)

L'application Android native intègre son propre runtime Python 3.11 embarqué via **Chaquopy** :

1. Téléchargez le fichier [**Animan-v2.1.0.apk**](https://github.com/loeuf237/animan-python/releases/download/v2.1.0/Animan-v2.1.0.apk).
2. Ouvrez le fichier sur votre appareil Android et acceptez l'installation.
3. Lancez **Animan** :
   - **Mode 100% Autonome (par défaut)** : Le serveur backend FastAPI/Uvicorn démarre instantanément en tâche de fond sur votre téléphone (`http://127.0.0.1:8080`). Aucun PC, ni serveur externe n'est requis !
   - **Mode Client / LAN (optionnel)** : Vous pouvez également vous connecter à un serveur Animan distant ou hébergé sur votre réseau local (ex: `http://192.168.1.50:8080`) via l'écran de configuration du serveur.
4. **Téléchargements mobiles** : les épisodes sont directement téléchargés dans le dossier *Download* d'Android via le gestionnaire natif.

---

## 💻 Application Windows (.exe)

L'exécutable autonome Windows ne nécessite aucun environnement de développement :

1. Téléchargez [**Animan-Windows-x64.zip**](https://github.com/loeuf237/animan-python/releases/download/v2.1.0/Animan-Windows-x64.zip).
2. Décompressez l'archive dans un dossier de votre choix (ex: `C:\Animan`).
3. Double-cliquez sur `Animan.exe`.
4. L'application démarre automatiquement le serveur local en arrière-plan et ouvre une fenêtre native fluide via **Microsoft Edge WebView2**.

---

## 🌐 Installation PWA (Progressive Web App)

Animan intègre un **Manifest Web App** et un **Service Worker** complet :

1. Lancez Animan (`python3 run.py`) et rendez-vous sur `http://localhost:8000` (ou votre IP locale).
2. **Sur Google Chrome / Edge (Desktop)** : Cliquez sur l'icône d'installation dans la barre d'adresse ou sur le bouton *Installer l'application* dans la barre supérieure.
3. **Sur Android** : Un bandeau vous propose d'ajouter Animan à votre écran d'accueil.
4. **Sur iOS (Safari)** : Appuyez sur l'icône de partage, puis sélectionnez *Sur l'écran d'accueil*.
5. L'application s'ouvre alors comme une application native indépendante, en plein écran, avec cache statique et page de secours hors-ligne.

---

## 🐧 Démarrage Local (Python)

### Prérequis
- Python 3.10 ou supérieur (`python3 --version`)
- FFmpeg (optionnel, pour le muxing de sous-titres)

### Installation
```bash
# Cloner le dépôt
git clone https://github.com/loeuf237/animan-python.git
cd animan-python

# Installer les dépendances
pip install -r requirements.txt
```

### Lancement
```bash
# Lancer le serveur web
python3 run.py

# Ou lancer l'interface de bureau (avec fenêtre native WebView)
python3 desktop.py
```

L'application est accessible sur :
👉 **http://localhost:8000** (ou port configuré)

---

## 📁 Structure du Projet

```text
animan-python/
├── .github/workflows/         # Intégration continue (Release Windows .exe & Android .apk)
├── android/                   # Projet natif Android Studio (Kotlin, WebView, DownloadManager)
│   ├── app/src/main/          # Code source Android & manifest
│   ├── build.gradle.kts       # Configuration de compilation Gradle
│   └── gradlew                # Gradle wrapper
├── animan/                    # Backend Python principal
│   ├── config.py              # Configuration & paramètres d'environnement
│   ├── database.py            # Modèles SQLite & persistance
│   ├── routers/               # Contrôleurs FastAPI (anime, downloads, library, media, etc.)
│   ├── services/              # Logique métier, gestionnaire de téléchargements, SSE
│   │   ├── extractors/        # Hub d'extracteurs vidéo modulaires (Vidmoly, Sibnet, VOE, etc.)
│   │   └── container_adapters/# Adaptateurs spécifiques (Hanime, Anime-Sama)
│   ├── static/                # Assets frontend (CSS, JS, images, manifest.json, sw.js)
│   └── templates/             # Templates HTML Jinja2 modernes
├── tests/                     # Suite de 178 tests automatisés (pytest)
├── desktop.py                 # Lanceur de bureau fenêtré (pywebview)
├── animan.spec                # Configuration de packaging PyInstaller
├── requirements.txt           # Dépendances Python
├── run.py                     # Point d'entrée serveur Uvicorn
└── README.md
```

---

## 🧪 Tests de non-régression

Pour lancer l'ensemble des 178 tests unitaires et d'intégration :

```bash
PYTHONPATH=. pytest tests/ -v
```

---

## 📄 Licence

Ce projet est sous licence open-source libre pour un usage personnel et éducatif.
