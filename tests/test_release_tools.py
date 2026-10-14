import hashlib
import sys
import pytest
from scripts import desktop_release


def test_publication_rejects_missing_platform_and_checksums_exact_files(tmp_path, monkeypatch):
    names = ['Windows-x64.zip', 'Linux-x64.tar.gz', 'macOS-arm64-UNTESTED.zip', 'macOS-x64-UNTESTED.zip']
    for name in names[:-1]:
        (tmp_path / ('Animan-v0.1.0-' + name)).write_bytes(b'package')
    monkeypatch.setattr(sys, 'argv', ['release','checksums',str(tmp_path)])
    with pytest.raises(RuntimeError, match='incomplete'):
        desktop_release.checksums()
    (tmp_path / ('Animan-v0.1.0-' + names[-1])).write_bytes(b'mac')
    (tmp_path / 'build-info.json').write_bytes(b'{}')
    desktop_release.checksums()
    for line in (tmp_path / 'SHA256SUMS.txt').read_text().splitlines():
        digest, filename = line.split('  ')
        assert hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest() == digest
    assert len((tmp_path / 'SHA256SUMS.txt').read_text().splitlines()) == 5


def test_preparation_rejects_mismatched_release_version(monkeypatch):
    monkeypatch.setenv('RELEASE_TAG','v2.1.0')
    with pytest.raises(ValueError, match='Tag'):
        desktop_release.prepare()
