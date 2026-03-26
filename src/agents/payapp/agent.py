"""
PayAppReviewAgent — processes ASSIGNED_TO_AGENT tasks with document_type == PAY_APP.

Pipeline:
  1. Transition task → PROCESSING
  2. Fetch email ingest + extract document text
  3. Call PayAppExtractor (EXTRACT capability)
  4. Call PayAppReviewer (REASON_STANDARD + RED_TEAM_CRITIQUE)
  5. Store initial_review, red_team_critique, final_output to Firestore payapp_reviews/{task_id}
  6. Transition task → STAGED_FOR_REVIEW
"""

import logging
from datetime import datetime, timezone

from ai_engine.engine import AIEngine
from ai_engine.models import AIEngineExhaustedError
from ai_engine.gcp import GCPIntegration

from .extractor import PayAppExtractor
from .reviewer import PayAppReviewer, write_payapp_review

logger = logging.getLogger(__name__)

AGENT_ID = "AGENT-PAYAPP-001"


class PayAppReviewAgent:
    def __init__(self, gcp: GCPIntegration, ai_engine: AIEngine):
        self._gcp = gcp
        self._extractor = PayAppExtractor(ai_engine)
        self._reviewer = PayAppReviewer(ai_engine)

    def run(self) -> list[str]:
        """Process all ASSIGNED_TO_AGENT pay app tasks. Returns list of processed task_ids."""
        if not self._gcp.firestore_client:
            logger.error("Firestore client not available — aborting Pay App Review Agent run.")
            return []

        db = self._gcp.firestore_client
        assigned = (
            db.collection("tasks")
            .where("status", "==", "ASSIGNED_TO_AGENT")
            .where("assigned_agent", "==", AGENT_ID)
            .stream()
        )

        processed: list[str] = []
        for doc in assigned:
            task = doc.to_dict()
            task_id = task.get("task_id", doc.id)
            ingest_id = task.get("ingest_id", "")
            project_id = task.get("project_id", "UNKNOWN")
            logger.info(f"[{task_id}] Pay App Review Agent picking up task.")
            self._process_task(db, task_id, ingest_id, project_id)
            processed.append(task_id)

        return processed

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def _process_task(self, db, task_id: str, ingest_id: str, project_id: str) -> None:
        now = datetime.now(timezone.utc)

        # Step 1: Transition to PROCESSING
        self._transition(db, task_id, "ASSIGNED_TO_AGENT", "PROCESSING",
                         "Pay App Review Agent started.", now)

        # Step 2: Fetch ingest
        ingest = self._fetch_ingest(db, ingest_id, task_id)
        if ingest is None:
            self._set_error(db, task_id, "Could not retrieve ingest document from Firestore.")
            return

        document_text = self._extract_document_text(ingest, task_id)

        # Step 3: Extract pay application data (EXTRACT capability)
        try:
            extraction = self._extractor.extract(document_text, task_id)
        except (ValueError, AIEngineExhaustedError) as e:
            logger.error(f"[{task_id}] Pay app extraction failed: {e}")
            self._set_error(db, task_id, str(e))
            return

        # Step 4: Review extracted data (REASON_STANDARD + RED_TEAM_CRITIQUE)
        try:
            review_result = self._reviewer.review(extraction, task_id, project_id)
        except (ValueError, AIEngineExhaustedError) as e:
            logger.error(f"[{task_id}] Pay app review failed: {e}")
            self._set_error(db, task_id, str(e))
            return

        # Step 5: Store to Firestore payapp_reviews
        try:
            write_payapp_review(db, task_id, project_id, review_result)
        except Exception as e:
            self._set_error(db, task_id, f"Firestore write failed: {e}")
            return

        # Step 6: Transition to STAGED_FOR_REVIEW
        now2 = datetime.now(timezone.utc)
        try:
            snap = db.collection("tasks").document(task_id).get()
            history = snap.to_dict().get("status_history", []) if snap.exists else []
            history.append({
                "from_status": "PROCESSING",
                "to_status": "STAGED_FOR_REVIEW",
                "triggered_by": AGENT_ID,
                "trigger_type": "AGENT",
                "timestamp": now2.isoformat(),
                "notes": "Pay application review complete — awaiting owner review.",
            })
            db.collection("tasks").document(task_id).update({
                "status": "STAGED_FOR_REVIEW",
                "updated_at": now2.isoformat(),
                "agent_id": AGENT_ID,
                "status_history": history,
            })
        except Exception as e:
            logger.error(f"[{task_id}] Failed to transition to STAGED_FOR_REVIEW: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_ingest(self, db, ingest_id: str, task_id: str) -> dict | None:
        try:
            doc = db.collection("email_ingests").document(ingest_id).get()
            if doc.exists:
                return doc.to_dict()
            logger.warning(f"[{task_id}] Ingest {ingest_id} not found.")
            return None
        except Exception as e:
            logger.error(f"[{task_id}] Error fetching ingest: {e}")
            return None

    def _extract_document_text(self, ingest: dict, task_id: str) -> str:
        """Combine email body and attachment text into a single document string."""
        parts = []
        body = ingest.get("body_text", "")
        if body:
            parts.append(f"EMAIL BODY:\n{body}")
        for att in ingest.get("attachments", []):
            att_text = att.get("extracted_text", "")
            if att_text:
                filename = att.get("filename", "attachment")
                parts.append(f"ATTACHMENT ({filename}):\n{att_text}")
        if not parts:
            logger.warning(f"[{task_id}] No document text found in ingest — using subject only.")
            parts.append(ingest.get("subject", "(No content)"))
        return "\n\n".join(parts)

    def _transition(self, db, task_id: str, from_status: str, to_status: str,
                    notes: str, ts: datetime) -> None:
        try:
            snap = db.collection("tasks").document(task_id).get()
            history = snap.to_dict().get("status_history", []) if snap.exists else []
            history.append({
                "from_status": from_status,
                "to_status": to_status,
                "triggered_by": AGENT_ID,
                "trigger_type": "AGENT",
                "timestamp": ts.isoformat(),
                "notes": notes,
            })
            db.collection("tasks").document(task_id).update({
                "status": to_status,
                "updated_at": ts.isoformat(),
                "status_history": history,
            })
        except Exception as e:
            logger.error(f"[{task_id}] Failed to transition to {to_status}: {e}")

    def _set_error(self, db, task_id: str, error_msg: str) -> None:
        now = datetime.now(timezone.utc)
        try:
            snap = db.collection("tasks").document(task_id).get()
            history = snap.to_dict().get("status_history", []) if snap.exists else []
            history.append({
                "from_status": "PROCESSING",
                "to_status": "ERROR",
                "triggered_by": AGENT_ID,
                "trigger_type": "AGENT",
                "timestamp": now.isoformat(),
                "notes": error_msg,
            })
            db.collection("tasks").document(task_id).update({
                "status": "ERROR",
                "error_message": error_msg,
                "updated_at": now.isoformat(),
                "status_history": history,
            })
        except Exception as e:
            logger.error(f"[{task_id}] Failed to write ERROR state: {e}")
