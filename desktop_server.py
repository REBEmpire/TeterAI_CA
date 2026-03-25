"""
TeterAI CA — Desktop server entry point.

This is the PyInstaller entry point. It starts the FastAPI backend
in-process via uvicorn, which is simpler than spawning a subprocess
and gives PyInstaller a clean module graph to analyse.

Usage (development):
    DESKTOP_MODE=true PYTHONPATH=src python desktop_server.py

Usage (packaged — run by Electron):
    ./teterai-backend   (no args; env is set by Electron main.js)
"""
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — must happen before any src imports
# ---------------------------------------------------------------------------

# PyInstaller sets sys._MEIPASS to the temp extraction directory at runtime.
# In development sys._MEIPASS is not set, so we fall back to src/ relative
# to this file.
if hasattr(sys, '_MEIPASS'):
    _base = Path(sys._MEIPASS)
else:
    _base = Path(__file__).parent

_src = _base / 'src'
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# ---------------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------------

os.environ.setdefault('DESKTOP_MODE', 'true')

# ---------------------------------------------------------------------------
# Start server
# ---------------------------------------------------------------------------

import uvicorn  # noqa: E402 — import after path setup

if __name__ == '__main__':
    uvicorn.run(
        'ui.api.server:app',
        host='127.0.0.1',
        port=8000,
        log_level='warning',
        # No reload in production; Electron restarts the process if needed
        reload=False,
    )
