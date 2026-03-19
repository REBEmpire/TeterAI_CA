import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from ai_engine.engine import AIEngine
from ai_engine.gcp import GCPIntegration
from agents.dispatcher import DispatcherAgent
from agents.rfi import RFIAgent
from knowledge_graph.client import KnowledgeGraphClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI web application (import for uvicorn: main:app)
# ---------------------------------------------------------------------------
from ui.api.server import app  # noqa: F401  — re-exported for uvicorn


# ---------------------------------------------------------------------------
# Agent runner (batch / Cloud Run Jobs mode)
# ---------------------------------------------------------------------------

def main():
    gcp = GCPIntegration()
    ai_engine = AIEngine()
    kg_client = KnowledgeGraphClient()

    # Phase 1: Dispatcher — classify and route incoming emails
    logger.info("TeterAI CA — Dispatcher Agent starting.")
    dispatcher = DispatcherAgent(gcp=gcp, ai_engine=ai_engine)
    dispatched = dispatcher.run()
    if dispatched:
        logger.info(f"Dispatcher processed {len(dispatched)} ingest(s): {dispatched}")
    else:
        logger.info("Dispatcher run complete — no pending ingests found.")

    # Phase 2: RFI Agent — process tasks assigned to AGENT-RFI-001
    logger.info("TeterAI CA — RFI Agent starting.")
    rfi_agent = RFIAgent(gcp=gcp, ai_engine=ai_engine, kg_client=kg_client)
    rfi_processed = rfi_agent.run()
    if rfi_processed:
        logger.info(f"RFI Agent processed {len(rfi_processed)} task(s): {rfi_processed}")
    else:
        logger.info("RFI Agent run complete — no assigned tasks found.")

    kg_client.close()


if __name__ == "__main__":
    main()
