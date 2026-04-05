import logging
import uuid
from datetime import datetime, timezone

from ai_engine.engine import AIEngine
from ai_engine.models import AIEngineExhaustedError
from ai_engine.gcp import GCPIntegration

from audit.logger import audit_logger
from audit.models import AgentActionLog, ErrorLog, ErrorSeverity, SystemEventLog

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
        ingests_processed = 0

        for doc in pending:
            ingests_processed += 1
            ingest = doc.to_dict()
            ingest_id = ingest.get("ingest_id", doc.id)
            # Reuse task_id from ingest record if upload endpoint already created it;
            # otherwise generate a new one (e.g. for email-ingested documents).
            task_id = ingest.get("task_id") or f"TASK-{ingest_id}-{uuid.uuid4().hex[:8].upper()}"
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
                # Source data for SplitViewer
                "sender_name": ingest.get("sender_name", ""),
                "subject": ingest.get("subject", ""),
                "source_email": {
                    "from": f"{ingest.get('sender_name', '')} <{ingest.get('sender_email', '')}>".strip(),
                    "subject": ingest.get("subject", ""),
                    "date": ingest.get("received_at", ""),
                    "body": ingest.get("body_text", ""),
                },
                # attachments: list of {filename, mime_type, size_bytes, drive_file_id}
                "attachments": ingest.get("attachment_metadata", []),
            }

            try:
                # Use merge=True so we preserve fields from upload-created tasks
                db.collection("tasks").document(task_id).set(task_doc, merge=True)
            except Exception as e:
                logger.error(f"[{ingest_id}] Failed to create task doc: {e}")
                # Restore ingest so it can be retried
                try:
                    ingests_ref.document(ingest_id).update({"status": "PENDING_CLASSIFICATION"})
                except Exception:
                    pass
                continue

            # Step 3: Classify via AI Engine (or Short-Circuit)


            task_start_ms = int(datetime.now(timezone.utc).timestamp() * 1000)



            tool_type_hint = ingest.get("tool_type_hint")


            project_id_hint = ingest.get("project_id")



            if tool_type_hint and tool_type_hint not in ("unknown", "auto") and project_id_hint:


                from ai_engine.models import DimensionResult


                from agents.dispatcher.classifier import ClassificationResult





                logger.info(f"[{ingest_id}] Short-circuit: skipping AI classification (tool_type and project pre-specified)")


                classification = ClassificationResult(


                    project_id=DimensionResult(value=project_id_hint, confidence=1.0, reasoning="Pre-specified by user on upload"),


                    document_type=DimensionResult(value=tool_type_hint.upper(), confidence=1.0, reasoning="Pre-specified by user on upload"),


                    phase=DimensionResult(value="construction", confidence=0.8, reasoning="Default for manual upload"),


                    urgency=DimensionResult(value="MEDIUM", confidence=0.7, reasoning="Default for manual upload"),


                    ai_call_id=None


                )


            else:


                try:


                    classification = self._classifier.classify(ingest)


                except AIEngineExhaustedError as e:
                logger.error(f"[{task_id}] AIEngine exhausted: {e}")
                self._set_error(db, task_id, ingest_id, str(e), now)
                audit_logger.log(ErrorLog(
                    component=AGENT_ID,
                    task_id=task_id,
                    error_code="AI_ENGINE_EXHAUSTED",
                    error_message=str(e),
                    severity=ErrorSeverity.ERROR,
                ))
                continue
            except ClassificationParseError as e:
                logger.error(f"[{task_id}] Classification parse error: {e}")
                self._set_error(db, task_id, ingest_id, str(e), now)
                audit_logger.log(ErrorLog(
                    component=AGENT_ID,
                    task_id=task_id,
                    error_code="CLASSIFICATION_PARSE_ERROR",
                    error_message=str(e),
                    severity=ErrorSeverity.ERROR,
                ))
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

            # Emit AGENT_ACTION audit log for this task
            duration_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - task_start_ms
            min_confidence = min(
                classification.project_id.confidence,
                classification.phase.confidence,
                classification.document_type.confidence,
                classification.urgency.confidence,
            )
            subject = ingest.get("subject", "")
            ai_call_ids = [classification.ai_call_id] if classification.ai_call_id else []
            audit_logger.log(AgentActionLog(
                agent_id=AGENT_ID,
                task_id=task_id,
                action="CLASSIFY_AND_ROUTE",
                input_summary=f"ingest={ingest_id} | {subject[:100]}",
                output_summary=(
                    f"{routing.action} → {routing.assigned_agent or 'human'} | {routing.reason}"
                ),
                confidence_score=min_confidence,
                ai_call_ids=ai_call_ids,
                duration_ms=duration_ms,
                status="SUCCESS",
            ))

        # Emit SYSTEM_EVENT audit log for the completed poll run
        audit_logger.log(SystemEventLog(
            event="EMAIL_POLL_COMPLETED",
            component=AGENT_ID,
            details={
                "ingests_processed": ingests_processed,
                "tasks_created": len(processed_task_ids),
            },
            status="SUCCESS",
        ))

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
