import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from google.cloud import firestore

from ai_engine.gcp import GCPIntegration
from knowledge_graph.client import KnowledgeGraphClient
from workflow.engine import WorkflowEngine
from workflow.models import TaskStatus, TriggerType, Urgency

logger = logging.getLogger(__name__)

router = APIRouter()

def get_workflow_engine() -> WorkflowEngine:
    # Factory for DI
    gcp = GCPIntegration()
    kg_client = KnowledgeGraphClient()
    return WorkflowEngine(gcp=gcp, kg_client=kg_client)

class QueueReviewResponse(BaseModel):
    stale_tasks_flagged: int
    rejected_tasks_requeued: int
    tasks_escalated: int
    unpicked_tasks_swept: int

@router.post("/queue-review", response_model=QueueReviewResponse, tags=["workflow"])
def queue_review(engine: WorkflowEngine = Depends(get_workflow_engine)):
    """
    Triggered by Cloud Scheduler every 20 minutes to maintain queue health:
    1. Sweep stale tasks (in CLASSIFYING/PROCESSING > timeout) to ERROR
    2. Re-queue REJECTED tasks to original agent
    3. Urgency escalation for STAGED_FOR_REVIEW > thresholds
    4. Pickup sweep for ASSIGNED_TO_AGENT > 5 mins
    """
    db = engine._db
    now = engine._now()

    response = QueueReviewResponse(
        stale_tasks_flagged=0,
        rejected_tasks_requeued=0,
        tasks_escalated=0,
        unpicked_tasks_swept=0
    )

    try:
        # 1. Sweep stale tasks
        stale_threshold = now - timedelta(minutes=engine.stale_processing_timeout_minutes)
        for state in [TaskStatus.CLASSIFYING.value, TaskStatus.PROCESSING.value]:
            stale_query = db.collection("tasks").where("status", "==", state).where("updated_at", "<", stale_threshold).stream()
            for doc in stale_query:
                try:
                    engine.transition(
                        task_id=doc.id,
                        new_status=TaskStatus.ERROR,
                        triggered_by="SCHEDULER",
                        trigger_type=TriggerType.SCHEDULER,
                        notes=f"Task stuck in {state} for more than {engine.stale_processing_timeout_minutes} minutes"
                    )
                    response.stale_tasks_flagged += 1
                except Exception as e:
                    logger.error(f"Failed to mark stale task {doc.id} as ERROR: {e}")

        # 2. Re-queue rejected tasks
        rejected_query = db.collection("tasks").where("status", "==", TaskStatus.REJECTED.value).stream()
        for doc in rejected_query:
            try:
                engine.transition(
                    task_id=doc.id,
                    new_status=TaskStatus.ASSIGNED_TO_AGENT,
                    triggered_by="SCHEDULER",
                    trigger_type=TriggerType.SCHEDULER,
                    notes="Re-queued rejected task to agent"
                )
                response.rejected_tasks_requeued += 1
            except Exception as e:
                logger.error(f"Failed to re-queue rejected task {doc.id}: {e}")

        # 3. Urgency escalation
        staged_query = db.collection("tasks").where("status", "==", TaskStatus.STAGED_FOR_REVIEW.value).stream()
        for doc in staged_query:
            task_data = doc.to_dict()
            urgency = task_data.get("urgency", Urgency.LOW.value)
            updated_at = task_data.get("updated_at")
            if not updated_at:
                continue

            # Handle if updated_at is still a string
            if isinstance(updated_at, str):
                try:
                    updated_at = datetime.fromisoformat(updated_at)
                except:
                    continue

            age_hours = (now - updated_at).total_seconds() / 3600

            should_escalate = False
            if urgency == Urgency.HIGH.value and age_hours > engine.high_urgency_review_hours:
                should_escalate = True
            elif urgency == Urgency.MEDIUM.value and age_hours > engine.medium_urgency_review_hours:
                should_escalate = True

            if should_escalate:
                try:
                    engine.transition(
                        task_id=doc.id,
                        new_status=TaskStatus.ESCALATED_TO_HUMAN,
                        triggered_by="SCHEDULER",
                        trigger_type=TriggerType.SCHEDULER,
                        notes=f"Escalated due to exceeding SLA for {urgency} urgency"
                    )
                    response.tasks_escalated += 1
                except Exception as e:
                    logger.error(f"Failed to escalate task {doc.id}: {e}")

        # 4. Pickup sweep
        pickup_threshold = now - timedelta(minutes=5)
        unpicked_query = db.collection("tasks").where("status", "==", TaskStatus.ASSIGNED_TO_AGENT.value).where("updated_at", "<", pickup_threshold).stream()
        for doc in unpicked_query:
            # Re-trigger assignment (e.g., alert or touch the document so it gets picked up again)
            try:
                doc_ref = db.collection("tasks").document(doc.id)
                doc_ref.update({"updated_at": now, "_pickup_retry": firestore.Increment(1)})
                response.unpicked_tasks_swept += 1
            except Exception as e:
                logger.error(f"Failed to sweep unpicked task {doc.id}: {e}")

    except Exception as e:
        logger.error(f"Queue review failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    return response
