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
