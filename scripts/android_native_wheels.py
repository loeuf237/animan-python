"""Build the missing CPython 3.13 Android wheels with Chaquopy's toolchain.

The upstream curl_cffi ARM64 wheel is used unchanged. Never rename desktop wheels
or relax their dependency metadata to make a dependency probe appear successful.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen

CHAQUOPY_COMMIT = "884ec5f14591d69844e20c9dc6a6a9c5d1ba0a41"
TARGET_VERSION = "3.13.16-0"


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def build(root: Path):
    checkout = root / "build/android-native/chaquopy"
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "https://github.com/chaquo/chaquopy.git", str(checkout))
    run("git", "checkout", "--detach", CHAQUOPY_COMMIT, cwd=checkout)
    run("git", "restore", "server/pypi/build-wheel.py", "server/pypi/packages/cffi/meta.yaml", cwd=checkout)
    pypi = checkout / "server/pypi"
    run(sys.executable, "-m", "pip", "install", "-r", str(pypi / "requirements.txt"))
    target = checkout / f"maven/com/chaquo/python/target/{TARGET_VERSION}"
    if not target.exists():
        run("bash", "target/download-target.sh", str(target), cwd=checkout)
    ffi_dir = pypi / "dist/chaquopy-libffi"
    ffi_dir.mkdir(parents=True, exist_ok=True)
    filename = "chaquopy_libffi-3.3-3-py3-none-android_24_arm64_v8a.whl"
    with urlopen("https://chaquo.com/pypi-13.1/chaquopy-libffi/" + filename, timeout=60) as response:
        (ffi_dir / filename).write_bytes(response.read())
    recipe = pypi / "packages/cffi/meta.yaml"
    recipe.write_text(recipe.read_text().replace('version: "1.17.1"', 'version: "2.0.0"'))
    # pydantic-core requires the full CPython API, including datetime. The generic
    # legacy Rust recipe assumes abi3 and would incorrectly remove these APIs.
    tool = pypi / "build-wheel.py"
    contents = tool.read_text()
    old = '"PYO3_NO_PYTHON": "1",'
    if old not in contents:
        raise RuntimeError("Chaquopy Rust configuration changed; review the native build")
    contents = contents.replace(old, '"PYO3_CROSS_LIB_DIR": f"{self.host_env}/chaquopy/lib",')
    # New target packages provide both libpython3 and libpython3.13. The legacy
    # helper attempts to create the same convenience symlink for both libraries.
    contents = contents.replace('if link_filename != filename:',
        'if link_filename != filename and not exists(f"{reqs_lib_dir}/{link_filename}"):')
    tool.write_text(contents)
    core = pypi / "packages/pydantic-core"
    core.mkdir(exist_ok=True)
    (core / "meta.yaml").write_text('''package:
  name: pydantic-core
  version: "2.41.5"
build:
  number: 0
requirements:
  build:
    - rust
''')
    for package in ("cffi", "pydantic-core"):
        run(sys.executable, "build-wheel.py", "--python", "3.13", "--abi", "arm64-v8a", package, cwd=pypi)
    output = root / "android/wheels"
    output.mkdir(parents=True, exist_ok=True)
    for package in ("cffi", "pydantic-core"):
        wheels = list((pypi / "dist" / package).glob("*cp313*arm64_v8a.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected one ARM64 CPython 3.13 wheel for {package}: {wheels}")
        shutil.copy2(wheels[0], output / wheels[0].name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    build(parser.parse_args().root.resolve())
