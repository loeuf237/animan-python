# Animan (Python Edition) 🎬

[![GitHub Release](https://img.shields.io/github/v/release/loeuf237/animan-python?color=9d6fff&label=Release)](https://github.com/loeuf237/animan-python/releases/latest)
[![Python tests](https://img.shields.io/badge/Python-regression_tests-34d399.svg)](tests/)
[![Frontend tests](https://img.shields.io/badge/Frontend-regression_tests-34d399.svg)](frontend/tests/)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.12%20%7C%203.14-38bdf8.svg)](https://www.python.org/)
[![PWA](https://img.shields.io/badge/PWA-Ready-f59e0b.svg)](animan/static/manifest.json)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Web-a855f7.svg)](#downloads-and-applications)

**Animan** is an anime streaming and download application built with **FastAPI**, **Python 3**, and a **Vue 3 / TypeScript** interface. It supports dubbed and subtitled episodes, a personal library, imported sources, and local video playback.

Use the packaged **Python + Vue desktop application** on Windows, Linux or macOS, or the cross-platform **Progressive Web App (PWA)**. The desktop release series starts at **0.1.0**; macOS builds are explicitly **UNTESTED on real Mac hardware**.

## Downloads and applications

Compiled builds are available on [GitHub Releases](https://github.com/loeuf237/animan-python/releases/latest).

| Platform | Format | Access | Description |
| :--- | :---: | :--- | :--- |
| Windows x64 | `.zip` / `.exe` | [Download](https://github.com/loeuf237/animan-python/releases/download/v0.1.0/Animan-v0.1.0-Windows-x64.zip) | Python engine, Vue interface and media tools included; WebView2 or installed-browser fallback. |
| Linux x64 | `.tar.gz` | [Download](https://github.com/loeuf237/animan-python/releases/download/v0.1.0/Animan-v0.1.0-Linux-x64.tar.gz) | Ubuntu 22.04 build baseline; GTK/WebKit window or installed-browser fallback. |
| macOS Apple Silicon | `.app` in `.zip` | [Download — UNTESTED](https://github.com/loeuf237/animan-python/releases/download/v0.1.0/Animan-v0.1.0-macOS-arm64-UNTESTED.zip) | **UNTESTED on real Mac hardware**, not Developer-ID signed or notarized. |
| macOS Intel | `.app` in `.zip` | [Download — UNTESTED](https://github.com/loeuf237/animan-python/releases/download/v0.1.0/Animan-v0.1.0-macOS-x64-UNTESTED.zip) | **UNTESTED on real Mac hardware**, not Developer-ID signed or notarized. |
| Web / Mobile | PWA | [Browser installation](#pwa-installation) | Standalone browser installation on Chrome, Edge, Safari iOS and Android. |

Extract the whole archive. Python and Node.js are not required for these packages. FFmpeg and ffprobe are included. [Package requirements and checks](docs/desktop-distribution.md) explain system compatibility and `SHA256SUMS.txt` verification.

The **Android beta pipeline** embeds the shared Python engine, compiled Vue interface,
curl_cffi and native FFmpeg for **Android 10+ / ARM64**. It validates the installed
app on emulators before publication; production signing and real-phone testing
are tracked separately. Validation APKs use a temporary identity and are not
distributed as production releases. See [Android distribution](docs/android-distribution.md)
and the [technical roadmap](docs/android-embedded-roadmap.md).

## Language and default source

Animan supports **English and French**, including navigation, search, settings, download states, dialogs, notifications and accessibility labels. Translation catalogs are bundled with the Vue application, so interface translation does not require an additional network request to succeed.

On first use, the interface follows the browser's preferred language: French browsers use French; English and other unsupported languages use English. A valid `?lang=fr` or `?lang=en` override takes priority, followed by the saved language cookie, local preference and browser detection. The language button and Settings let users change this choice. Explicit choices are saved per browser, rather than changing the language for everyone using the server.

For users without a saved source preference:

- **English:** AnimePahe is selected for home-page search, latest releases and global search.
- **French:** French-Manga is selected.

Selecting a source saves the user's preference. A later language change preserves that explicit source choice. Source names, episode versions, anime titles and descriptions supplied by external sites retain their original meaning; changing the interface language does not translate the media or change its audio language.

## Features

### Sources and video extraction

- Built-in sources: **French-Manga**, **VoirAnime** and **AnimePahe**.
- Modular video extractors for Vidmoly, Sibnet, Sendvid, Streamtape, VOE and Uqload, with a `yt-dlp` fallback.
- Python adapters for dynamic sources, including Hanime, Anime-Sama, AniSama and FRAnime.
- Source-specific search, latest releases, pagination, popular series, genres and tags when supported by the source.
- VoirAnime exposes popularity and sorting by rating, views, date and title, with combined genre searches. French-Manga exposes genres, tags, languages, statuses and featured titles. AnimePahe uses its API for search and latest releases.
- Unsupported catalog features are not invented. Filters labeled as applying to a page only affect the loaded page; pagination lets users browse additional results.

### Imported extensions

- Import an Aniyomi repository. Only the latest repository remains active; newly imported extensions are disabled by default.
- Repository updates preserve enabled sources, remove entries no longer in the catalog and invalidate changed extraction recipes.
- Test a source to inspect catalog connectivity; configure its address and JSON selectors when required.
- Adapters handle AniSama AJAX players, FRAnime's catalog/seasons/languages/players, JetAnime Dooplay players and Vostfree/AnimeVostFr links.

Animan does not run Aniyomi APKs as Android does. It extracts a recipe and uses Python adapters. Sources with custom logic may need an additional adapter. Closed domains, certificate errors and Cloudflare challenges can prevent access even with a correct recipe.

### Network sessions and site verification

- A shared `curl_cffi` client serves sources, extensions, extractors, media and the installed `yt-dlp` fallback. The Chrome profile and User-Agent remain consistent.
- Sessions are isolated by domain, reuse connections, keep a stable proxy and remove expired cookies. Persistent cookies are stored privately under `CACHE_DIR/http_sessions`; session cookies remain in memory.
- Small GET responses have a short-lived cache; identical requests are coalesced. Per-domain connection limits, pacing and `Retry-After` reduce unnecessary requests. HLS streams, Range requests and private responses are not cached.
- Cloudflare challenges, explicit Cloudflare access blocks and DDoS-Guard verification pages are distinguished from rate limits and network errors. Blocked downloads enter **Verification required** instead of repeatedly retrying.

Verification controls appear with a failed search or catalog request, or a blocked download. Background feed checks do not display a global verification panel on Home. **Open in a new tab** uses the browser currently displaying Animan, including on a remote device. Browser detection supplies a hint for the label and the default installed browser.

The optional **Capture cookies using a verification window** section opens an installed Chrome, Chromium, Edge or Brave browser on the **server machine**. Animan does not download a browser. Complete the CAPTCHA manually, then choose **I have completed verification**. Animan imports cookies for the relevant domain, checks access and resumes pending requests or downloads. A system WebView option is experimental. A normal tab cannot automatically transfer its cookies to the Python application; use the dedicated window for cookie capture. **I’m back, retry** checks access before clearing a blocked session.

The home feed fetches every enabled extension and reports failures per source instead of displaying them as an empty catalog.

Global search keeps partial results from accessible sources. After verification, a pending search or catalog request resumes with its existing criteria. Closed or superseded searches are not revived.

### Public proxies and rotation

**Settings → Proxy** has two sections:

- **Auto** fetches the fixed public lists from [ProxyScrape](https://github.com/proxyscrape/free-proxy-list), [Proxifly](https://github.com/proxifly/free-proxy-list) and [Geonode](https://geonode.com/free-proxy-list) in the background at every startup. **Refresh lists** fetches them again; **Test a sample** checks another bounded sample. Provider failures retain the previous list and are displayed individually. HTTPS-capable HTTP lists are preferred; their CONNECT support does not mean the proxy itself uses TLS.
- **Manual** configures your HTTP/HTTPS/SOCKS proxy, including authentication and local addresses. The connection test uses the fields currently displayed. Saving a changed proxy applies it to idle sessions immediately and to busy sessions after their active requests finish.

Public lists are a catalog, not a promise of connectivity. The catalog holds up to 3,000 unique public IP addresses and displays the first 100, with available proxies first. Up to 24 addresses are tested concurrently in batches of six against a fixed HTTPS endpoint, with certificate validation enabled. A successful check expires after 30 minutes. Results vary by network and time; the [provider comparison](docs/proxy-providers.md) records the observed limitations.

While automatic rotation is enabled, Animan tests another bounded sample when fewer than three fresh candidates remain, at most once every five minutes. This keeps long sessions supplied with fresh candidates without repeatedly fetching provider lists.

**Import JSON** accepts an array of proxy URLs, an object containing `proxies`/`data`, or entries with `ip`, `port` and `protocol`. Imports are atomic, limited to 1 MB and 1,000 entries, persisted across restarts and removable separately. Lists accept public IPs only; configure local proxies and hostnames in Manual. Credentials from an imported URL are masked in API responses. Imported proxies also need a successful HTTPS check before use.

**Change proxy and retry** is offered with source failures and blocked downloads. **Automatically rotate proxies for blocked sources** is optional and disabled by default. It applies to source pages, extensions, searches and media requests through the shared transport: at most one automatic retry per request and two proxy changes per domain in five minutes. POST requests require an explicit read-only search marker in the source adapter; other POST requests, rate limits and certificate failures do not trigger automatic rotation. A proxy stays fixed during active requests and streams; changes clear the domain's cookies, connections and cached session identity. Only the failing domain changes. Ordinary browsing and cookie capture use different mechanisms, and a proxy cannot guarantee that a CAPTCHA will disappear.

Proxy pool changes, imports, tests, rotation and managed verification are available from the server machine. The lists and masked status remain readable from remote clients.

An automatic domain rotation also requeues existing downloads waiting for verification on that domain. If the new route is still blocked, those tasks return to the verification state; unrelated downloads are unaffected.

### Navigation and library

- Four mobile tabs: **Home**, **Sources**, **Downloads** and **Library**. Extensions are managed from Sources; Settings is available in the top bar.
- **Ctrl+K / Cmd+K** opens global search. Source selectors group pinned and other sources.
- Search retains its query, source and results when returning from an anime detail page. Catalogs keep loaded results and scroll position during navigation.
- Favorites, episode watch progress and viewing history persist in SQLite. VF/VOSTFR versions have separate watch states.
- Removing a library item offers an undo notification. Clearing the library preserves downloaded files.
- Responsive layouts, dark/light themes, keyboard focus indicators, touch targets and reduced-motion support.
- Server-Sent Events provide live download updates, with periodic refresh as a fallback.

### Downloads and recovery

- Independent VF, VOSTFR and VO selections. Version suffixes such as `[VF]` and `[VOSTFR]` keep filenames distinct, including Plex/Jellyfin layouts.
- Duplicate launch prevention. Legacy tasks sharing a destination across different links are paused to prevent mixed files.
- Batch downloads show a preview of episode versions, requested quality and subtitles before being added to the queue.
- Concurrent queue management, pause, cancellation, scheduling, series priority and global/per-task bandwidth limits.
- Interrupted downloads resume using HTTP `Range` and strictly validated `Content-Range` bounds. Persisted strong ETags (or Last-Modified) are sent with `If-Range`; a 64 KB overlap also checks that the new route serves the same bytes. Changed media or servers ignoring Range restart safely instead of mixing representations.
- Segmented HLS downloads preserve completed segments, retry interrupted segments and validate response lengths before saving them. A playlist fingerprint prevents reusing segments from a different playlist/variant; renewed signed playlist URLs can conservatively require a fresh download.
- Optional Plex/Jellyfin organization: `Title/Season 01/Title - S01E01 [VF].mp4`.
- Explicit preparation, video download, subtitle download, assembly, muxing and verification phases. Unknown total sizes show bytes received instead of a misleading percentage.

Retries reuse valid local video and subtitle files before contacting the host. Subtitle requests have bounded retries and explicit errors; expired URLs can be re-extracted once. Partial subtitle success is persisted. Muxing validates a temporary file before publication; existing MKVs are preserved and a conflicting new export receives a distinct filename. Legacy tasks referencing a removed MP4 can recover the corresponding MKV after video and requested-track checks. Verification distinguishes actual decoder failures from timestamp diagnostics produced by FFmpeg's null output.

An active media connection keeps its proxy. If reading fails, the connection is closed before an optional automatic rotation, and the download manager resumes the partial file or retries the incomplete HLS segment. A manual rotation is refused while requests for that domain are active; pause the download first and wait for the connection to close. This is recovery after an interruption, not a seamless change of an established connection. Hosts may bind signed links to an IP or require fresh verification; those cases can need URL re-resolution or user verification. Servers without Range support restart file downloads from zero.

### Subtitles and muxing

- JavaScript and HTML subtitle extraction with relative URL resolution.
- **SRT, WebVTT and ASS** support; empty files and HTML error pages are rejected.
- Distinct sidecar filenames even when tracks share a label.
- Subtitle titles and language metadata are preserved in the muxed file.
- **FFmpeg** exports to **MKV**, including when the original video is already an MKV.
- **ffprobe** verifies the temporary output and subtitle count before replacing the original video and removing successfully integrated sidecars.
- File sizes are updated after muxing. Known subtitle failures are reported; a valid video alone does not mark an unfinished subtitle request as complete.

Enable subtitles for the episode or batch. Tracks must be available from the source. **FFmpeg and ffprobe must be on `PATH` for verified muxing.** Without FFmpeg, downloaded subtitles remain beside the video as separate files.

### Playback and network access protection

- Streaming and local playback support seeking, HTTP 206 Partial Content, open-ended ranges and suffix ranges such as `bytes=-1024`.
- Episode URLs distinguish dubbed and subtitled variants with identical titles.
- Landscape playback, subtitle selection and quality selection when available.
- Media proxy and subtitle request URLs and redirects are validated to reject local/private network destinations.
- Download and subtitle paths are validated.

## Windows

1. Download [Animan-v0.1.0-Windows-x64.zip](https://github.com/loeuf237/animan-python/releases/download/v0.1.0/Animan-v0.1.0-Windows-x64.zip).
2. Extract the archive into a directory such as `C:\Animan`.
3. Run `Animan.exe`.
4. Animan starts the local server and opens a native Microsoft Edge WebView2 window.

## Linux and macOS

For packaged builds, extract the whole archive and run `./Animan` on Linux or open
`Animan.app` on macOS. Choose the correct Mac architecture. **macOS is UNTESTED on
real hardware**, unsigned by Developer ID and not notarized. Linux archives need
a compatible system (glibc 2.35+); they are not universal AppImages.

For a native window from a source checkout:

```bash
python3 desktop.py
```

Linux uses WebKitGTK; macOS uses Cocoa / WebKit.

For a web or headless server:

```bash
python3 run.py
```

Open `http://localhost:8080`. Use the host setting below to restrict access to the local machine.

## PWA installation

1. Start Animan and open `http://localhost:8080`.
2. On Chrome/Edge desktop, use the install icon in the address bar when available.
3. On Android, add the application to the home screen.
4. On iOS Safari, use **Share → Add to Home Screen**.

The application opens in its own window and uses a service worker for static caching and an offline fallback page.

## Local Python setup

### Requirements

- Python **3.10 or later**.
- **FFmpeg and ffprobe** for verified subtitle muxing; optional for video downloads with separate subtitle files.
- **Node.js 20.19+ on the 20.x branch, or 22.12+**, and npm to develop or build the Vue frontend.

Check the media tools:

```bash
ffmpeg -version
ffprobe -version
```

### Installation

```bash
git clone https://github.com/loeuf237/animan-python.git
cd animan-python
python3 -m pip install -r requirements.txt
```

### Running

```bash
# Web server
python3 run.py

# Native desktop window
python3 desktop.py
```

The default address is **http://localhost:8080**. Change the port with `ANIMAN_PORT`.

To restrict the server to the local machine:

```bash
ANIMAN_HOST=127.0.0.1 python3 run.py
```

### Vue 3 / TypeScript frontend

Build from the repository root:

```bash
cd frontend
npm ci
npm run build
cd ..
python3 run.py
```

The SPA is available at **http://localhost:8080/spa/** and **http://localhost:8080/app/**. Internal links preserve the selected prefix. Legacy Jinja pages remain available at the server root.

For frontend development, keep the backend running in another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite serves **http://localhost:5173** and proxies `/api` to port **8080**. Update `frontend/vite.config.ts` if the backend port changes.

## Project structure

```text
animan-python/
├── .github/workflows/        # CI and release builds
├── android/                  # Experimental Android project
├── animan/
│   ├── config.py             # Configuration and environment settings
│   ├── database.py           # SQLite models and persistence
│   ├── routers/              # FastAPI routes
│   ├── services/             # Sources, extractors, queue and verification
│   │   ├── extractors/       # Modular video extractors
│   │   ├── subtitle_service.py
│   │   └── container_adapters/
│   ├── static/               # Legacy frontend, images, manifest and service worker
│   └── templates/            # Jinja HTML templates
├── frontend/                 # Vue 3, TypeScript, Vite and frontend tests
│   └── src/locales/          # Bundled English/French interface catalogs
├── tests/                    # Python regression tests
├── desktop.py                # Native-window launcher
├── animan.spec               # PyInstaller packaging configuration
├── requirements.txt
├── run.py                    # Uvicorn server entry point
└── README.md
```

## Regression tests

Run the Python suite from the repository root:

```bash
PYTHONPATH=. pytest tests/ -v
```

Subtitle tests use mocked HTTP responses and synthetic videos. They cover labels, languages, relative URLs, private destinations and redirects, MP4/MKV muxing, updated file sizes, recovery, expired URLs and filename conflicts. FFmpeg-dependent tests are skipped when the required tools are unavailable.

```bash
PYTHONPATH=. pytest tests/test_subtitle_pipeline.py -v
```

To isolate tests from the usual database and download directory:

```bash
animan_test_dir=$(mktemp -d)
export ANIMAN_DB_PATH="$animan_test_dir/animan.sqlite3"
export ANIMAN_DOWNLOAD_DIR="$animan_test_dir/downloads"
export ANIMAN_CACHE_DIR="$animan_test_dir/cache"
PYTHONPATH=. python3 -c "import animan.models; from animan.database import init_db; init_db()"
PYTHONPATH=. pytest tests/ -v
```

Run frontend regressions and the TypeScript/Vue build from `frontend/`:

```bash
npm ci
npm test
npm run build
```

## License

This project is intended for personal and educational use. See the repository's license information before redistributing it.
