import pytest
import io
import struct
import zipfile

from animan.config import settings


@pytest.fixture
def extension_apk():
    """Small DEX string table in an APK; exercises the real recipe parser offline."""
    def build(base_url='https://source.example', selector='.new-card'):
        strings = [base_url, selector]
        dex = bytearray(112 + 4 * len(strings))
        dex[:8] = b'dex\n035\0'
        struct.pack_into('<II', dex, 0x38, len(strings), 112)
        for index, value in enumerate(strings):
            struct.pack_into('<I', dex, 112 + index * 4, len(dex))
            encoded = value.encode()
            assert len(encoded) < 128
            dex.extend(bytes([len(value)]) + encoded + b'\0')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('classes.dex', dex)
        return buffer.getvalue()
    return build


@pytest.fixture(autouse=True)
def _tmdb_test_key(monkeypatch):
    """Les tests TMDB mockent le réseau mais exigent une clé non vide.

    La clé n'est plus codée en dur dans la configuration : on injecte une valeur
    factice uniquement pour la durée des tests.
    """
    monkeypatch.setattr(settings, "TMDB_API_KEY", "test-key", raising=False)
