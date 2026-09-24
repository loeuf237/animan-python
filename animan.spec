# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path

block_cipher = None

# Racine du projet
project_dir = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(project_dir, 'animan', 'templates'), os.path.join('animan', 'templates')),
    (os.path.join(project_dir, 'animan', 'static'), os.path.join('animan', 'static')),
]

hiddenimports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespans',
    'uvicorn.lifespans.on',
    'uvicorn.lifespans.off',
    'fastapi',
    'pydantic',
    'pydantic_core',
    'sqlalchemy',
    'sqlalchemy.dialects.sqlite',
    'jinja2',
    'aiofiles',
    'httpx',
    'socksio',
    'bs4',
    'lxml',
    'yt_dlp',
    'webview',
    'webview.platforms.edgechromium',
    'webview.platforms.winforms',
    'animan.routers.anime',
    'animan.routers.download',
    'animan.routers.library',
    'animan.routers.media',
    'animan.routers.extensions',
    'animan.routers.sources',
    'animan.routers.i18n',
    'animan.services.container_adapters',
    'animan.services.extractors',
]

a = Analysis(
    ['desktop.py'],
    pathex=[project_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Animan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Animan',
)
