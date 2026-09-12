import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from run import app
from animan.database import init_db
from animan.models.download_task import DownloadTask, DownloadStatus
from animan.services.download_manager import download_manager
from animan.services.library_service import library_service

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    init_db()
    tmp_dir = tmp_path_factory.mktemp("media_test")
    fake_video = tmp_dir / "test_video.mp4"
    fake_data = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" * 100
    fake_video.write_bytes(fake_data)

    fake_sub = tmp_dir / "test_video.fr.vtt"
    fake_sub.write_text("WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\nHello world", encoding="utf-8")

    task = DownloadTask(
        id="media-test-task-1",
        animeName="Media Test Anime",
        episodeNumber=1,
        fileName="test_video.mp4",
        savePath=str(fake_video),
        savePathSubtitle=json.dumps([str(fake_sub)]),
        status=DownloadStatus.COMPLETED,
        totalBytes=len(fake_data),
    )
    download_manager.tasks[task.id] = task
    library_service.save_task(task)

    with TestClient(app) as c:
        yield c, task, fake_data

def test_full_video_stream(client):
    c, task, fake_data = client
    resp = c.get(f"/api/media/stream/{task.id}")
    assert resp.status_code == 200
    assert resp.headers.get("Accept-Ranges") == "bytes"
    assert int(resp.headers.get("Content-Length")) == len(fake_data)
    assert resp.content == fake_data

def test_range_video_stream(client):
    c, task, fake_data = client
    start = 10
    end = 49
    resp = c.get(
        f"/api/media/stream/{task.id}",
        headers={"Range": f"bytes={start}-{end}"}
    )
    assert resp.status_code == 206
    assert resp.headers.get("Content-Range") == f"bytes {start}-{end}/{len(fake_data)}"
    assert resp.headers.get("Accept-Ranges") == "bytes"
    expected_len = end - start + 1
    assert int(resp.headers.get("Content-Length")) == expected_len
    assert resp.content == fake_data[start:end+1]

def test_subtitles_endpoints(client):
    c, task, _ = client
    resp = c.get(f"/api/media/subtitles/{task.id}")
    assert resp.status_code == 200
    subs = resp.json()
    assert len(subs) == 1
    assert subs[0]["srclang"] == "fr"

    # Stream subtitle
    sub_resp = c.get(subs[0]["src"])
    assert sub_resp.status_code == 200
    assert "WEBVTT" in sub_resp.text
