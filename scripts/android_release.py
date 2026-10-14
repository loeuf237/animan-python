"""Inspect the packaged Android engine and generate traceable release metadata."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zipfile


def inspect_apk(path):
    names, native = [], []
    def inspect_zip(data, prefix="", depth=0):
        if depth > 3:
            raise ValueError("Unexpected nested Android archives")
        with zipfile.ZipFile(data) as archive:
            for item in archive.infolist():
                name = prefix + item.filename
                names.append(name)
                if item.filename.endswith((".so", ".imy", ".zip")):
                    content = archive.read(item)
                    if content.startswith(b"\x7fELF"):
                        if content[4:6] != b"\x02\x01" or struct.unpack_from("<H", content, 18)[0] != 183:
                            raise ValueError("Non-ARM64 native library: " + name)
                        ph_offset = struct.unpack_from("<Q", content, 32)[0]
                        ph_size, ph_count = struct.unpack_from("<HH", content, 54)
                        for index in range(ph_count):
                            offset = ph_offset + index * ph_size
                            if struct.unpack_from("<I", content, offset)[0] == 1:
                                alignment = struct.unpack_from("<Q", content, offset + 48)[0]
                                if alignment < 16384:
                                    raise ValueError("Native library is not 16 KB aligned: " + name)
                        native.append(name)
                    elif content.startswith(b"PK"):
                        inspect_zip(io.BytesIO(content), name + "/", depth + 1)
    inspect_zip(path)
    for marker in ("frontend/dist/index.html", "android_runtime.py", "animan/services/download_manager", "curl_cffi/_wrapper", "pydantic_core/_pydantic_core", "libffmpegkit"):
        if not any(marker in name for name in names):
            raise ValueError("Missing packaged engine component: " + marker)
    if not native:
        raise ValueError("No native engine libraries found")
    return {"embedded_spa": True, "embedded_python_engine": True, "abi": "arm64-v8a",
            "native_16kb_alignment": True, "native_libraries": native}


def manifest(apk, output, validation=False):
    report = inspect_apk(apk)
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    report.update({"version": "0.1.0", "version_code": 211, "min_android_api": 29,
                   "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                   "physical_device_tested": False, "validation_key_only": validation,
                   "ffmpeg": "dev.ffmpegkit-maintained:ffmpeg-kit-min:8.1.7",
                   "python": "3.13", "curl_cffi": "0.16.3"})
    (output / "Android-build-info.json").write_text(json.dumps(report, indent=2))
    (output / "SHA256SUMS.txt").write_text(hashlib.file_digest(apk.open("rb"), "sha256").hexdigest() + "  " + apk.name + "\n")
    if not validation and not os.getenv("ANIMAN_ANDROID_KEYSTORE"):
        raise RuntimeError("Publication requires the dedicated Android release signing identity")
    print(json.dumps({key: value for key, value in report.items() if key != "native_libraries"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--validation", action="store_true")
    args = parser.parse_args()
    manifest(args.apk, args.output, args.validation)
