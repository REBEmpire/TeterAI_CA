import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from ai_engine.engine import AIEngine
from ai_engine.gcp import GCPIntegration
from agents.dispatcher import DispatcherAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("TeterAI CA — Dispatcher Agent starting.")
    gcp = GCPIntegration()
    ai_engine = AIEngine()

    agent = DispatcherAgent(gcp=gcp, ai_engine=ai_engine)
    task_ids = agent.run()

    if task_ids:
        logger.info(f"Dispatcher processed {len(task_ids)} ingest(s): {task_ids}")
    else:
        logger.info("Dispatcher run complete — no pending ingests found.")


if __name__ == "__main__":
    main()
