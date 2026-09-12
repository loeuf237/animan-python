import pytest
import os
import tempfile
from pathlib import Path
from animan.models.download_task import DownloadTask, DownloadStatus
from animan.services.download_manager import download_manager

@pytest.mark.asyncio
async def test_html_response_rejection(tmp_path):
    """Vérifie que _download_single_file rejette immédiatement un contenu HTML."""
    task = DownloadTask(
        animeName="Test Anime",
        episodeNumber=1,
        fileName="test_ep1.mp4",
        fileUrl="https://example.com/test",
        savePath=str(tmp_path / "test_ep1.mp4"),
    )
    # Si on essaie de télécharger une URL qui renvoie une page web au lieu d'une vidéo
    # (par exemple https://example.com qui renvoie du text/html)
    with pytest.raises(Exception) as excinfo:
        await download_manager._download_single_file(task, "https://example.com")
    
    assert "html" in str(excinfo.value).lower()
    # S'assurer que le fichier final n'a PAS été créé avec du HTML
    assert not (tmp_path / "test_ep1.mp4").exists()

def test_redownload_preserves_healthy_part(tmp_path):
    """Vérifie que redownload_task ne détruit pas un fichier .part binaire sain."""
    target = tmp_path / "healthy.mp4"
    part = tmp_path / "healthy.mp4.part"
    
    # Créer un fichier partiel binaire de 50 Ko (non-HTML)
    with open(part, "wb") as f:
        f.write(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 50000)
    
    task = DownloadTask(
        id="test-healthy-task-1",
        animeName="Healthy Anime",
        episodeNumber=1,
        fileName="healthy.mp4",
        fileUrl="https://example.com/stream",
        savePath=str(target),
        status=DownloadStatus.FAILED,
        downloadedBytes=50032,
        totalBytes=100000,
    )
    download_manager.tasks[task.id] = task
    
    # Relancer la tâche
    res = download_manager.redownload_task(task.id, force=False)
    
    # Le fichier .part doit être conservé intact !
    assert part.exists()
    assert part.stat().st_size == 50012
    assert res.downloadedBytes == 50012

def test_redownload_purges_corrupted_html(tmp_path):
    """Vérifie que redownload_task purge un fichier HTML corrompu."""
    target = tmp_path / "corrupted.mp4"
    with open(target, "wb") as f:
        f.write(b"<!doctype html><html><head><title>Error</title></head></html>")
    
    task = DownloadTask(
        id="test-corrupted-task-1",
        animeName="Corrupted Anime",
        episodeNumber=1,
        fileName="corrupted.mp4",
        fileUrl="https://example.com/stream",
        savePath=str(target),
        status=DownloadStatus.FAILED,
    )
    download_manager.tasks[task.id] = task
    
    res = download_manager.redownload_task(task.id, force=False)
    
    # Le fichier HTML corrompu doit être purgé
    assert not target.exists()
    assert res.downloadedBytes == 0
    assert res.progress == 0.0
