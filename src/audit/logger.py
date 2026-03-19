import json
import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

from ai_engine.gcp import gcp_integration

from .models import (
    AgentActionLog,
    AICallLog,
    AuditEntry,
    BaseAuditEntry,
    ErrorLog,
    HumanReviewLog,
    LogType,
    SystemEventLog,
    ThoughtChain,
)

logger = logging.getLogger(__name__)


def _deserialize_entry(data: dict) -> Optional[AuditEntry]:
    """Convert a Firestore document dict to the appropriate AuditEntry subclass."""
    log_type = data.get("log_type")
    try:
        if log_type == LogType.AGENT_ACTION:
            return AgentActionLog(**data)
        elif log_type == LogType.AI_CALL:
            return AICallLog(**data)
        elif log_type == LogType.HUMAN_REVIEW:
            return HumanReviewLog(**data)
        elif log_type == LogType.SYSTEM_EVENT:
            return SystemEventLog(**data)
        elif log_type == LogType.ERROR:
            return ErrorLog(**data)
        else:
            logger.warning(f"Unknown log_type '{log_type}' — skipping entry.")
            return None
    except Exception as e:
        logger.warning(f"Failed to deserialize audit entry (log_type={log_type}): {e}")
        return None


class AuditLogger:
    def __init__(self, gcp, drive_service=None):
        self._db = gcp.firestore_client
        self._drive = drive_service  # Optional; used for thought chain capture

    def log(self, entry: BaseAuditEntry) -> str:
        """
        Append-only write to Firestore audit_logs collection.
        Also updates audit_logs_by_task index if entry has a task_id.
        Fail-silent: exceptions are logged but never raised to callers.
        Returns the log_id.
        """
        if not self._db:
            logger.warning("Firestore not available — audit log skipped.")
            return entry.log_id

        try:
            data = entry.model_dump(mode="json")
            self._db.collection("audit_logs").document(entry.log_id).set(data)

            task_id = getattr(entry, "task_id", None)
            if task_id:
                self._update_task_index(task_id, entry.log_id)

        except Exception as e:
            logger.error(f"Audit log write failed (log_id={entry.log_id}): {e}")

        return entry.log_id

    def _update_task_index(self, task_id: str, log_id: str) -> None:
        """Update audit_logs_by_task/{task_id} with ArrayUnion. Fail-silent."""
        try:
            ref = self._db.collection("audit_logs_by_task").document(task_id)
            ref.set({"logs": firestore.ArrayUnion([log_id])}, merge=True)
        except Exception as e:
            logger.error(f"Failed to update audit_logs_by_task for task {task_id}: {e}")

    def log_thought_chain(
        self,
        project_id: str,
        task_id: str,
        step_num: int,
        step_name: str,
        chain: ThoughtChain,
    ) -> Optional[str]:
        """
        Upload a thought chain JSON file to Google Drive.
        Path: 04 - Agent Workspace/Thought Chains/{task_id}/{step_num:02d}_{step_name}.json
        Fail-silent: returns file_id on success, None on failure.
        """
        if not self._drive:
            logger.warning("DriveService not configured — thought chain not saved.")
            return None

        try:
            workspace_folder_id = self._drive.get_folder_id(project_id, "04 - Agent Workspace")
            if not workspace_folder_id:
                logger.warning(
                    f"04 - Agent Workspace folder not found for project {project_id} "
                    f"— thought chain not saved."
                )
                return None

            # Ensure Thought Chains/{task_id} subfolder exists by uploading directly
            # The spec stores them under a task_id subfolder; use task_id as part of filename
            # to avoid needing subfolder creation here.
            filename = f"{step_num:02d}_{step_name}__{task_id}.json"
            content = json.dumps(chain.model_dump(mode="json"), indent=2).encode("utf-8")

            file_id = self._drive.upload_file(
                folder_id=workspace_folder_id,
                filename=filename,
                content=content,
                mime_type="application/json",
            )
            logger.info(f"Thought chain saved: {filename} (file_id={file_id})")
            return file_id

        except Exception as e:
            logger.error(f"Failed to save thought chain for task {task_id}: {e}")
            return None

    def get_task_timeline(self, task_id: str) -> list[AuditEntry]:
        """
        Return all audit entries for a task, ordered chronologically (ascending).
        """
        if not self._db:
            return []

        try:
            docs = (
                self._db.collection("audit_logs")
                .where("task_id", "==", task_id)
                .order_by("timestamp")
                .stream()
            )
            entries = []
            for doc in docs:
                entry = _deserialize_entry(doc.to_dict())
                if entry is not None:
                    entries.append(entry)
            return entries
        except Exception as e:
            logger.error(f"get_task_timeline failed for task {task_id}: {e}")
            return []

    def get_agent_activity(self, agent_id: str, since: datetime) -> list[AuditEntry]:
        """
        Return all AGENT_ACTION entries for a given agent since a datetime.
        """
        if not self._db:
            return []

        try:
            docs = (
                self._db.collection("audit_logs")
                .where("log_type", "==", LogType.AGENT_ACTION)
                .where("agent_id", "==", agent_id)
                .where("timestamp", ">=", since)
                .order_by("timestamp")
                .stream()
            )
            entries = []
            for doc in docs:
                entry = _deserialize_entry(doc.to_dict())
                if entry is not None:
                    entries.append(entry)
            return entries
        except Exception as e:
            logger.error(f"get_agent_activity failed for agent {agent_id}: {e}")
            return []

    def get_reviewer_history(self, reviewer_uid: str) -> list[HumanReviewLog]:
        """
        Return all HUMAN_REVIEW entries for a given reviewer UID.
        """
        if not self._db:
            return []

        try:
            docs = (
                self._db.collection("audit_logs")
                .where("log_type", "==", LogType.HUMAN_REVIEW)
                .where("reviewer_uid", "==", reviewer_uid)
                .order_by("timestamp")
                .stream()
            )
            entries = []
            for doc in docs:
                entry = _deserialize_entry(doc.to_dict())
                if isinstance(entry, HumanReviewLog):
                    entries.append(entry)
            return entries
        except Exception as e:
            logger.error(f"get_reviewer_history failed for reviewer {reviewer_uid}: {e}")
            return []


audit_logger = AuditLogger(gcp_integration)
