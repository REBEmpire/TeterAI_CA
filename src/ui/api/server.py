"""
TeterAI FastAPI application.

Provides:
  - REST API at /api/v1/...
  - Static file serving for the React web app build at /

Run with:
  uvicorn ui.api.server:app --reload

Desktop mode (local storage, no cloud):
  DESKTOP_MODE=true PYTHONPATH=src uvicorn ui.api.server:app --reload
"""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router
from workflow.router import router as workflow_router

logger = logging.getLogger(__name__)

# Load credentials from ~/.teterai/config.env into the environment before any
# service clients are initialised. This is a no-op on production where env vars
# are already injected by the Cloud Run configuration.
try:
    from config.local_config import LocalConfig
    LocalConfig.ensure_exists().push_to_env()
    logger.info("LocalConfig credentials loaded into environment")
except Exception as _lc_err:
    logger.warning(f"LocalConfig not loaded: {_lc_err}")

_DESKTOP_MODE = os.environ.get("DESKTOP_MODE", "").lower() in ("true", "1")


def _run_inbox_watcher() -> None:
    """Background thread: poll the local inbox folder at a configurable interval."""
    try:
        from config.local_config import LocalConfig
        from integrations.local_inbox.watcher import LocalInboxWatcher
        from ai_engine.gcp import gcp_integration

        cfg = LocalConfig.ensure_exists()
        db = gcp_integration.firestore_client
        watcher = LocalInboxWatcher(cfg, db)
        interval = cfg.poll_interval_seconds

        logger.info(f"Inbox watcher started — polling {cfg.inbox_path} every {interval}s")
        while True:
            try:
                new_ids = watcher.poll()
                if new_ids:
                    logger.info(f"Inbox watcher: created {len(new_ids)} ingest(s): {new_ids}")
            except Exception as e:
                logger.error(f"Inbox watcher error: {e}")
            time.sleep(interval)
    except Exception as e:
        logger.error(f"Inbox watcher failed to start: {e}")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if _DESKTOP_MODE:
        t = threading.Thread(target=_run_inbox_watcher, daemon=True, name="inbox-watcher")
        t.start()
    yield


app = FastAPI(
    title="TeterAI CA — Web API",
    version="0.1.0",
    description="Human-in-the-loop review interface for Teter Construction Administration.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=_lifespan,
)

# CORS — allow the React dev server in development
_allowed_origins = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all API routes under /api/v1
app.include_router(router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1/workflow")

# Serve the compiled React app from src/ui/web/dist (production build)
_web_dist = Path(__file__).parent.parent / "web" / "dist"
if _web_dist.exists():
    app.mount("/", StaticFiles(directory=str(_web_dist), html=True), name="web")
