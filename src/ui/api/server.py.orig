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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load credentials BEFORE importing any module that creates service singletons.
#
# routes.py and workflow.router both trigger `kg_client = KnowledgeGraphClient()`
# at import time, which reads NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD from
# os.environ.  If push_to_env() runs after those imports the driver is always
# initialised with None credentials and every KG call returns empty data.
# ---------------------------------------------------------------------------
try:
    from config.local_config import LocalConfig
    LocalConfig.ensure_exists().push_to_env()
    logger.info("LocalConfig credentials loaded into environment")
except Exception as _lc_err:
    logger.warning(f"LocalConfig not loaded: {_lc_err}")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router
from workflow.router import router as workflow_router

_DESKTOP_MODE = os.environ.get("DESKTOP_MODE", "").lower() in ("true", "1")
if not _DESKTOP_MODE:
    try:
        from config.local_config import LocalConfig as _LC
        _DESKTOP_MODE = _LC.ensure_exists().desktop_mode
    except Exception:
        pass


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


def _run_dispatcher() -> None:
    """Background thread: run DispatcherAgent to classify PENDING_CLASSIFICATION ingests."""
    try:
        from config.local_config import LocalConfig
        from ai_engine.gcp import gcp_integration
        from ai_engine.engine import engine as ai_engine
        from agents.dispatcher.agent import DispatcherAgent

        cfg = LocalConfig.ensure_exists()
        interval = cfg.poll_interval_seconds
        dispatcher = DispatcherAgent(gcp=gcp_integration, ai_engine=ai_engine)

        logger.info(f"Dispatcher started — polling every {interval}s")
        while True:
            try:
                task_ids = dispatcher.run()
                if task_ids:
                    logger.info(f"Dispatcher: classified {len(task_ids)} ingest(s): {task_ids}")
            except Exception as e:
                logger.error(f"Dispatcher poll error: {e}")
            time.sleep(interval)
    except Exception as e:
        logger.error(f"Dispatcher failed to start: {e}")


def _run_tool_agents() -> None:
    """Background thread: run all tool agents to process ASSIGNED_TO_AGENT tasks."""
    try:
        from config.local_config import LocalConfig
        from ai_engine.gcp import gcp_integration
        from ai_engine.engine import engine as ai_engine
        from knowledge_graph.client import kg_client
        from agents.rfi.agent import RFIAgent
        from agents.submittal.agent import SubmittalReviewAgent
        from agents.cost.agent import CostAnalyzerAgent
        from agents.payapp.agent import PayAppReviewAgent
        from agents.schedule.agent import ScheduleReviewAgent

        cfg = LocalConfig.ensure_exists()
        interval = cfg.poll_interval_seconds

        agents = [
            RFIAgent(gcp=gcp_integration, ai_engine=ai_engine, kg_client=kg_client),
            SubmittalReviewAgent(gcp=gcp_integration, ai_engine=ai_engine, kg_client=kg_client),
            CostAnalyzerAgent(gcp=gcp_integration, ai_engine=ai_engine),
            PayAppReviewAgent(gcp=gcp_integration, ai_engine=ai_engine),
            ScheduleReviewAgent(gcp=gcp_integration, ai_engine=ai_engine),
        ]

        logger.info(f"Tool agents started — {len(agents)} agents, polling every {interval}s")
        while True:
            for agent in agents:
                try:
                    processed = agent.run()
                    if processed:
                        logger.info(
                            f"{agent.__class__.__name__}: processed {len(processed)} task(s): {processed}"
                        )
                except Exception as e:
                    logger.error(f"{agent.__class__.__name__} run error: {e}")
            time.sleep(interval)
    except Exception as e:
        logger.error(f"Tool agents failed to start: {e}")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if _DESKTOP_MODE:
        t = threading.Thread(target=_run_inbox_watcher, daemon=True, name="inbox-watcher")
        t.start()
        d = threading.Thread(target=_run_dispatcher, daemon=True, name="dispatcher")
        d.start()
        a = threading.Thread(target=_run_tool_agents, daemon=True, name="tool-agents")
        a.start()
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
