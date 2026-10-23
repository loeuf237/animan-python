# AnimeLab

<img src="docs/branding/animelab-wordmark.png" alt="AnimeLab" width="360" />

[![CI](https://github.com/loeuf237/animelab/actions/workflows/ci.yml/badge.svg)](https://github.com/loeuf237/animelab/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/loeuf237/animelab)](https://github.com/loeuf237/animelab/releases/latest)

**AnimeLab** lets you discover, watch, download and organize anime episodes from supported sources. It combines a **Python / FastAPI** engine with a **Vue 3 / TypeScript** interface, available on desktop, Android and in a browser.

## Downloads

Choose a build from [GitHub Releases](https://github.com/loeuf237/animelab/releases). Desktop and Android releases are published separately.

| Platform | Package | Getting started |
| --- | --- | --- |
| Windows x64 | ZIP archive | Extract the entire archive and launch `AnimeLab.exe`. |
| Linux x64 | TAR.GZ archive | Extract and launch `./AnimeLab`. Requires glibc 2.35+. |
| macOS Intel / Apple Silicon | ZIP containing an application | Choose your CPU architecture and open `AnimeLab.app`. **UNTESTED on real Mac hardware; unsigned and not notarized.** |
| Android 10+ / ARM64 | Signed APK, beta | Install the APK. The Python engine and interface are included; no desktop server is required. |
| Browser / mobile web | Web interface | Start the server or Docker container and open its address. |

Desktop packages include Python, the compiled interface, FFmpeg and ffprobe. Windows uses WebView2; Linux uses GTK/WebKit, with an installed-browser fallback when a native window is unavailable.

Android remains a **prerelease**. The [0.1.1 beta release notes](docs/releases/android-v0.1.1-beta.1.md) explain its emulator coverage and pending physical-device validation. Release assets include checksums and build information.

In supporting browsers, install the web interface as a PWA using the browser's install or **Add to Home Screen** option. The AnimeLab server must remain available.

## Main features

- **Browse and search:** built-in French-Manga, VoirAnime and AnimePahe sources, plus supported imported sources. Latest releases, popular titles, genres and tags depend on each source's capabilities.
- **Watch:** streaming and local playback, subtitles, available quality options and saved episode progress.
- **Download:** individual or batch downloads, queue management, pause/resume, bandwidth limits, subtitle processing and integrity checks.
- **Keep versions separate:** VF, VOSTFR and VO selections have distinct identities and filenames to avoid overwriting each other.
- **Organize:** favorites, viewing history, automatic episode tracking and optional Plex/Jellyfin folder layouts.
- **Use on mobile:** responsive screens, English/French interface, light/dark themes and global search with **Ctrl+K / Cmd+K**.

On Android, completed videos can be exported to shared storage. Export failures can be retried without downloading the video again.

## Sources and extensions

Import an Aniyomi-compatible repository from **Sources → Extensions**, then enable the sources you want to use. Source health checks and recipe configuration help diagnose failures.

AnimeLab uses extracted recipes and Python adapters; it does **not execute Aniyomi APKs as an Android extension runtime**. Extensions requiring unsupported custom logic may need an additional adapter. Source availability also depends on external websites.

If a site blocks access or requests verification, AnimeLab offers a manual website link and retry controls. Supported verification windows can capture cookies after you complete verification. Opening an ordinary browser tab alone does not transfer cookies to AnimeLab. Proxy configuration and optional rotation are available in Settings; they do not guarantee access.

## Run from source

Requirements:

- **Python 3.12 or 3.13**; these versions are covered by CI.
- **Node.js 22.12+ and npm** to build the interface.
- **FFmpeg and ffprobe** on `PATH` for media processing and verified subtitle muxing.

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/loeuf237/animelab.git
cd animelab
python3 -m venv .venv
source .venv/bin/activate
```

On Windows, use `python` instead of `python3` if needed and activate with `.\.venv\Scripts\Activate.ps1` in PowerShell.

Install dependencies, build the interface and start the server:

```bash
python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
python run.py
```

Open **[http://localhost:8080/app/](http://localhost:8080/app/)**. Rebuild the interface after changing its source files.

For a native desktop window, install `pywebview` and the platform's WebView dependencies, then run `python desktop.py`. See [desktop package details](docs/desktop-distribution.md) for platform compatibility.

### Configuration and data

Settings controls language, downloads, sources and proxies. For a source checkout, environment variables also configure the server:

| Variable | Purpose | Default |
| --- | --- | --- |
| `ANIMAN_HOST` | Server bind address | `127.0.0.1` |
| `ANIMAN_PORT` | HTTP port | `8080` |
| `ANIMAN_RELOAD` | Reload the development server after code changes | `true` |
| `ANIMAN_DOWNLOAD_DIR` | Download destination | `~/Downloads/Animan` on desktop |

For local-only use without automatic reload, on Linux/macOS:

```bash
ANIMAN_HOST=127.0.0.1 ANIMAN_RELOAD=false python run.py
```

AnimeLab was previously named **Animan**. Internal `animan` package names, `ANIMAN_*` variables, `.animan` data folders and Android ID `com.animan.app` are retained for compatibility. Desktop settings and the library live under `~/.animan`; Android uses private app storage and exports completed media separately.

## Docker

From the cloned repository, with Docker Compose installed:

```bash
docker compose up -d --build --wait
```

Open **[http://localhost:8080/app/](http://localhost:8080/app/)**. The container includes the compiled interface and media tools. Named volumes preserve the library, settings and downloads.

Stop it with `docker compose down`. See the [Docker guide](docs/docker.md) for visible download folders, backups, ports and network access.

## Development and contributions

Bug reports, translations, source adapters, UI improvements and device testing are welcome. [Open an issue](https://github.com/loeuf237/animelab/issues) with reproduction steps, platform and application version; discuss substantial changes before submitting a pull request. Remove cookies, credentials and private URLs from diagnostic material.

For frontend development, keep the Python server running and launch Vite in another terminal:

```bash
cd frontend
npm run dev
```

Vite serves the interface at **http://localhost:5173** and proxies API requests to port **8080**.

[CI](.github/workflows/ci.yml) runs on pushes and pull requests. It checks Python, the frontend build and responsive layouts, Docker persistence and Android resources. Tests use temporary storage. Desktop and Android release workflows are separate.

To run frontend checks locally from `frontend/`:

```bash
npm test
npm run build
npx playwright install --with-deps chromium
npm run test:ui
```

For backend checks, follow the isolated storage setup in [the CI workflow](.github/workflows/ci.yml) before running `python -m pytest tests -q`.

## Documentation

- [Architecture, UML diagrams and improvement plan](docs/architecture/README.md)
- [Desktop distribution](docs/desktop-distribution.md) and [Android build and storage guide](docs/android-distribution.md)
- [Docker setup](docs/docker.md)
- [Mobile UI validation](docs/mobile-ui.md) and [proxy provider study](docs/proxy-providers.md)
- [Release notes](docs/releases/) and [branding assets](docs/branding/README.md)

## License

A project license has not yet been selected. Third-party components retain their own licenses; see the [Android third-party notices](android/app/src/main/assets/THIRD-PARTY-NOTICES.txt) and the notices included in release packages.
