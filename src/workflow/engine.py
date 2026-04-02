import os
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

try:
    from google.cloud import firestore
except ImportError:
    firestore = None

from ai_engine.gcp import GCPIntegration
from audit.logger import AuditLogger
from knowledge_graph.client import KnowledgeGraphClient
from workflow.models import Task, TaskStatus, Urgency, TriggerType, StatusHistoryEntry, CorrectionCapture

logger = logging.getLogger(__name__)

class InvalidTransitionError(Exception):
    pass

class WorkflowEngine:
    # State machine allowed transitions
    ALLOWED_TRANSITIONS = {
        TaskStatus.PENDING_CLASSIFICATION: {TaskStatus.CLASSIFYING},
        TaskStatus.CLASSIFYING: {TaskStatus.ASSIGNED_TO_AGENT, TaskStatus.ESCALATED_TO_HUMAN},
        TaskStatus.ASSIGNED_TO_AGENT: {TaskStatus.PROCESSING},
        TaskStatus.PROCESSING: {TaskStatus.STAGED_FOR_REVIEW, TaskStatus.ERROR},
        TaskStatus.STAGED_FOR_REVIEW: {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.ESCALATED_TO_HUMAN},
        TaskStatus.APPROVED: {TaskStatus.DELIVERED},
        TaskStatus.REJECTED: {TaskStatus.ASSIGNED_TO_AGENT},
        TaskStatus.DELIVERED: set(),  # Terminal state
        TaskStatus.ESCALATED_TO_HUMAN: {TaskStatus.ASSIGNED_TO_AGENT, TaskStatus.DELIVERED, TaskStatus.REJECTED},
        TaskStatus.ERROR: {TaskStatus.ASSIGNED_TO_AGENT},
    }

    def __init__(self, gcp: GCPIntegration, kg_client: KnowledgeGraphClient):
        self._gcp = gcp
        self._db = self._gcp.firestore_client
        self._kg_client = kg_client
        self._audit = AuditLogger(gcp)

        self.stale_processing_timeout_minutes = int(os.environ.get("WF_STALE_PROCESSING_TIMEOUT_MINUTES", 10))
        self.high_urgency_review_hours = int(os.environ.get("WF_HIGH_URGENCY_REVIEW_HOURS", 24))
        self.medium_urgency_review_hours = int(os.environ.get("WF_MEDIUM_URGENCY_REVIEW_HOURS", 48))

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def create_task(self, ingest_id: str) -> Task:
        task_id = str(uuid.uuid4())
        now = self._now()

        task = Task(
            task_id=task_id,
            ingest_id=ingest_id,
            status=TaskStatus.PENDING_CLASSIFICATION,
            urgency=Urgency.LOW,
            created_at=now,
            updated_at=now,
            status_history=[],
            correction_captured=False
        )

        doc_ref = self._db.collection("tasks").document(task_id)
        doc_ref.set(task.model_dump(mode='json'))

        self._audit.log_event(
            task_id=task_id,
            event_type="TASK_CREATED",
            actor="SYSTEM",
            description=f"Task created for ingest {ingest_id}",
            metadata={"ingest_id": ingest_id}
        )

        return task

    def transition(self, task_id: str, new_status: TaskStatus, triggered_by: str, trigger_type: TriggerType, notes: Optional[str] = None) -> Task:
        transaction = self._db.transaction()
        doc_ref = self._db.collection("tasks").document(task_id)

        @firestore.transactional
        def _update_in_transaction(transaction, doc_ref):
            snapshot = doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                raise ValueError(f"Task {task_id} not found")

            task_data = snapshot.to_dict()
            current_status = TaskStatus(task_data["status"])

            # Allow transitions to ERROR from any non-terminal state
            allowed = self.ALLOWED_TRANSITIONS.get(current_status, set())
            if new_status != TaskStatus.ERROR and new_status not in allowed:
                raise InvalidTransitionError(f"Cannot transition from {current_status} to {new_status}")

            now = self._now()

            history_entry = StatusHistoryEntry(
                from_status=current_status,
                to_status=new_status,
                triggered_by=triggered_by,
                trigger_type=trigger_type,
                timestamp=now,
                notes=notes
            )

            history = task_data.get("status_history", [])
            history.append(history_entry.model_dump(mode='json'))

            update_data = {
                "status": new_status.value,
                "updated_at": now,
                "status_history": history
            }

            # Handle special state rules
            if new_status == TaskStatus.ASSIGNED_TO_AGENT and current_status == TaskStatus.REJECTED:
                # Keep assigned agent for re-process
                pass

            transaction.update(doc_ref, update_data)

            # Update the returned dict
            task_data.update(update_data)
            return Task(**task_data)

        updated_task = _update_in_transaction(transaction, doc_ref)

        self._audit.log_event(
            task_id=task_id,
            event_type="STATE_TRANSITION",
            actor=triggered_by,
            description=f"Transitioned from {updated_task.status_history[-1].from_status} to {new_status}",
            metadata={"from": updated_task.status_history[-1].from_status, "to": new_status, "trigger_type": trigger_type}
        )

        return updated_task

    def assign_to_agent(self, task_id: str, agent_id: str) -> Task:
        doc_ref = self._db.collection("tasks").document(task_id)
        now = self._now()
        doc_ref.update({"assigned_agent": agent_id, "updated_at": now})

        doc = doc_ref.get()
        task = Task(**doc.to_dict())

        self._audit.log_event(
            task_id=task_id,
            event_type="AGENT_ASSIGNED",
            actor="SYSTEM",
            description=f"Assigned to agent {agent_id}",
            metadata={"agent_id": agent_id}
        )
        return task

    def assign_to_reviewer(self, task_id: str, reviewer_uid: str) -> Task:
        doc_ref = self._db.collection("tasks").document(task_id)
        now = self._now()
        doc_ref.update({"assigned_reviewer": reviewer_uid, "updated_at": now})

        doc = doc_ref.get()
        task = Task(**doc.to_dict())

        self._audit.log_event(
            task_id=task_id,
            event_type="REVIEWER_ASSIGNED",
            actor="SYSTEM",
            description=f"Assigned to reviewer {reviewer_uid}",
            metadata={"reviewer_uid": reviewer_uid}
        )
        return task

    def get_agent_queue(self, agent_id: str) -> List[Task]:
        docs = self._db.collection("tasks").where("assigned_agent", "==", agent_id).where("status", "==", TaskStatus.ASSIGNED_TO_AGENT.value).stream()
        return [Task(**doc.to_dict()) for doc in docs]

    def get_review_queue(self, reviewer_uid: Optional[str] = None) -> List[Task]:
        query = self._db.collection("tasks").where("status", "==", TaskStatus.STAGED_FOR_REVIEW.value)
        if reviewer_uid:
            query = query.where("assigned_reviewer", "==", reviewer_uid)

        docs = query.stream()
        return [Task(**doc.to_dict()) for doc in docs]

    def capture_correction(self, task_id: str, original: str, edited: str, reviewer_uid: str) -> None:
        doc_ref = self._db.collection("tasks").document(task_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise ValueError(f"Task {task_id} not found")

        task_data = doc.to_dict()
        agent_id = task_data.get("assigned_agent", "UNKNOWN_AGENT")

        # Simple heuristic for correction type, can be expanded
        correction_type = "content"

        capture = CorrectionCapture(
            task_id=task_id,
            agent_id=agent_id,
            original_draft=original,
            edited_draft=edited,
            correction_type=correction_type,
            reviewer_uid=reviewer_uid,
            timestamp=self._now()
        )

        # Mark task as correction_captured
        doc_ref.update({"correction_captured": True, "updated_at": self._now()})

        # Send to KG
        self._kg_client.log_correction(
            task_id=task_id,
            agent_id=agent_id,
            correction_type=correction_type,
            original_text=original,
            edited_text=edited,
            reviewed_by=reviewer_uid,
        )

        self._audit.log_event(
            task_id=task_id,
            event_type="CORRECTION_CAPTURED",
            actor=reviewer_uid,
            description="Human reviewer provided corrections to agent draft",
            metadata={"correction_type": correction_type}
        )
