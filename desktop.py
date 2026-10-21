"""Desktop launcher and offline checks for the packaged Python + Vue app."""
import argparse
import gc
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser
from animan import __version__

# Windowed PyInstaller executables have no console streams on Windows.
for _stream in ("stdin", "stdout", "stderr"):
    if getattr(sys, _stream) is None:
        setattr(sys, _stream, open(os.devnull, "r" if _stream == "stdin" else "w", encoding="utf-8"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("animan.desktop")
if os.getenv("ANIMAN_LOG_FILE"):
    logging.getLogger().addHandler(logging.FileHandler(os.environ["ANIMAN_LOG_FILE"], encoding="utf-8"))


def configure_bundled_tools():
    if getattr(sys, "frozen", False):
        directory = Path(sys._MEIPASS) / "bin"
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


def find_available_port(default_port=8080):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", default_port))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_server(port, max_retries=80, delay=.25):
    opener = build_opener(ProxyHandler({}))
    for _ in range(max_retries):
        try:
            with opener.open(f"http://127.0.0.1:{port}/openapi.json", timeout=.5) as response:
                if json.load(response)["info"]["version"] == __version__:
                    return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(delay)
    return False


def start_server(port):
    os.environ.update(ANIMAN_PORT=str(port), ANIMAN_HOST="127.0.0.1", ANIMAN_RELOAD="false")
    from animan.config import settings
    settings.PORT, settings.HOST = port, "127.0.0.1"
    from run import app
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        log_level="warning", log_config=None, access_log=False, timeout_graceful_shutdown=10))
    worker = threading.Thread(target=server.run, daemon=True, name="AnimeLabServer")
    worker.start()
    if not wait_for_server(port):
        server.should_exit = True
        worker.join(timeout=15)
        raise RuntimeError("AnimeLab server did not become ready")
    return server, worker


def self_test():
    with tempfile.TemporaryDirectory(prefix="animan-package-check-") as directory:
        os.environ.update(ANIMAN_DB_PATH=str(Path(directory) / "test.sqlite3"),
            ANIMAN_CACHE_DIR=str(Path(directory) / "cache"), ANIMAN_DOWNLOAD_DIR=directory,
            ANIMAN_STARTUP_REFRESH="false")
        server, worker = start_server(find_available_port(0))
        try:
            from run import frontend_dist
            index = frontend_dist / "index.html"
            if not index.is_file() or not (frontend_dist / "assets").is_dir():
                raise RuntimeError("Packaged Vue frontend is missing")
            import re
            opener = build_opener(ProxyHandler({}))
            base = f"http://127.0.0.1:{server.config.port}"
            with opener.open(base + "/spa/", timeout=5) as response:
                html = response.read().decode()
            assets = re.findall(r'(?:src|href)="(/assets/[^" ]+)"', html)
            if not assets: raise RuntimeError("Vue asset URLs are missing")
            for asset in assets:
                with opener.open(base + asset, timeout=5) as response:
                    if not response.read(): raise RuntimeError("Empty frontend asset")
            from curl_cffi.requests import Session
            with Session(impersonate="chrome", trust_env=False) as client:
                response = client.get(base + "/openapi.json", timeout=5)
                response.raise_for_status()
                assert response.json()["info"]["version"] == __version__
            import webview
            from animan.services.extractors import extractor_registry
            import yt_dlp
            target = Path(directory) / "probe.mp4"
            for tool in ("ffmpeg", "ffprobe"):
                if not shutil.which(tool): raise RuntimeError(f"Missing bundled media tool: {tool}")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                "color=c=black:s=32x32:d=1", "-c:v", "mpeg4", str(target)],
                stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=30)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(target)],
                                   stdin=subprocess.DEVNULL, check=True, capture_output=True, text=True, timeout=30)
            assert any(stream["codec_type"] == "video" for stream in json.loads(probe.stdout)["streams"])
            from animan.services.verification_service import verification_service
            result = verification_service.verify_file(str(target))
            if not result.valid: raise RuntimeError(f"Packaged media integrity check failed: {result.error}")
            print(json.dumps({"version":__version__, "frontend":True, "http":True,
                              "curl_cffi":True, "media_tools":True, "gui_hardware_tested":False}))
        finally:
            server.should_exit = True
            worker.join(timeout=20)
            if worker.is_alive(): raise RuntimeError("Packaged server failed to stop")
            from animan.database import engine
            engine.dispose()
            gc.collect()  # Release SQLite handles before Windows removes temporary storage.


def main():
    parser = argparse.ArgumentParser(description="AnimeLab desktop")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--self-test", action="store_true", help="Offline packaged backend/frontend/media checks")
    parser.add_argument("--headless", action="store_true", help="Run without opening a window")
    args = parser.parse_args()
    configure_bundled_tools()
    if args.self_test:
        self_test()
        return
    server, worker = start_server(find_available_port(int(os.getenv("ANIMAN_PORT", "8080"))))
    url = f"http://127.0.0.1:{server.config.port}/spa/"
    logger.info("AnimeLab %s ready at %s", __version__, url)
    try:
        if args.headless:
            while worker.is_alive(): time.sleep(.5)
            return
        try:
            import webview
            from animan.config import settings
            from animan.services.browser_verification import browser_verification
            from animan.services.source_http import USER_AGENT
            webview.create_window("AnimeLab", url, width=1280, height=820, min_size=(800, 600))
            browser_verification.webview_opener = lambda target: webview.create_window(
                "AnimeLab — Site verification", target, width=900, height=700)
            try:
                webview.start(user_agent=USER_AGENT, icon=str(settings.STATIC_DIR / "img/icon-512.png"))
            finally:
                browser_verification.webview_opener = None
        except Exception as error:
            logger.warning("Native window unavailable (%s); using the installed browser", error)
            webbrowser.open(url)
            while worker.is_alive(): time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        from animan.services.download_manager import download_manager
        download_manager.pause_all_downloads()
        server.should_exit = True
        worker.join(timeout=20)
        if not worker.is_alive():
            from animan.database import engine
            engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("AnimeLab failed to start or complete its package checks")
        raise SystemExit(1)
