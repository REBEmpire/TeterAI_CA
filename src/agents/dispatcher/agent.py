import logging
import uuid
from datetime import datetime, timezone

from ai_engine.engine import AIEngine
from ai_engine.models import AIEngineExhaustedError
from ai_engine.gcp import GCPIntegration

from .classifier import EmailClassifier, ClassificationParseError
from .router import DispatcherRouter
from .models import TaskStatus

logger = logging.getLogger(__name__)

AGENT_ID = "AGENT-DISPATCH-001"


class DispatcherAgent:
    def __init__(self, gcp: GCPIntegration, ai_engine: AIEngine):
        self._gcp = gcp
        self._classifier = EmailClassifier(ai_engine)
        self._router = DispatcherRouter()

    def run(self) -> list[str]:
        """Process all PENDING_CLASSIFICATION email ingests. Returns list of task_ids created."""
        if not self._gcp.firestore_client:
            logger.error("Firestore client not available — aborting dispatcher run.")
            return []

        db = self._gcp.firestore_client
        ingests_ref = db.collection("email_ingests")
        pending = ingests_ref.where("status", "==", "PENDING_CLASSIFICATION").stream()

        processed_task_ids: list[str] = []

        for doc in pending:
            ingest = doc.to_dict()
            ingest_id = ingest.get("ingest_id", doc.id)
            task_id = f"TASK-{ingest_id}-{uuid.uuid4().hex[:8].upper()}"
            logger.info(f"[{ingest_id}] Processing ingest → {task_id}")

            # Step 1: Mark ingest as CLASSIFYING to prevent duplicate processing
            try:
                ingests_ref.document(ingest_id).update({"status": "CLASSIFYING"})
            except Exception as e:
                logger.error(f"[{ingest_id}] Failed to update ingest to CLASSIFYING: {e}")
                continue

            now = datetime.now(timezone.utc)

            # Step 2: Create task document in CLASSIFYING state
            initial_history_entry = {
                "from_status": None,
                "to_status": TaskStatus.CLASSIFYING,
                "triggered_by": AGENT_ID,
                "trigger_type": "AGENT",
                "timestamp": now.isoformat(),
                "notes": "Task created by Dispatcher Agent",
            }
            task_doc = {
                "task_id": task_id,
                "ingest_id": ingest_id,
                "status": TaskStatus.CLASSIFYING,
                "assigned_agent": None,
                "assigned_reviewer": None,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "status_history": [initial_history_entry],
                "project_id": None,
                "project_number": ingest.get("subject_hints", {}).get("project_number_hint"),
                "document_type": None,
                "document_number": ingest.get("subject_hints", {}).get("doc_number_hint"),
                "phase": None,
                "urgency": None,
                "classification_confidence": None,
                "draft_drive_path": None,
                "final_drive_path": None,
                "error_message": None,
                "correction_captured": False,
            }

            try:
                db.collection("tasks").document(task_id).set(task_doc)
            except Exception as e:
                logger.error(f"[{ingest_id}] Failed to create task doc: {e}")
                # Restore ingest so it can be retried
                try:
                    ingests_ref.document(ingest_id).update({"status": "PENDING_CLASSIFICATION"})
                except Exception:
                    pass
                continue

            # Step 3: Classify via AI Engine
            try:
                classification = self._classifier.classify(ingest)
            except AIEngineExhaustedError as e:
                logger.error(f"[{task_id}] AIEngine exhausted: {e}")
                self._set_error(db, task_id, ingest_id, str(e), now)
                continue
            except ClassificationParseError as e:
                logger.error(f"[{task_id}] Classification parse error: {e}")
                self._set_error(db, task_id, ingest_id, str(e), now)
                continue

            # Step 4: Routing decision
            routing = self._router.route(classification)

            # Step 5: Update task with classification result and final status
            final_status = (
                TaskStatus.ASSIGNED_TO_AGENT
                if routing.action == "ASSIGN_TO_AGENT"
                else TaskStatus.ESCALATED_TO_HUMAN
            )
            now2 = datetime.now(timezone.utc)
            final_history_entry = {
                "from_status": TaskStatus.CLASSIFYING,
                "to_status": final_status,
                "triggered_by": AGENT_ID,
                "trigger_type": "AGENT",
                "timestamp": now2.isoformat(),
                "notes": routing.reason,
            }

            try:
                db.collection("tasks").document(task_id).update({
                    "status": final_status,
                    "assigned_agent": routing.assigned_agent,
                    "project_id": classification.project_id.value,
                    "phase": classification.phase.value,
                    "document_type": classification.document_type.value,
                    "urgency": classification.urgency.value,
                    "classification_confidence": {
                        "project_id": classification.project_id.confidence,
                        "phase": classification.phase.confidence,
                        "document_type": classification.document_type.confidence,
                        "urgency": classification.urgency.confidence,
                    },
                    "updated_at": now2.isoformat(),
                    "status_history": [initial_history_entry, final_history_entry],
                })
            except Exception as e:
                logger.error(f"[{task_id}] Failed to update task to final status: {e}")
                continue

            # Step 6: Mark ingest as processed
            ingest_final_status = "PROCESSED" if routing.action == "ASSIGN_TO_AGENT" else "ESCALATED"
            try:
                ingests_ref.document(ingest_id).update({
                    "status": ingest_final_status,
                    "task_id": task_id,
                })
            except Exception as e:
                logger.warning(
                    f"[{task_id}] Failed to update ingest final status "
                    f"(task still created): {e}"
                )

            logger.info(
                f"[{task_id}] → {final_status} | "
                f"agent={routing.assigned_agent} | {routing.reason}"
            )
            processed_task_ids.append(task_id)

        return processed_task_ids

    def _set_error(
        self,
        db,
        task_id: str,
        ingest_id: str,
        error_msg: str,
        created_at: datetime,
    ) -> None:
        now = datetime.now(timezone.utc)
        try:
            db.collection("tasks").document(task_id).update({
                "status": TaskStatus.ERROR,
                "error_message": error_msg,
                "updated_at": now.isoformat(),
                "status_history": [
                    {
                        "from_status": None,
                        "to_status": TaskStatus.CLASSIFYING,
                        "triggered_by": AGENT_ID,
                        "trigger_type": "AGENT",
                        "timestamp": created_at.isoformat(),
                        "notes": "Task created by Dispatcher Agent",
                    },
                    {
                        "from_status": TaskStatus.CLASSIFYING,
                        "to_status": TaskStatus.ERROR,
                        "triggered_by": AGENT_ID,
                        "trigger_type": "AGENT",
                        "timestamp": now.isoformat(),
                        "notes": error_msg,
                    },
                ],
            })
            db.collection("email_ingests").document(ingest_id).update({"status": "ERROR"})
        except Exception as e:
            logger.error(f"[{task_id}] Failed to write ERROR state to Firestore: {e}")
