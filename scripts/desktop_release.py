"""Prepare, check and archive desktop release artifacts on their native runners."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animan import __version__


def prepare():
    tag = os.environ.get('RELEASE_TAG', 'v' + __version__)
    if tag != 'v' + __version__: raise ValueError('Tag does not match the application version')
    target = ROOT / 'build' / 'release-metadata'
    target.mkdir(parents=True, exist_ok=True)
    packages = {item.metadata['Name']:item.version for item in metadata.distributions()}
    tools = {}
    for name in ('ffmpeg', 'ffprobe'):
        path = os.getenv('ANIMAN_' + name.upper() + '_BINARY') or shutil.which(name)
        if not path: raise RuntimeError(f'{name} is not installed')
        result = subprocess.run([path, '-version'], capture_output=True, text=True, check=True)
        tools[name] = result.stdout.splitlines()[0]
        license_text = subprocess.run([path, '-L'], capture_output=True, text=True, check=True)
        (target / (name + '-license.txt')).write_text(license_text.stdout + license_text.stderr)
    manifest = {'version':__version__, 'commit':subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
                'platform':platform.system(), 'architecture':platform.machine(), 'python':platform.python_version(),
                'macos_hardware_tested':False, 'media_tools':tools, 'packages':packages}
    (target / 'build-info.json').write_text(json.dumps(manifest, indent=2))
    (target / 'MEDIA-SOURCES.txt').write_text(
        'FFmpeg project: https://ffmpeg.org/\nLinux: Ubuntu package repositories\n'
        'macOS: Homebrew ffmpeg formula\nWindows: Chocolatey ffmpeg package / Gyan builds\n'
        'Build versions and license notices are recorded beside this file.\n')
    license_dir = target / 'python-package-licenses'
    for package in metadata.distributions():
        for item in package.files or []:
            if re.search(r'(license|copying|notice)', item.name, re.I) and item.name.lower().endswith(('.txt','.md','.rst','license','copying','notice')):
                source = package.locate_file(item)
                if source.is_file():
                    destination = license_dir / package.metadata['Name'] / str(item).split('.dist-info/')[-1]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)


def check():
    if sys.platform == 'darwin': binary = ROOT / 'dist/Animan.app/Contents/MacOS/Animan'
    else: binary = ROOT / ('dist/Animan/Animan.exe' if os.name == 'nt' else 'dist/Animan/Animan')
    logfile = ROOT / 'build' / 'packaged-self-test.log'
    logfile.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(binary), '--self-test'], timeout=90,
                            env={**os.environ, 'ANIMAN_LOG_FILE':str(logfile)})
    if logfile.exists(): print(logfile.read_text())
    if result.returncode: raise RuntimeError('Packaged offline check failed')


def archive():
    label = os.environ['PLATFORM_LABEL']
    if not re.fullmatch(r'[A-Za-z0-9-]+',label): raise ValueError('Invalid platform label')
    output = ROOT / 'release-assets'
    output.mkdir(exist_ok=True)
    filename = f'Animan-v{__version__}-{label}'
    if sys.platform == 'darwin':
        destination = output / (filename + '-UNTESTED.zip')
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(ROOT / 'dist/Animan.app'),str(destination)],check=True)
    elif os.name == 'nt':
        destination = output / (filename + '.zip')
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as handle:
            for path in (ROOT / 'dist/Animan').rglob('*'):
                if path.is_file(): handle.write(path,path.relative_to(ROOT / 'dist'))
    else:
        destination = output / (filename + '.tar.gz')
        with tarfile.open(destination,'w:gz') as handle:
            handle.add(ROOT / 'dist/Animan',arcname='Animan')
    shutil.copyfile(ROOT / 'build/release-metadata/build-info.json',output / (filename + '-build-info.json'))
    print(destination)


def checksums():
    root = Path(sys.argv[2])
    archives = sorted(p for p in root.iterdir() if p.name.endswith(('.zip','.tar.gz')))
    expected = {'Windows-x64','Linux-x64','macOS-arm64-UNTESTED','macOS-x64-UNTESTED'}
    if {p.name.removeprefix(f'Animan-v{__version__}-').removesuffix('.tar.gz').removesuffix('.zip') for p in archives} != expected:
        raise RuntimeError('Release is incomplete or contains unexpected platform archives')
    with (root / 'SHA256SUMS.txt').open('w') as handle:
        for path in sorted(p for p in root.iterdir() if p.name != 'SHA256SUMS.txt'):
            with path.open('rb') as source:
                digest = hashlib.file_digest(source,'sha256').hexdigest()
            handle.write(f'{digest}  {path.name}\n')


if __name__ == '__main__':
    {'prepare':prepare,'check':check,'archive':archive,'checksums':checksums}[sys.argv[1]]()
