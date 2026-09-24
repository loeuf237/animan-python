import os
import sys
import socket
import threading
import time
import logging
import webbrowser
from typing import Optional

# Configuration des logs pour l'exécutable
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("animan.desktop")

def find_available_port(default_port: int = 8080) -> int:
    """Tente d'utiliser le port par défaut ou trouve un port dynamique libre."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", default_port)) != 0:
            return default_port
    # Trouver un port libre aléatoire
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def wait_for_server(port: int, max_retries: int = 40, delay: float = 0.25) -> bool:
    """Attend que le serveur Uvicorn local soit prêt à accepter les connexions."""
    for _ in range(max_retries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return True
        except Exception:
            pass
        time.sleep(delay)
    return False

def main():
    logger.info("Démarrage d'Animan Desktop...")
    
    port = find_available_port(int(os.getenv("ANIMAN_PORT", "8080")))
    os.environ["ANIMAN_PORT"] = str(port)
    os.environ["ANIMAN_HOST"] = "127.0.0.1"
    os.environ["ANIMAN_RELOAD"] = "false"

    from animan.config import settings
    settings.PORT = port
    settings.HOST = "127.0.0.1"

    from run import app
    import uvicorn

    server_config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(server_config)

    # Lancement du serveur Uvicorn en arrière-plan
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    logger.info("En attente de la disponibilité du serveur sur le port %d...", port)
    if not wait_for_server(port):
        logger.error("Le serveur Animan n'a pas répondu à temps.")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    logger.info("Serveur Animan opérationnel à l'adresse : %s", url)

    # Tentative d'affichage dans une fenêtre native WebView (Edge WebView2 sous Windows)
    has_webview = False
    try:
        import webview
        has_webview = True
        logger.info("Lancement de l'interface native via pywebview...")
        window = webview.create_window(
            title="Animan - Anime Downloader",
            url=url,
            width=1280,
            height=820,
            min_size=(960, 600),
            confirm_close=False,
        )
        webview.start()
    except Exception as e:
        logger.warning("pywebview n'a pas pu initialiser la fenêtre native (%s). Bascule sur le navigateur par défaut.", e)
        has_webview = False

    if not has_webview:
        # Fallback classique navigateur
        logger.info("Ouverture dans le navigateur par défaut : %s", url)
        webbrowser.open(url)
        try:
            while server_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Arrêt d'Animan...")

if __name__ == "__main__":
    main()
