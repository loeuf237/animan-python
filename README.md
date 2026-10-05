# Animan (Python Edition) 🎬

[![GitHub Release](https://img.shields.io/github/v/release/loeuf237/animan-python?color=9d6fff&label=Release)](https://github.com/loeuf237/animan-python/releases/latest)
[![Tests Python](https://img.shields.io/badge/Python_tests-249%20passed-34d399.svg)](tests/)
[![Tests Frontend](https://img.shields.io/badge/Frontend_tests-6%20passed-34d399.svg)](frontend/tests/)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.12%20%7C%203.14-38bdf8.svg)](https://www.python.org/)
[![PWA](https://img.shields.io/badge/PWA-Ready-f59e0b.svg)](animan/static/manifest.json)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Web-a855f7.svg)](#-téléchargements--applications)

**Animan** est une application moderne et haute performance de streaming et de téléchargement d'animés (VF et VOSTFR), développée avec **FastAPI**, **Python 3** et une interface **Web / Desktop / PWA**.

Disponible sous forme d'**exécutable de bureau autonome pour Windows (.exe)**, d'application fenêtrée native pour **macOS & Linux** (`desktop.py`), ou de **Progressive Web App (PWA)** multiplateforme.

---

## 📥 Téléchargements & Applications

Retrouvez les versions compilées sur la page des [Releases GitHub](https://github.com/loeuf237/animan-python/releases/latest) :

| Plateforme | Format | Mode d'accès | Description |
| :--- | :---: | :--- | :--- |
| **Windows** | `.exe` | [💻 **Animan-Windows-x64.zip**](https://github.com/loeuf237/animan-python/releases/download/v2.1.0/Animan-Windows-x64.zip) *(~35 Mo)* | Exécutable Windows autonome avec interface native WebView2 (Edge), sans installation de Python requise. |
| **Linux** | `Desktop / Web` | [🐧 **Lancer via desktop.py**](#-lancement-sur-linux--macos) | Fenêtre native WebKitGTK ou serveur local via Python 3. |
| **macOS** | `Desktop / Web` | [🍎 **Lancer via desktop.py**](#-lancement-sur-linux--macos) | Fenêtre native Cocoa / WebKit ou serveur local via Python 3. |
| **Web / Mobile** | `PWA` | [🌐 **Installer depuis le navigateur**](#-installation-pwa-progressive-web-app) | Installation instantanée plein écran sans barre d'adresse sur Chrome, Edge, Safari iOS et Android. |

> ℹ️ *Note : L'ancienne version APK Android expérimentale est temporairement suspendue et fait l'objet d'une réécriture native complète sous Flutter.*

---

## ✨ Fonctionnalités Principales

### 📡 Sources & Extraction vidéo
- **Sources intégrées** : Scraping asynchrone ultra-rapide pour `french-manga.net`, `voir-anime.to` et `animepahe.pw`.
- **Hub d'extracteurs vidéo modulaires (Axe 1)** : Résolution directe des flux pour *Vidmoly*, *Sibnet*, *Sendvid*, *Streamtape*, *VOE*, *Uqload*, et repli intelligent sur *yt-dlp*.
- **Adaptateurs de conteneurs (Axe 2)** : Support d'extensions et sources dynamiques (*Hanime Astro SPA*, *Anime-Sama JS*, *AniSama AJAX*, *FRAnime API*).

### 🧩 Extensions importées
- Import d’un dépôt Aniyomi : seul le dernier dépôt est actif ; les nouvelles extensions sont désactivées par défaut.
- Actualisation du dépôt en conservant les activations, suppression des entrées retirées du catalogue et invalidation des recettes lors d’une mise à jour.
- Bouton **Tester** pour vérifier le catalogue et afficher les erreurs de connexion ; bouton **Configurer** pour adapter l’adresse et les sélecteurs de la recette JSON.
- Extraction des épisodes et lecteurs AJAX d’AniSama, catalogue/saisons/langues/lecteurs de l’API FRAnime, lecteurs Dooplay de JetAnime et liens de Vostfree/AnimeVostFr.

Les APK Aniyomi ne sont pas exécutés comme sur Android : Animan extrait une recette et utilise ses adaptateurs Python. Une source avec une logique spécifique peut nécessiter un adaptateur supplémentaire. Un domaine fermé, une erreur de certificat ou un défi Cloudflare peuvent empêcher l’accès malgré une recette correcte.

### 🌐 Sessions réseau et vérification des sites
- Client commun `curl_cffi` pour les sources intégrées, extensions, extracteurs, médias et le repli `yt-dlp` lorsqu’il est installé. Le profil Chrome et son User-Agent restent cohérents ; l’ancienne rotation du User-Agent ne s’applique plus aux sources.
- Sessions isolées par domaine, connexions réutilisées, proxy conservé pendant la session et cookies expirés retirés. Les cookies avec une expiration sont conservés dans `CACHE_DIR/http_sessions` avec des permissions privées ; les cookies de session restent en mémoire.
- Cache court des petites réponses GET, regroupement des requêtes identiques en cours, trois connexions maximum par domaine, espacement des requêtes et respect de `Retry-After`. Les flux HLS, requêtes Range et réponses privées ne sont pas mis en cache par ce transport.
- Détection des challenges via `cf-mitigated: challenge` et les marqueurs des pages Cloudflare. Un simple HTTP 403 n’est pas automatiquement considéré comme un challenge. Les téléchargements passent en **Vérification nécessaire**, sans consommer leurs tentatives ni effacer leurs fichiers partiels.

Dans l’interface Vue (`/spa/downloads`), le panneau **Vérification nécessaire** propose d’ouvrir Chrome, Chromium, Edge ou Brave déjà installé sur la machine du serveur. Aucun navigateur n’est téléchargé. Terminez la vérification dans la fenêtre dédiée, puis cliquez sur **J’ai terminé la vérification** : Animan importe uniquement les cookies du domaine concerné, vérifie l’accès et reprend ses téléchargements en attente. Une recherche ou un catalogue en attente est relancé automatiquement avec ses critères ; les résultats des sources accessibles restent affichés pendant la vérification.

La fenêtre utilise un profil dédié sous `CACHE_DIR/verification_profiles`, conserve la même route proxy et se ferme après validation, annulation ou dix minutes. Son ouverture est réservée aux requêtes provenant de la machine du serveur et nécessite une session graphique. Les proxys authentifiés ne sont pas pris en charge pour cette fenêtre. Firefox n’est pas piloté par ce parcours.

Avec `desktop.py`, le bouton **WebView (expérimental)** permet d’essayer le moteur système déjà disponible via `pywebview`, sans nouveau navigateur. Ce mode est disponible sans proxy ; son efficacité dépend du moteur et du site. Il ne constitue pas une garantie de résolution de tous les challenges Cloudflare.

### 📚 Parcourir les sources
L’onglet **Sources** remplace Recherche dans les navigations de bureau et mobile. Il liste VoirAnime, AnimePahe et French-Manga, ainsi que les extensions installées (recette compilée). Une extension désactivée peut être réactivée depuis Extensions. La recherche globale reste accessible via le bouton **Ctrl + K**, le raccourci clavier Ctrl+K (Cmd+K sur macOS) et la barre supérieure.

Chaque source dispose d’une page dédiée avec recherche, dernières sorties et pagination lorsqu’elle est proposée par le site. VoirAnime expose les populaires, les tris par note, vues, date et titre, ainsi qu’une recherche combinant plusieurs genres. French-Manga expose ses genres, tags, langues, statuts et coups de cœur. AnimePahe utilise son API pour les dernières sorties et la recherche. Les extensions utilisent leurs routes et sélecteurs de catalogue, populaires et pagination ; FRAnime et Hanime proposent aussi les genres de leur catalogue API.

Les options dépendent de la source : un classement populaire n’est pas inventé lorsque le site n’en fournit pas. Un tri marqué « page » ou une recherche dans une page filtrée s’applique uniquement aux résultats de cette page ; la pagination permet de parcourir la suite. Les filtres combinés de VoirAnime et des catalogues API s’appliquent au catalogue entier.

La recherche globale affiche les résultats partiels et identifie les sources demandant une vérification Cloudflare. Le bouton **Ouvrir une fenêtre de vérification** apparaît aussi dans la fenêtre de recherche. Après validation manuelle, Animan récupère les cookies, confirme l’accès et relance la recherche en attente. Une recherche fermée ou remplacée par de nouveaux critères n’est pas relancée.

### ⚡ Téléchargement & Reprise
- Sélection indépendante des épisodes VF/VOSTFR, filtre de version, fichiers distincts y compris en organisation Plex et navigation du lecteur dans la langue choisie.
- Prévention des doubles lancements ; anciennes tâches partageant une destination entre plusieurs liens mises en pause pour éviter un mélange de fichiers. Relancez la version voulue depuis sa fiche.
- File d'attente asynchrone avec gestion de la concurrence, pause, annulation et reprise.
- Reprise automatique des téléchargements interrompus via en-têtes HTTP `Range` (`Content-Range`).
- Concaténation de flux vidéo segmentés HLS (`.m3u8` / `.ts`).
- Organisation automatique pour **Plex / Jellyfin** (`Titre/Season 01/S01E01.mp4`).
- Limitation de bande passante globale et priorisation des séries.
- Préférences de serveur et de qualité appliquées aux téléchargements par lot, avec possibilité de les préciser par épisode.

### 💬 Sous-titres & Fusion vidéo
- Extraction des pistes JavaScript et HTML, avec résolution des URLs relatives.
- Prise en charge des fichiers **SRT, WebVTT et ASS** ; validation du contenu reçu pour rejeter les fichiers vides et les pages HTML d'erreur.
- Fichiers distincts pour chaque piste, même lorsque plusieurs langues portent le même libellé.
- Conservation des libellés et des métadonnées de langue dans le fichier fusionné.
- Fusion vers **MKV** avec **FFmpeg**, y compris lorsque la vidéo d'origine est déjà en MKV.
- Vérification du fichier temporaire et du nombre de pistes avec **ffprobe** avant remplacement de la vidéo et suppression des fichiers originaux.
- Mise à jour de la taille réelle après fusion ; signalement des échecs de téléchargement ou de fusion des pistes connues.
- Reprise des sous-titres manquants sans considérer la seule présence d'une vidéo valide comme un téléchargement entièrement terminé.

Pour utiliser cette fonction, activez le téléchargement des sous-titres pour l'épisode ou le lot. Les pistes doivent être disponibles auprès de la source. **FFmpeg et ffprobe doivent être accessibles dans le `PATH` pour la fusion vérifiée.** Si FFmpeg est absent, les pistes téléchargées restent dans des fichiers séparés à côté de la vidéo.

### 🎥 Streaming & Expérience Vidéo
- Lecture vidéo avec prise en charge du seeking (`HTTP 206 Partial Content`), des plages ouvertes et des plages suffixes comme `bytes=-1024`.
- Sélection locale fondée sur l'URL de l'épisode pour éviter de lire une version VF à la place d'une VOSTFR portant le même titre.
- Interface 100% responsive et adaptative (Desktop, Tablettes, Mobiles).
- Mode paysage immersif automatique et sélection des sous-titres/qualités.

### 📚 Bibliothèque & Synchronisation
- Favoris, progression de visionnage par épisode et historique persistant sous SQLite.
- États « vu » et « non vu » persistants, avec distinction des versions VF et VOSTFR et restauration de la progression dans l'interface Vue.
- Mode sombre AMOLED moderne inspiré des interfaces Mihon / Aniyomi.
- Suivi en temps réel de la progression via **Server-Sent Events (SSE)**.

### 🔒 Protection des accès réseau
- Validation des URLs et des redirections des proxies HTTP de médias et des téléchargements de sous-titres pour bloquer les destinations locales ou privées.
- Vérification des chemins de téléchargement et des fichiers de sous-titres.

---

## 💻 Application Windows (.exe)

L'exécutable autonome Windows ne nécessite aucun environnement de développement :

1. Téléchargez [**Animan-Windows-x64.zip**](https://github.com/loeuf237/animan-python/releases/download/v2.1.0/Animan-Windows-x64.zip).
2. Décompressez l'archive dans un dossier de votre choix (ex: `C:\Animan`).
3. Double-cliquez sur `Animan.exe`.
4. L'application démarre automatiquement le serveur local en arrière-plan et ouvre une fenêtre native fluide via **Microsoft Edge WebView2**.

---

## 🍎 / 🐧 Lancement sur Linux & macOS

Animan propose deux modes de fonctionnement natifs sur Linux et macOS :

### 1. Mode Application Fenêtrée (Recommandé)
Pour lancer Animan dans une fenêtre native indépendante (sans passer par un navigateur) :
```bash
python3 desktop.py
```
*Utilise WebKitGTK sous Linux et WebKit Cocoa sous macOS pour un rendu natif fluide sans terminal visible.*

### 2. Mode Serveur Web / Headless
```bash
python3 run.py
```
Puis accédez à `http://localhost:8080` depuis n'importe quel navigateur sur votre machine ou réseau local.

---

## 🌐 Installation PWA (Progressive Web App)

Animan intègre un **Manifest Web App** et un **Service Worker** complet :

1. Lancez Animan (`python3 run.py`) et rendez-vous sur `http://localhost:8080` (ou votre IP locale).
2. **Sur Google Chrome / Edge (Desktop)** : Cliquez sur l'icône d'installation dans la barre d'adresse ou sur le bouton *Installer l'application* dans la barre supérieure.
3. **Sur Android** : Un bandeau vous propose d'ajouter Animan à votre écran d'accueil.
4. **Sur iOS (Safari)** : Appuyez sur l'icône de partage, puis sélectionnez *Sur l'écran d'accueil*.
5. L'application s'ouvre alors comme une application native indépendante, en plein écran, avec cache statique et page de secours hors-ligne.

---

## 🐧 Démarrage Local (Python)

### Prérequis
- Python 3.10 ou supérieur (`python3 --version`)
- **FFmpeg et ffprobe** pour fusionner et vérifier les sous-titres ; ils sont optionnels pour télécharger la vidéo et conserver des sous-titres séparés.
- **Node.js 20.19+ dans la branche 20, ou 22.12+** et npm pour développer ou compiler l'interface Vue.

Vérifiez les outils de fusion installés :

```bash
ffmpeg -version
ffprobe -version
```

### Installation
```bash
# Cloner le dépôt
git clone https://github.com/loeuf237/animan-python.git
cd animan-python

# Installer les dépendances
python3 -m pip install -r requirements.txt
```

### Lancement
```bash
# Lancer le serveur web
python3 run.py

# Ou lancer l'interface de bureau (avec fenêtre native WebView)
python3 desktop.py
```

L'application est accessible sur :
👉 **http://localhost:8080** (ou port configuré avec `ANIMAN_PORT`)

Pour limiter le serveur web à votre machine :

```bash
ANIMAN_HOST=127.0.0.1 python3 run.py
```

### Interface Vue 3 / TypeScript

Depuis la racine du projet, compilez l'interface :

```bash
cd frontend
npm ci
npm run build
cd ..
python3 run.py
```

La SPA est alors disponible sur **http://localhost:8080/spa/** ou **http://localhost:8080/app/**. La navigation et les liens vers les pages internes conservent le préfixe choisi. Les pages Jinja restent disponibles à la racine du serveur.

Pour développer l'interface, lancez le backend dans un terminal, puis exécutez dans un second terminal :

```bash
cd frontend
npm ci
npm run dev
```

Vite sert l'interface sur **http://localhost:5173** et transmet les requêtes `/api` au backend sur le port **8080**. Si vous modifiez ce port, adaptez la cible du proxy dans `frontend/vite.config.ts`.

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
│   │   ├── subtitle_service.py # Normalisation des pistes, formats et langues
│   │   └── container_adapters/# Adaptateurs spécifiques (Hanime, Anime-Sama)
│   ├── static/                # Assets frontend (CSS, JS, images, manifest.json, sw.js)
│   └── templates/             # Templates HTML Jinja2 modernes
├── frontend/                  # SPA Vue 3, TypeScript, Vite et tests frontend
├── tests/                     # Suite de 249 tests Python (pytest)
├── desktop.py                 # Lanceur de bureau fenêtré (pywebview)
├── animan.spec                # Configuration de packaging PyInstaller
├── requirements.txt           # Dépendances Python
├── run.py                     # Point d'entrée serveur Uvicorn
└── README.md
```

---

## 🧪 Tests de non-régression

La dernière validation comprend **249 tests Python réussis**, dont **16 tests dédiés au parcours des sous-titres**, ainsi que **6 tests frontend réussis**.

Depuis la racine du projet, lancez les tests Python :

```bash
PYTHONPATH=. pytest tests/ -v
```

Les tests de sous-titres utilisent des réponses HTTP simulées et des vidéos synthétiques. Ils vérifient notamment les collisions de libellés, les langues, les URLs relatives, les destinations privées et les redirections, les fusions MP4/MKV, les tailles après fusion et les reprises après échec. Les tests de fusion sont ignorés si FFmpeg ou ffprobe est absent.

Pour exécuter uniquement ces tests :

```bash
PYTHONPATH=. pytest tests/test_subtitle_pipeline.py -v
```

Pour éviter d'utiliser la base SQLite et le dossier de téléchargement habituels pendant les tests, configurez des chemins temporaires et initialisez la base :

```bash
animan_test_dir=$(mktemp -d)
export ANIMAN_DB_PATH="$animan_test_dir/animan.sqlite3"
export ANIMAN_DOWNLOAD_DIR="$animan_test_dir/downloads"
export ANIMAN_CACHE_DIR="$animan_test_dir/cache"
PYTHONPATH=. python3 -c "import animan.models; from animan.database import init_db; init_db()"
PYTHONPATH=. pytest tests/ -v
```

Dans `frontend/`, lancez les tests de navigation SPA et de progression, puis vérifiez la compilation TypeScript/Vue :

```bash
npm ci
npm test
npm run build
```

---

## 📄 Licence

Ce projet est sous licence open-source libre pour un usage personnel et éducatif.
