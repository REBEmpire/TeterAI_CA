"""
SubmittalReviewAgent — processes ASSIGNED_TO_AGENT tasks with document_type == SUBMITTAL.

Pipeline:
  1. Transition task → PROCESSING
  2. Fetch email ingest + extract submittal text
  3. Retrieve relevant spec sections from Knowledge Graph
  4. Call all 3 AI models in parallel (generate_all_models)
  5. Parse each model's JSON output into itemized review items
  6. Store all 3 outputs to Firestore (submittal_reviews/{task_id})
  7. Transition task → STAGED_FOR_REVIEW
"""

import logging
import os
from datetime import datetime, timezone

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass
from ai_engine.gcp import GCPIntegration
from knowledge_graph.client import KnowledgeGraphClient

from agents.mixins.red_team import RedTeamMixin

from .reviewer import build_system_prompt, build_user_prompt, parse_review_output

logger = logging.getLogger(__name__)

AGENT_ID = "AGENT-SUBMITTAL-001"

_SUBMITTAL_DOMAIN_CONTEXT = (
    "This is a submittal review for a construction project.\n"
    "Focus your critique on:\n"
    "- Are the specified values vs. submitted values comparison items complete and accurate?\n"
    "- Are major warnings correctly identified as major (not downgraded to minor)?\n"
    "- Are there any spec sections that should have been checked but weren't?\n"
    "- Is the overall recommendation (Approved/Rejected/Revise and Resubmit) correct?\n"
    "- Are ADA/accessibility compliance items flagged where applicable?\n"
    "- Is missing information clearly identified?"
)


class SubmittalReviewAgent(RedTeamMixin):
    def __init__(
        self,
        gcp: GCPIntegration,
        ai_engine: AIEngine,
        kg_client: KnowledgeGraphClient,
    ):
        self._gcp = gcp
        self._engine = ai_engine
        self._kg = kg_client
        # Build system prompt once (reads DOCX files)
        self._system_prompt = build_system_prompt()

    def run(self) -> list[str]:
        """Process all ASSIGNED_TO_AGENT submittal tasks. Returns list of processed task_ids."""
        if not self._gcp.firestore_client:
            logger.error("Firestore client not available — aborting Submittal Review Agent run.")
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
            logger.info(f"[{task_id}] Submittal Review Agent picking up task.")
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
                         "Submittal Review Agent started.", now)

        # Step 2: Fetch ingest
        ingest = self._fetch_ingest(db, ingest_id, task_id)
        if ingest is None:
            self._set_error(db, task_id, "Could not retrieve ingest document from Firestore.")
            return

        submittal_text = self._extract_submittal_text(ingest, task_id)

        # Step 3: Knowledge Graph — retrieve relevant spec sections
        spec_sections = self._fetch_spec_sections(submittal_text, task_id)

        # Step 4: Call all 3 models in parallel
        user_prompt = build_user_prompt(submittal_text, spec_sections, project_id)

        try:
            raw_results = self._engine.generate_all_models(
                AIRequest(
                    capability_class=CapabilityClass.SUBMITTAL_REVIEW,
                    system_prompt=self._system_prompt,
                    user_prompt=user_prompt,
                    task_id=task_id,
                    calling_agent=AGENT_ID,
                    temperature=0.1,
                )
            )
        except Exception as e:
            logger.error(f"[{task_id}] generate_all_models failed: {e}")
            self._set_error(db, task_id, str(e))
            return

        # Step 5: Parse each model's output and run Red Team critique
        model_results: dict[str, dict] = {}
        for tier_num, result in raw_results.items():
            tier_key = f"tier_{tier_num}"
            if isinstance(result, Exception):
                model_results[tier_key] = {
                    "provider": "unknown",
                    "model": "unknown",
                    "error": str(result),
                    "items": {
                        "comparison_table": [],
                        "warnings": [],
                        "missing_info": [],
                        "summary": "",
                    },
                }
            else:
                parsed = parse_review_output(result.content, task_id)

                # Red Team pass — critique the parsed review output.
                # The submittal review has deeply nested lists (comparison_table, warnings,
                # missing_info) that cannot be safely auto-reconciled by apply_critique's
                # top-level key replacement. Instead we carry the critique summary forward
                # as a "red_team_note" on the final_output so reviewers see both passes.
                critique = self.run_red_team(
                    self._engine, parsed, _SUBMITTAL_DOMAIN_CONTEXT, task_id,
                    agent_id=AGENT_ID,
                )
                # final_output carries the original parsed content plus the critique summary
                # as an advisory note; nested list items are not auto-replaced.
                final_output = dict(parsed)
                final_output["red_team_note"] = (
                    f"[{critique.overall_severity}] {critique.summary}"
                )

                model_results[tier_key] = {
                    "provider": result.metadata.provider,
                    "model": result.metadata.model,
                    "items": parsed,
                    "latency_ms": result.metadata.latency_ms,
                    "initial_review": parsed,
                    "red_team_critique": critique.model_dump(),
                    "final_output": final_output,
                }

        # Step 6: Store to Firestore
        try:
            db.collection("submittal_reviews").document(task_id).set({
                "task_id": task_id,
                "project_id": project_id,
                "model_results": model_results,
                "selected_items": {},
                "status": "PENDING_SELECTION",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"[{task_id}] Submittal review stored to Firestore.")
        except Exception as e:
            logger.error(f"[{task_id}] Failed to store submittal review: {e}")
            self._set_error(db, task_id, f"Firestore write failed: {e}")
            return

        # Step 7: Transition to STAGED_FOR_REVIEW
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
                "notes": f"All {len(model_results)} model(s) completed review.",
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

    def _extract_submittal_text(self, ingest: dict, task_id: str) -> str:
        """Combine email body and any text attachment content into a single review document."""
        parts = []
        body = ingest.get("body_text", "")
        if body:
            parts.append(f"EMAIL BODY:\n{body}")
        # Attachment text (if the dispatcher stored extracted text)
        for att in ingest.get("attachments", []):
            att_text = att.get("extracted_text", "")
            if att_text:
                filename = att.get("filename", "attachment")
                parts.append(f"ATTACHMENT ({filename}):\n{att_text}")
        if not parts:
            logger.warning(f"[{task_id}] No submittal text found in ingest — using subject only.")
            parts.append(ingest.get("subject", "(No content)"))
        return "\n\n".join(parts)

    def _fetch_spec_sections(self, query_text: str, task_id: str) -> list[str]:
        """Search KG for relevant spec sections to provide as context."""
        try:
            sections = self._kg.search_spec_sections(query_text[:500], top_k=5)
            return [str(s) for s in sections]
        except Exception as e:
            logger.warning(f"[{task_id}] KG spec search failed: {e}")
            return []

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
