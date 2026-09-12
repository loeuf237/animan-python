import pytest
from fastapi.testclient import TestClient
from run import app
from animan.database import init_db

@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c

def test_html_pages(client):
    # Home
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Animan" in resp.text

    # Downloads
    resp = client.get("/downloads")
    assert resp.status_code == 200
    assert "téléchargements" in resp.text.lower()

    # Library
    resp = client.get("/library")
    assert resp.status_code == 200
    assert "bibliothèque" in resp.text.lower()

    # History
    resp = client.get("/history")
    assert resp.status_code == 200
    assert "historique" in resp.text.lower()

def test_download_settings(client):
    # GET settings
    resp = client.get("/api/download/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "maxConcurrentDownloads" in data
    assert "globalSpeedLimit" in data

    # POST settings
    resp = client.post("/api/download/settings", json={
        "maxConcurrentDownloads": 4,
        "globalSpeedLimit": 2048000,
        "plexOrganization": True,
        "selectedUserAgent": "Chrome"
    })
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # Verify updated settings
    resp = client.get("/api/download/settings")
    data = resp.json()
    assert data["maxConcurrentDownloads"] == 4
    assert data["globalSpeedLimit"] == 2048000
    assert data["plexOrganization"] is True
    assert data["selectedUserAgent"] == "Chrome"

def test_favorites_api(client):
    url = "https://example.com/anime/test-api"
    title = "Test API Anime"

    # Add favorite
    resp = client.post("/api/favorites", json={
        "url": url,
        "title": title,
        "imageUrl": "https://img.com/pic.jpg",
        "source": "french-manga"
    })
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # Check favorite
    resp = client.get(f"/api/favorites/check?url={url}")
    assert resp.status_code == 200
    assert resp.json().get("isFavorite") is True

    # Auto download toggle
    resp = client.patch("/api/favorites/auto-download", json={
        "url": url,
        "autoDownload": True
    })
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # Delete favorite
    resp = client.request("DELETE", "/api/favorites", json={"url": url})
    assert resp.status_code == 200
    assert resp.json().get("success") is True

def test_progress_api(client):
    url = "https://example.com/anime/progress-test"
    resp = client.post("/api/progress/watched", json={
        "animeUrl": url,
        "animeName": "Progress Test",
        "episodeNumber": "5",
        "version": "VOSTFR"
    })
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # Check progress
    resp = client.get(f"/api/progress?animeUrl={url}")
    assert resp.status_code == 200
    progs = resp.json()
    assert len(progs) > 0
    assert progs[0]["episodeNumber"] == 5
    assert progs[0]["watched"] is True

def test_download_controls(client):
    resp = client.post("/api/download/pause-all")
    assert resp.status_code == 200

    resp = client.post("/api/download/resume-all")
    assert resp.status_code == 200

    resp = client.post("/api/download/clean")
    assert resp.status_code == 200

    resp = client.get("/api/download/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

def test_system_storage_api(client):
    resp = client.get("/api/system/storage")
    assert resp.status_code == 200
    data = resp.json()
    assert "totalBytes" in data
    assert "usedBytes" in data
    assert "freeBytes" in data
    assert "usedPercent" in data

def test_watchdog_check_api(client):
    resp = client.post("/api/watchdog/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert "newEpisodes" in data

def test_downloads_page_and_storage_card_removal(client):
    resp = client.get("/downloads")
    assert resp.status_code == 200
    html = resp.text

    # Verify storage card was removed
    assert "sidebar-storage-card" not in html
    assert "storage-percent" not in html

    # Verify download tabs and badges
    assert 'id="tab-badge-queue"' in html
    assert 'id="tab-badge-done"' in html
    assert 'id="tab-badge-all"' in html

    # Verify empty notes exist
    assert 'id="active-empty-note"' in html
    assert 'id="queue-empty-note"' in html
    assert 'id="done-empty-note"' in html
    assert 'id="dl-empty"' in html

def test_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Paramètres" in resp.text
    assert "settings-page-layout" in resp.text
    assert "save-settings-btn" in resp.text

def test_system_storage_real_stats(client):
    resp = client.get("/api/system/storage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalBytes"] > 0
    assert data["freeBytes"] > 0
    assert data["usedBytes"] >= 0
    assert "downloadDir" in data

def test_clear_history_memory_sync(client):
    from animan.services.download_manager import download_manager
    from animan.models.download_task import DownloadTask, DownloadStatus
    task = DownloadTask(
        id="test-clear-sync-1",
        animeName="Test Sync Anime",
        episodeNumber=1,
        fileName="test_sync.mp4",
        downloadPageUrl="https://example.com/test",
        status=DownloadStatus.COMPLETED
    )
    download_manager.tasks[task.id] = task
    download_manager.task_order.append(task.id)

    resp = client.request("DELETE", "/api/history?animeName=Test%20Sync%20Anime")
    assert resp.status_code == 200
    assert "test-clear-sync-1" not in download_manager.tasks

