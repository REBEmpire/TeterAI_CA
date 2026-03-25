# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TeterAI CA backend.

Produces a self-contained onedir bundle (dist/teterai-backend/) that
Electron copies into app resources via electron-builder extraResources.

Build command (from repo root):
    pyinstaller teterai-backend.spec

Output:
    dist/teterai-backend/teterai-backend[.exe]   <- executable Electron spawns
    dist/teterai-backend/_internal/              <- bundled libs + data

Requirements:
    pip install pyinstaller
    # All runtime deps must be installed in the active Python environment.
    # For desktop-only mode: uv sync  (cloud + kg extras NOT required)
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH)   # repo root
SRC  = ROOT / 'src'

# ---------------------------------------------------------------------------
# Data files bundled into the package
# ---------------------------------------------------------------------------
# Format: (source_path_or_glob, dest_dir_inside_bundle)

datas = [
    # Entire src/ tree — agents, api, config, db, storage, integrations, etc.
    (str(SRC), 'src'),
    # Bundled React web UI (served by FastAPI staticfiles from within the bundle)
    (str(ROOT / 'src' / 'ui' / 'web' / 'dist'), 'src/ui/web/dist'),
]

# ---------------------------------------------------------------------------
# Hidden imports
# (modules that PyInstaller's static analysis misses due to dynamic imports)
# ---------------------------------------------------------------------------

hiddenimports = [
    # ASGI server
    'uvicorn',
    'uvicorn.main',
    'uvicorn.config',
    'uvicorn.server',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.middleware',
    'uvicorn.middleware.proxy_headers',
    # FastAPI / Starlette
    'fastapi',
    'starlette',
    'starlette.routing',
    'starlette.responses',
    'starlette.staticfiles',
    'starlette.middleware.cors',
    # Pydantic v2
    'pydantic',
    'pydantic.v1',
    # LiteLLM — loads providers dynamically
    'litellm',
    'litellm.main',
    'litellm.utils',
    # Local DB
    'aiosqlite',
    'sqlite3',
    # Auth
    'jwt',
    'jwt.algorithms',
    # Document parsing
    'pypdf',
    'docx',
    'docx.oxml',
    # Email parsing (stdlib)
    'email',
    'email.policy',
    'email.parser',
    'email.message',
    # Multipart uploads
    'multipart',
    'python_multipart',
    # HTTP client
    'httpx',
    # Misc stdlib used by agents
    'uuid',
    'json',
    'logging',
    'threading',
    'pathlib',
    'shutil',
    'mimetypes',
    're',
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    [str(ROOT / 'desktop_server.py')],
    pathex=[str(ROOT), str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Cloud libs — not needed in desktop mode
        'google.cloud.firestore',
        'google.cloud.secretmanager',
        'google_auth_oauthlib',
        # Knowledge graph — optional; excluded from base bundle
        'neo4j',
        'neo4j_graphrag',
        # Test libs
        'pytest',
        'pytest_asyncio',
        'pytest_mock',
        # Heavy ML libs from litellm that we don't use
        'torch',
        'tensorflow',
        'transformers',
        'sklearn',
        'numpy',
        'pandas',
        # GUI libs not needed in headless server mode
        'tkinter',
        'wx',
        'PyQt5',
        'PyQt6',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='teterai-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # <-- no terminal window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='teterai-backend',  # output dir: dist/teterai-backend/
)
