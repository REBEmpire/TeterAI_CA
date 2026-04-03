import logging
import os
import uuid
from datetime import datetime, timezone

from ai_engine.engine import AIEngine
from ai_engine.models import AIEngineExhaustedError
from ai_engine.gcp import GCPIntegration
from knowledge_graph.client import KnowledgeGraphClient

from .extractor import RFIExtractor, RFIExtractionParseError
from .drafter import RFIDrafter
from .models import KGLookupResult, RFIProcessingResult

logger = logging.getLogger(__name__)

AGENT_ID = "AGENT-RFI-001"

_THRESHOLD_STAGE = float(os.environ.get("RFI_CONFIDENCE_THRESHOLD_STAGE", 0.75))
_THRESHOLD_ESCALATE = float(os.environ.get("RFI_CONFIDENCE_THRESHOLD_ESCALATE", 0.50))


class RFIAgent:
    def __init__(
        self,
        gcp: GCPIntegration,
        ai_engine: AIEngine,
        kg_client: KnowledgeGraphClient,
    ):
        self._gcp = gcp
        self._extractor = RFIExtractor(ai_engine)
        self._drafter = RFIDrafter(ai_engine)
        self._kg = kg_client

    def run(self) -> list[str]:
        """Process all ASSIGNED_TO_AGENT tasks for AGENT-RFI-001. Returns list of task_ids processed."""
        if not self._gcp.firestore_client:
            logger.error("Firestore client not available — aborting RFI Agent run.")
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
            logger.info(f"[{task_id}] RFI Agent picking up task.")

            result = self._process_task(db, task_id, ingest_id, project_id)
            processed.append(task_id)
            logger.info(f"[{task_id}] → {result.final_status}")

        return processed

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def _process_task(
        self,
        db,
        task_id: str,
        ingest_id: str,
        project_id: str,
    ) -> RFIProcessingResult:
        now = datetime.now(timezone.utc)

        # Step 1: Transition to PROCESSING
        self._transition(db, task_id, "ASSIGNED_TO_AGENT", "PROCESSING", "RFI Agent started processing", now)

        # Step 2: Fetch ingest document
        ingest = self._fetch_ingest(db, ingest_id, task_id)
        if ingest is None:
            self._set_error(db, task_id, "Could not retrieve ingest document from Firestore")
            return RFIProcessingResult(task_id=task_id, final_status="ERROR")

        # Step 3: Extract RFI details (EXTRACT capability)
        try:
            extraction = self._extractor.extract(ingest, task_id)
            self._save_thought_chain(
                db, task_id, "01_extraction", {"result": extraction.model_dump()}
            )
        except (RFIExtractionParseError, AIEngineExhaustedError) as e:
            logger.error(f"[{task_id}] Extraction failed: {e}")
            self._set_error(db, task_id, str(e))
            return RFIProcessingResult(task_id=task_id, final_status="ERROR")

        # Step 4: Knowledge Graph lookup (spec sections + project-doc fallback)
        kg_result = self._kg_lookup(extraction, task_id, project_id=project_id)
        self._save_thought_chain(db, task_id, "02_kg_queries", {
            "spec_sections_found": len(kg_result.spec_sections),
            "playbook_rules_found": len(kg_result.playbook_rules),
        })

        # Step 5: Assign internal RFI number (Phase 0: Firestore counter)
        rfi_number_internal = self._assign_rfi_number(db, project_id)

        # Note: Step 3 (source doc retrieval) and Step 4 (MULTIMODAL drawing analysis)
        # from the spec are Phase 0 stubs — Drive integration is not yet wired.
        # Drawing sheets referenced by the contractor are captured in extraction and
        # will be used once Drive integration lands.
        if extraction.referenced_drawing_sheets:
            logger.info(
                f"[{task_id}] Drawing sheets referenced: {extraction.referenced_drawing_sheets} "
                f"— Drive retrieval not yet implemented (Phase 0 stub)."
            )

        # Step 6: Draft response (REASON_DEEP capability)
        try:
            draft = self._drafter.draft(
                extraction=extraction,
                kg_result=kg_result,
                task_id=task_id,
                project_id=project_id,
                rfi_number_internal=rfi_number_internal,
            )
            self._save_thought_chain(db, task_id, "04_draft_generation", {
                "confidence_score": draft.confidence_score,
                "review_flag": draft.review_flag,
                "references_count": len(draft.references),
            })
        except AIEngineExhaustedError as e:
            logger.error(f"[{task_id}] Draft generation failed: {e}")
            self._set_error(db, task_id, str(e))
            return RFIProcessingResult(task_id=task_id, extraction=extraction, final_status="ERROR")

        # Step 7: Determine final status based on confidence
        if draft.confidence_score < _THRESHOLD_ESCALATE:
            final_status = "ESCALATED_TO_HUMAN"
            draft_path = None
            self._update_rfi_log(db, project_id, rfi_number_internal, extraction, task_id, "ESCALATED")
        else:
            final_status = "STAGED_FOR_REVIEW"
            draft_path = self._save_draft(db, task_id, draft, project_id=project_id)
            self._update_rfi_log(db, project_id, rfi_number_internal, extraction, task_id, "STAGED")

        # Transition task to final status
        notes = (
            f"Confidence: {draft.confidence_score:.2f}"
            + (f" | Flag: {draft.review_flag}" if draft.review_flag else "")
            if draft.confidence_score >= _THRESHOLD_ESCALATE
            else f"Confidence {draft.confidence_score:.2f} below escalation threshold — escalated without draft"
        )
        now2 = datetime.now(timezone.utc)
        try:
            update_fields: dict = {
                "status": final_status,
                "updated_at": now2.isoformat(),
                "document_number": rfi_number_internal,
            }
            if draft_path:
                update_fields["draft_drive_path"] = draft_path
            if draft.review_flag:
                update_fields["review_flag"] = draft.review_flag

            task_snap = db.collection("tasks").document(task_id).get()
            history = task_snap.to_dict().get("status_history", []) if task_snap.exists else []
            history.append({
                "from_status": "PROCESSING",
                "to_status": final_status,
                "triggered_by": AGENT_ID,
                "trigger_type": "AGENT",
                "timestamp": now2.isoformat(),
                "notes": notes,
            })
            update_fields["status_history"] = history
            db.collection("tasks").document(task_id).update(update_fields)
        except Exception as e:
            logger.error(f"[{task_id}] Failed to update task to {final_status}: {e}")

        return RFIProcessingResult(
            task_id=task_id,
            extraction=extraction,
            draft=draft,
            final_status=final_status,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_ingest(self, db, ingest_id: str, task_id: str) -> dict | None:
        try:
            doc = db.collection("email_ingests").document(ingest_id).get()
            if doc.exists:
                return doc.to_dict()
            logger.warning(f"[{task_id}] Ingest {ingest_id} not found in Firestore.")
            return None
        except Exception as e:
            logger.error(f"[{task_id}] Error fetching ingest {ingest_id}: {e}")
            return None

    def _kg_lookup(self, extraction, task_id: str, project_id: str = "") -> KGLookupResult:
        query = extraction.question
        if extraction.referenced_spec_sections:
            query += " " + " ".join(extraction.referenced_spec_sections)

        try:
            spec_sections = self._kg.search_spec_sections(query, top_k=5)
        except Exception as e:
            logger.warning(f"[{task_id}] KG spec search failed: {e}")
            spec_sections = []

        # Fallback: if SpecSection nodes are sparse (doc-intel hasn't been run yet),
        # search the full CADocument library so the AI still gets project context.
        similar_project_docs: list = []
        if len(spec_sections) < 3:
            try:
                similar_project_docs = self._kg.search_project_documents(
                    query,
                    project_id=project_id or None,
                    doc_types=["RFI", "SUBMITTAL", "BULLETIN", "GENERAL"],
                    top_k=5,
                )
                if similar_project_docs:
                    logger.info(
                        f"[{task_id}] Spec sections sparse ({len(spec_sections)}); "
                        f"using {len(similar_project_docs)} similar project docs as fallback."
                    )
            except Exception as e:
                logger.warning(f"[{task_id}] KG project-doc fallback search failed: {e}")

        try:
            playbook_rules = self._kg.get_agent_playbook(AGENT_ID)
        except Exception as e:
            logger.warning(f"[{task_id}] KG playbook lookup failed: {e}")
            playbook_rules = []

        try:
            workflow_steps = self._kg.get_document_workflow("RFI")
        except Exception as e:
            logger.warning(f"[{task_id}] KG workflow lookup failed: {e}")
            workflow_steps = []

        return KGLookupResult(
            spec_sections=spec_sections,
            playbook_rules=playbook_rules,
            workflow_steps=workflow_steps,
            similar_project_docs=similar_project_docs,
        )

    def _assign_rfi_number(self, db, project_id: str) -> str:
        """Phase 0 stub: increment counter in Firestore rfi_counters/{project_id}."""
        counter_ref = db.collection("rfi_counters").document(project_id)
        try:
            from google.cloud.firestore import Increment
            counter_ref.set({"count": 0}, merge=True)
            counter_ref.update({"count": Increment(1)})
            doc = counter_ref.get()
            count = doc.to_dict().get("count", 1)
            return f"RFI-{count:03d}"
        except Exception as e:
            logger.warning(f"RFI counter update failed for project {project_id}: {e}")
            return f"RFI-{uuid.uuid4().hex[:4].upper()}"

    def _save_draft(self, db, task_id: str, draft, project_id: str = "") -> str:
        """Persist draft to Firestore thought_chains and upload to Drive Agent Workspace."""
        content = (
            f"{draft.header}\n\n"
            f"RESPONSE:\n{draft.response_text}\n\n"
            f"REFERENCES:\n" + "\n".join(f"- {r}" for r in draft.references) +
            "\n\n[CA Staff Signature Block Placeholder]"
        )

        # 1. Always write to Firestore (UI reads from here)
        firestore_payload: dict = {
            "draft_rfi_response": content,
            "confidence_score": draft.confidence_score,
            "review_flag": draft.review_flag,
            "references": draft.references,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Include Red Team audit trail if present
        if draft.initial_review is not None:
            firestore_payload["initial_review"] = draft.initial_review
        if draft.red_team_critique is not None:
            firestore_payload["red_team_critique"] = draft.red_team_critique
        if draft.final_output is not None:
            firestore_payload["final_output"] = draft.final_output

        try:
            db.collection("thought_chains").document(task_id).set(
                firestore_payload,
                merge=True,
            )
        except Exception as e:
            logger.warning(f"[{task_id}] Could not save draft to Firestore: {e}")

        # 2. Also upload to Drive Agent Workspace
        drive_path = f"04 - Agent Workspace/Thought Chains/{task_id}/draft_rfi_response.md"
        try:
            from integrations.drive.service import DriveService
            drive = DriveService()
            folder_id = drive.get_folder_id(project_id, "04 - Agent Workspace/Thought Chains") if project_id else None
            if folder_id:
                drive.upload_file(
                    folder_id=folder_id,
                    filename=f"{task_id}_draft_rfi_response.md",
                    content=content.encode("utf-8"),
                    mime_type="text/markdown",
                )
                logger.info(f"[{task_id}] Draft uploaded to Drive Agent Workspace.")
            else:
                logger.info(f"[{task_id}] Drive folder not found for project '{project_id}' — draft in Firestore only.")
        except Exception as e:
            logger.warning(f"[{task_id}] Drive draft upload failed (Firestore fallback active): {e}")

        return drive_path

    def _update_rfi_log(
        self, db, project_id: str, rfi_number_internal: str,
        extraction, task_id: str, status: str
    ) -> None:
        """Phase 0 stub: write RFI log entry to Firestore rfi_log collection."""
        doc_id = f"{project_id}-{rfi_number_internal}"
        try:
            db.collection("rfi_log").document(doc_id).set({
                "rfi_number_internal": rfi_number_internal,
                "rfi_number_submitted": extraction.rfi_number_submitted,
                "project_id": project_id,
                "contractor_name": extraction.contractor_name,
                "question_summary": extraction.question[:200],
                "status": status,
                "date_staged": datetime.now(timezone.utc).isoformat(),
                "date_responded": None,
                "task_id": task_id,
            })
        except Exception as e:
            logger.warning(f"[{task_id}] RFI log update failed: {e}")

    def _save_thought_chain(self, db, task_id: str, step_key: str, data: dict) -> None:
        try:
            db.collection("thought_chains").document(task_id).set(
                {step_key: data, "updated_at": datetime.now(timezone.utc).isoformat()},
                merge=True,
            )
        except Exception as e:
            logger.debug(f"[{task_id}] Thought chain save ({step_key}) failed: {e}")

    def _transition(
        self, db, task_id: str, from_status: str, to_status: str, notes: str, ts: datetime
    ) -> None:
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
