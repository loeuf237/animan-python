import base64
import json
import subprocess

import httpx
import pytest

from animan import media_tools
from animan.android_security import AndroidSessionMiddleware


@pytest.fixture
def native(monkeypatch):
    class Bridge:
        result = {"returncode": 0, "stdout": "native output", "stderr": ""}
        calls = []
        @classmethod
        def execute(cls, tool, arguments, timeout):
            cls.calls.append((tool, json.loads(arguments), timeout))
            return json.dumps(cls.result)
    monkeypatch.setattr(media_tools, "_native_media", Bridge)
    return Bridge


def test_native_media_preserves_argument_boundaries_and_failure(native):
    result = media_tools.run(["ffmpeg", "-i", "/private/episode with spaces.mp4"], check=True, timeout=12)
    assert result.stdout == "native output"
    assert native.calls == [("ffmpeg", ["-i", "/private/episode with spaces.mp4"], 12000)]
    native.result = {"returncode": 1, "stderr": "bad subtitle"}
    with pytest.raises(subprocess.CalledProcessError):
        media_tools.run(["ffmpeg", "-version"], check=True)
    native.result = {"returncode": -1, "timedOut": True}
    with pytest.raises(subprocess.TimeoutExpired):
        media_tools.run(["ffprobe", "input.mp4"], timeout=1)


def test_native_media_rejects_global_working_directory(native):
    with pytest.raises(ValueError):
        media_tools.run(["ffmpeg", "-version"], cwd="/private")


def test_aes_platforms_match_nist_vector(monkeypatch):
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    ciphertext = bytes.fromhex("7649abac8119b246cee98e9b12e9197d")
    plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    assert media_tools.decrypt_aes_cbc(ciphertext, key, iv) == plaintext
    class AES:
        @staticmethod
        def decrypt(data, encoded_key, encoded_iv, unpad):
            assert base64.b64decode(data) == ciphertext
            assert base64.b64decode(encoded_key) == key
            assert base64.b64decode(encoded_iv) == iv
            assert not unpad
            return base64.b64encode(plaintext).decode()
    monkeypatch.setattr(media_tools, "_native_aes", AES)
    assert media_tools.decrypt_aes_cbc(ciphertext, key, iv) == plaintext
    with pytest.raises(ValueError):
        media_tools.decrypt_aes_cbc(b"short", key, iv)


@pytest.mark.asyncio
async def test_android_loopback_authentication_includes_assets():
    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    token = "a" * 64
    app = AndroidSessionMiddleware(endpoint, token)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
        assert (await client.get("/spa/")).status_code == 401
        assert (await client.get("/assets/app.js", headers={"X-Animan-Session": "wrong"})).status_code == 401
        assert (await client.get("/spa/", headers={"Cookie": b'animan_android_session="\xff"'})).status_code == 401
        assert (await client.get("/spa/", headers={"X-Animan-Session": token})).status_code == 200
        client.cookies.set("animan_android_session", token)
        assert (await client.get("/api/download/status")).status_code == 200


@pytest.mark.asyncio
async def test_android_rejects_unauthenticated_websocket():
    async def endpoint(*args):
        raise AssertionError("Unauthenticated socket reached the engine")
    output = []
    async def send(message): output.append(message)
    await AndroidSessionMiddleware(endpoint, "a" * 64)({"type": "websocket", "headers": []}, None, send)
    assert output == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.asyncio
async def test_native_export_does_not_complete_a_paused_transfer(monkeypatch, tmp_path):
    from animan import platform_events
    from animan.models.download_task import DownloadTask, DownloadStatus
    from animan.services.download_manager import DownloadManagerService
    from animan.services.library_service import library_service
    from animan.services.verification_service import verification_service, VerificationResult
    manager = DownloadManagerService()
    task = DownloadTask(status=DownloadStatus.DOWNLOADING, savePath=str(tmp_path / "episode.mp4"))
    monkeypatch.setattr(verification_service, "verify_file", lambda **kwargs: VerificationResult(valid=True, status="VALID"))
    monkeypatch.setattr(library_service, "save_task", lambda task: None)
    def export(task):
        assert task.status == DownloadStatus.DOWNLOADING
        task.paused = True
    monkeypatch.setattr(platform_events, "completed_handler", export)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.PAUSED
    assert task.completedAt is None


def test_interrupted_mux_is_restored_as_paused(monkeypatch, tmp_path):
    from animan.models.download_task import DownloadTask, DownloadStatus
    from animan.services.download_manager import DownloadManagerService
    from animan.services.library_service import library_service
    manager = DownloadManagerService()
    task = DownloadTask(status=DownloadStatus.MUXING, savePath=str(tmp_path / "missing.mp4"))
    class Entity:
        def to_task(self): return task
    monkeypatch.setattr(library_service, "get_unfinished_tasks", lambda: [Entity()])
    monkeypatch.setattr(library_service, "save_task", lambda task: None)
    manager.init_from_db()
    assert task.status == DownloadStatus.PAUSED
    task.status = DownloadStatus.MUXING
    monkeypatch.setattr(manager, "_trigger_process_queue", lambda: None)
    manager.pause_all_downloads()
    assert task.paused and task.status == DownloadStatus.PAUSED


@pytest.mark.asyncio
async def test_storage_controls_validate_actions_and_retry_export(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from animan import platform_events
    from animan.routers.library import router
    from animan.routers.download import router as downloads_router
    from animan.services.download_manager import download_manager
    from animan.services.library_service import library_service
    from animan.models.download_task import DownloadTask, DownloadStatus
    app = FastAPI()
    app.include_router(router)
    app.include_router(downloads_router)
    calls = []
    monkeypatch.setattr(platform_events, 'storage_status_handler', lambda: {'android': True, 'authorized': False})
    monkeypatch.setattr(platform_events, 'storage_action_handler', lambda action: calls.append(action) or {'authorized': True})
    source = tmp_path / 'download.mp4'
    source.write_bytes(b'private media')
    task = DownloadTask(status=DownloadStatus.COMPLETED, savePath=str(source))
    monkeypatch.setattr(download_manager, 'tasks', {task.id: task})
    monkeypatch.setattr(download_manager, 'broadcast_update', lambda task: None)
    monkeypatch.setattr(library_service, 'save_task', lambda task: None)
    def failed_export(task):
        raise PermissionError('Folder access was revoked')
    monkeypatch.setattr(platform_events, 'completed_handler', failed_export)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
        assert (await client.get('/api/system/android/storage')).json()['authorized'] is False
        assert (await client.post('/api/download', json={})).status_code == 409
        assert (await client.post('/api/system/android/storage', json={'action': 'arbitrary_command'})).status_code == 400
        assert calls == []
        assert (await client.post('/api/system/android/storage', json={'action': 'choose_directory'})).json()['authorized'] is True
        assert calls == ['choose_directory']
        assert (await client.post('/api/system/android/export', json={'taskId': task.id})).status_code == 409
        assert task.status == DownloadStatus.COMPLETED and source.read_bytes() == b'private media'
        assert 'Folder access was revoked' in task.error
        monkeypatch.setattr(platform_events, 'completed_handler', lambda task: {'uris': ['content://downloads/1'], 'destination': 'Downloads/Animan'})
        assert (await client.post('/api/system/android/export', json={'taskId': task.id})).json()['success']
        assert task.error is None and source.exists()
        task.status = DownloadStatus.PAUSED
        assert (await client.post('/api/system/android/export', json={'taskId': task.id})).status_code == 409


@pytest.mark.asyncio
async def test_storage_failure_never_invents_available_capacity(monkeypatch, tmp_path):
    from animan.routers.library import get_system_storage
    from animan.config import settings
    from animan import platform_events
    import shutil
    monkeypatch.setattr(settings, 'DOWNLOAD_DIR', str(tmp_path))
    monkeypatch.setattr(platform_events, 'storage_status_handler', None)
    def denied(path): raise PermissionError('Storage unavailable')
    monkeypatch.setattr(shutil, 'disk_usage', denied)
    result = await get_system_storage()
    assert result['totalBytes'] is None and result['freeBytes'] is None
    assert result['error'] == 'Storage unavailable'
