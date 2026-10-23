# AnimeLab

[![CI](https://github.com/loeuf237/animelab/actions/workflows/ci.yml/badge.svg)](https://github.com/loeuf237/animelab/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/loeuf237/animelab)](https://github.com/loeuf237/animelab/releases/latest)

AnimeLab is a Python and Vue application for discovering, watching, downloading and organizing anime episodes.

## Download

Get desktop and Android builds from [GitHub Releases](https://github.com/loeuf237/animelab/releases/latest). macOS builds are untested on real Mac hardware; Android builds are beta releases. AnimeLab also runs in a browser or with [Docker](docs/docker.md).

## Features

- Built-in sources: French-Manga, VoirAnime and AnimePahe.
- Import supported source repositories and Aniyomi recipes.
- Search, browse releases and select episode versions such as VF and VOSTFR.
- Stream video, manage downloads, and organize a personal library.
- English and French interface, desktop, mobile and browser support.

Source availability and extension compatibility depend on the external sites.

## Run from source

Requirements: Python 3.12 or 3.13, Node.js 22.12+, FFmpeg and ffprobe for subtitle muxing.

```bash
git clone https://github.com/loeuf237/animelab.git
cd animelab
python3 -m pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
python3 run.py
```

Open [http://localhost:8080](http://localhost:8080). For a native desktop window, run `python3 desktop.py`.

## Docker

With Docker Compose installed, run:

```bash
docker compose up -d --build
```

Open [http://localhost:8080/app/](http://localhost:8080/app/). See the [Docker guide](docs/docker.md) for storage and configuration details.

## Development

The backend uses FastAPI and the interface uses Vue 3 with TypeScript. See [CI](.github/workflows/ci.yml) for automated checks and [architecture docs](docs/architecture/README.md) for diagrams and design notes.

## License

AnimeLab does not yet have a project license. Third-party licenses remain in effect; see [Android notices](android/app/src/main/assets/THIRD-PARTY-NOTICES.txt).
