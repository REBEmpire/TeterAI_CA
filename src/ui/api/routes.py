"""
TeterAI web API routes — all endpoints under /api/v1.

Mounts on the FastAPI app in server.py.
"""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ai_engine.gcp import GCPIntegration
from audit.logger import AuditLogger
from audit.models import HumanReviewAction, HumanReviewLog

from .auth import create_jwt, get_or_create_user, verify_google_id_token
from .middleware import UserInfo, require_auth, require_role
from .models import (
    ApproveRequest,
    AuditEntrySummary,
    CreateProjectRequest,
    EscalateRequest,
    ModelRegistryEntry,
    ProjectSummary,
    RejectRequest,
    TaskDetail,
    TaskSummary,
    TokenResponse,
    UpdateModelRequest,
    UpdateRoleRequest,
    UserSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Shared GCP dependency
# ---------------------------------------------------------------------------

_gcp = GCPIntegration()
_audit = AuditLogger(_gcp)


def _db():
    return _gcp.firestore_client


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class GoogleCallbackRequest(BaseModel):
    id_token: str


@router.post("/auth/google/callback", response_model=TokenResponse, tags=["auth"])
def google_callback(body: GoogleCallbackRequest):
    """
    Exchange a Google ID token (from the frontend sign-in flow) for a TeterAI JWT.
    """
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    claims = verify_google_id_token(body.id_token)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid Google token or domain not allowed.")

    user = get_or_create_user(db, claims)
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    token = create_jwt(
        uid=user["uid"],
        email=user["email"],
        display_name=user["display_name"],
        role=user["role"],
    )
    from .models import UserInfo as _UserInfo
    return TokenResponse(
        access_token=token,
        user=_UserInfo(**{k: user[k] for k in ("uid", "email", "display_name", "role")}),
    )


@router.get("/me", response_model=UserInfo, tags=["auth"])
def get_me(current_user: Annotated[UserInfo, Depends(require_auth)]):
    """Return the currently authenticated user's info and role."""
    return current_user


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

REVIEWABLE_STATUSES = {"STAGED_FOR_REVIEW", "ESCALATED_TO_HUMAN"}


@router.get("/tasks", response_model=list[TaskSummary], tags=["tasks"])
def list_tasks(
    current_user: Annotated[UserInfo, Depends(require_auth)],
    project: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    urgency: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """
    Return tasks in STAGED_FOR_REVIEW or ESCALATED_TO_HUMAN, sorted by
    urgency DESC then created_at ASC. Optionally filtered by project/type/urgency.
    """
    db = _db()
    if db is None:
        return []

    try:
        query = db.collection("tasks").where("status", "in", list(REVIEWABLE_STATUSES))
        if project:
            query = query.where("project_number", "==", project)
        if doc_type:
            query = query.where("document_type", "==", doc_type)
        if urgency:
            query = query.where("urgency", "==", urgency)

        docs = query.limit(limit).stream()
        tasks = []
        for doc in docs:
            data = doc.to_dict()
            data.setdefault("task_id", doc.id)
            tasks.append(_to_task_summary(data))

        # Sort: HIGH > MEDIUM > LOW, then oldest first
        _urgency_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        tasks.sort(
            key=lambda t: (
                _urgency_order.get(t.urgency, 9),
                t.created_at or datetime.min.replace(tzinfo=timezone.utc),
            )
        )
        return tasks
    except Exception as exc:
        logger.error(f"list_tasks failed: {exc}")
        return []


@router.get("/tasks/{task_id}", response_model=TaskDetail, tags=["tasks"])
def get_task(
    task_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Return full task detail including agent draft and metadata."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    doc = db.collection("tasks").document(task_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    data = doc.to_dict()
    data["task_id"] = task_id
    return _to_task_detail(data)


@router.post("/tasks/{task_id}/approve", tags=["tasks"])
def approve_task(
    task_id: str,
    body: ApproveRequest,
    current_user: Annotated[UserInfo, Depends(require_role("CA_STAFF", "ADMIN"))],
):
    """Approve a draft (optionally with edits). Transitions task to APPROVED."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    task_ref = db.collection("tasks").document(task_id)
    task = task_ref.get()
    if not task.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    task_data = task.to_dict()
    original_draft = task_data.get("draft_content", "")
    edits_made = body.edited_draft is not None and body.edited_draft != original_draft

    action = HumanReviewAction.EDITED_AND_APPROVED if edits_made else HumanReviewAction.APPROVED

    update: dict[str, Any] = {
        "status": "APPROVED",
        "approved_by": current_user.uid,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    if edits_made:
        update["draft_content"] = body.edited_draft
        update["draft_edited"] = True

    _push_status_history(task_data, "APPROVED", f"Human review: {action.value}", current_user.uid)
    update["status_history"] = task_data.get("status_history", [])

    task_ref.update(update)

    _audit.log(HumanReviewLog(
        task_id=task_id,
        reviewer_uid=current_user.uid,
        reviewer_name=current_user.display_name,
        action=action,
        original_draft_version=task_data.get("draft_version", ""),
        edits_made=edits_made,
        edit_summary="Reviewer edited draft before approval." if edits_made else None,
        duration_seconds=0,
        delivery_triggered=False,
    ))

    return {"status": "APPROVED", "task_id": task_id}


@router.post("/tasks/{task_id}/reject", tags=["tasks"])
def reject_task(
    task_id: str,
    body: RejectRequest,
    current_user: Annotated[UserInfo, Depends(require_role("CA_STAFF", "ADMIN"))],
):
    """Reject a draft with a reason. Task re-queues to ASSIGNED_TO_AGENT."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    task_ref = db.collection("tasks").document(task_id)
    task = task_ref.get()
    if not task.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    task_data = task.to_dict()
    _push_status_history(task_data, "REJECTED", f"Rejection reason: {body.reason}", current_user.uid)

    task_ref.update({
        "status": "REJECTED",
        "rejection_reason": body.reason,
        "rejection_notes": body.notes or "",
        "rejected_by": current_user.uid,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "status_history": task_data.get("status_history", []),
    })

    _audit.log(HumanReviewLog(
        task_id=task_id,
        reviewer_uid=current_user.uid,
        reviewer_name=current_user.display_name,
        action=HumanReviewAction.REJECTED,
        original_draft_version=task_data.get("draft_version", ""),
        edits_made=False,
        correction_type=body.reason,
        duration_seconds=0,
        delivery_triggered=False,
    ))

    return {"status": "REJECTED", "task_id": task_id}


@router.post("/tasks/{task_id}/escalate", tags=["tasks"])
def escalate_task(
    task_id: str,
    body: EscalateRequest,
    current_user: Annotated[UserInfo, Depends(require_role("CA_STAFF", "ADMIN"))],
):
    """Escalate a task to senior review."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    task_ref = db.collection("tasks").document(task_id)
    task = task_ref.get()
    if not task.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    task_data = task.to_dict()
    _push_status_history(task_data, "ESCALATED_TO_HUMAN", "Escalated by reviewer.", current_user.uid)

    task_ref.update({
        "status": "ESCALATED_TO_HUMAN",
        "escalated_by": current_user.uid,
        "escalated_at": datetime.now(timezone.utc).isoformat(),
        "escalation_notes": body.notes or "",
        "status_history": task_data.get("status_history", []),
    })

    _audit.log(HumanReviewLog(
        task_id=task_id,
        reviewer_uid=current_user.uid,
        reviewer_name=current_user.display_name,
        action=HumanReviewAction.ESCALATED,
        original_draft_version=task_data.get("draft_version", ""),
        edits_made=False,
        duration_seconds=0,
        delivery_triggered=False,
    ))

    return {"status": "ESCALATED_TO_HUMAN", "task_id": task_id}


@router.get("/tasks/{task_id}/draft", tags=["tasks"])
def get_draft(
    task_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Return the agent's draft text for a task."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    doc = db.collection("tasks").document(task_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    data = doc.to_dict()
    return {
        "task_id": task_id,
        "draft_content": data.get("draft_content", ""),
        "draft_version": data.get("draft_version", ""),
        "confidence_score": data.get("confidence_score"),
        "citations": data.get("citations", []),
        "agent_id": data.get("agent_id", ""),
    }


@router.get("/tasks/{task_id}/source", tags=["tasks"])
def get_source(
    task_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Return source document metadata (email body, attachment list) for a task.
    Actual file bytes are served through the Drive proxy (/tasks/{id}/source/{file_id}).
    """
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    doc = db.collection("tasks").document(task_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    data = doc.to_dict()
    return {
        "task_id": task_id,
        "source_email": data.get("source_email", {}),
        "attachments": data.get("attachments", []),
        "referenced_specs": data.get("referenced_specs", []),
        "referenced_drawings": data.get("referenced_drawings", []),
    }


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@router.get("/projects", response_model=list[ProjectSummary], tags=["projects"])
def list_projects(current_user: Annotated[UserInfo, Depends(require_auth)]):
    """List all active projects."""
    db = _db()
    if db is None:
        return []

    try:
        docs = db.collection("projects").stream()
        return [
            ProjectSummary(**{**doc.to_dict(), "project_id": doc.id})
            for doc in docs
            if doc.to_dict()
        ]
    except Exception as exc:
        logger.error(f"list_projects failed: {exc}")
        return []


@router.post(
    "/projects",
    response_model=ProjectSummary,
    status_code=status.HTTP_201_CREATED,
    tags=["projects"],
    dependencies=[Depends(require_role("ADMIN"))],
)
def create_project(
    body: CreateProjectRequest,
    current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))],
):
    """Create a new project (ADMIN only). Writes to Firestore projects collection."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    project_id = body.project_number.replace(" ", "-").lower()
    project_data = {
        "project_id": project_id,
        "project_number": body.project_number,
        "name": body.name,
        "phase": body.phase,
        "active": True,
        "known_senders": body.known_senders,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.uid,
    }

    db.collection("projects").document(project_id).set(project_data)
    logger.info(f"Project created: {project_id} by {current_user.uid}")
    return ProjectSummary(**project_data)


# ---------------------------------------------------------------------------
# Users (Admin)
# ---------------------------------------------------------------------------

@router.get(
    "/users",
    response_model=list[UserSummary],
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN"))],
)
def list_users(current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))]):
    """List all users (ADMIN only)."""
    db = _db()
    if db is None:
        return []

    try:
        docs = db.collection("users").stream()
        return [UserSummary(**doc.to_dict()) for doc in docs if doc.to_dict()]
    except Exception as exc:
        logger.error(f"list_users failed: {exc}")
        return []


@router.patch(
    "/users/{uid}/role",
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN"))],
)
def update_user_role(
    uid: str,
    body: UpdateRoleRequest,
    current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))],
):
    """Update a user's role (ADMIN only)."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    valid_roles = {"CA_STAFF", "ADMIN", "REVIEWER"}
    if body.role not in valid_roles:
        raise HTTPException(status_code=422, detail=f"Role must be one of {valid_roles}.")

    user_ref = db.collection("users").document(uid)
    if not user_ref.get().exists:
        raise HTTPException(status_code=404, detail=f"User {uid} not found.")

    user_ref.update({"role": body.role, "updated_by": current_user.uid})
    return {"uid": uid, "role": body.role}


# ---------------------------------------------------------------------------
# Model Registry (Admin)
# ---------------------------------------------------------------------------

@router.get(
    "/model-registry",
    response_model=list[ModelRegistryEntry],
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN"))],
)
def get_model_registry(current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))]):
    """Return current AI model assignments per capability class (ADMIN only)."""
    db = _db()
    if db is None:
        return []

    doc = db.collection("ai_engine").document("model_registry").get()
    if not doc.exists:
        return []

    data = doc.to_dict() or {}
    entries = []
    for cap_class, tiers in data.items():
        if isinstance(tiers, dict):
            entries.append(ModelRegistryEntry(
                capability_class=cap_class,
                tier_1=tiers.get("tier_1", ""),
                tier_2=tiers.get("tier_2"),
                tier_3=tiers.get("tier_3"),
            ))
    return entries


@router.patch(
    "/model-registry/{capability_class}",
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN"))],
)
def update_model(
    capability_class: str,
    body: UpdateModelRequest,
    current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))],
):
    """Update the model for a specific capability class + tier (ADMIN only)."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    if body.tier not in (1, 2, 3):
        raise HTTPException(status_code=422, detail="Tier must be 1, 2, or 3.")

    tier_key = f"tier_{body.tier}"
    db.collection("ai_engine").document("model_registry").update({
        f"{capability_class}.{tier_key}": body.model
    })
    return {"capability_class": capability_class, "tier": body.tier, "model": body.model}


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------

@router.get("/audit/{task_id}", response_model=list[AuditEntrySummary], tags=["audit"])
def get_task_audit(
    task_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Return audit trail for a task.
    ADMIN: full history. CA_STAFF/REVIEWER: own actions only.
    """
    db = _db()
    if db is None:
        return []

    try:
        query = db.collection("audit_logs").where("task_id", "==", task_id).order_by("timestamp")
        if current_user.role not in ("ADMIN",):
            query = query.where("reviewer_uid", "==", current_user.uid)

        docs = query.stream()
        results = []
        for doc in docs:
            data = doc.to_dict()
            results.append(AuditEntrySummary(
                log_id=data.get("log_id", doc.id),
                log_type=data.get("log_type", ""),
                timestamp=data.get("timestamp"),
                task_id=data.get("task_id"),
                agent_id=data.get("agent_id"),
                reviewer_uid=data.get("reviewer_uid"),
                action=data.get("action"),
                status=data.get("status"),
                details={k: v for k, v in data.items() if k not in {
                    "log_id", "log_type", "timestamp", "task_id",
                    "agent_id", "reviewer_uid", "action", "status",
                }},
            ))
        return results
    except Exception as exc:
        logger.error(f"get_task_audit failed: {exc}")
        return []


@router.get("/audit/{task_id}/export", tags=["audit"])
def export_task_audit_csv(
    task_id: str,
    current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))],
):
    """Export audit trail for a task as CSV (ADMIN only)."""
    entries = get_task_audit(task_id=task_id, current_user=current_user)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "log_id", "log_type", "timestamp", "task_id",
        "agent_id", "reviewer_uid", "action", "status",
    ])
    writer.writeheader()
    for e in entries:
        writer.writerow({
            "log_id": e.log_id,
            "log_type": e.log_type,
            "timestamp": e.timestamp,
            "task_id": e.task_id or "",
            "agent_id": e.agent_id or "",
            "reviewer_uid": e.reviewer_uid or "",
            "action": e.action or "",
            "status": e.status or "",
        })

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit_{task_id}.csv"'},
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_task_summary(data: dict) -> TaskSummary:
    return TaskSummary(
        task_id=data.get("task_id", ""),
        status=data.get("status", ""),
        urgency=data.get("urgency", "LOW"),
        document_type=data.get("document_type", "UNKNOWN"),
        document_number=data.get("document_number"),
        project_number=data.get("project_number"),
        sender_name=data.get("sender_name"),
        subject=data.get("subject"),
        created_at=_parse_dt(data.get("created_at")),
        response_due=_parse_dt(data.get("response_due")),
        classification_confidence=data.get("classification_confidence"),
        assigned_agent=data.get("assigned_agent"),
    )


def _to_task_detail(data: dict) -> TaskDetail:
    base = _to_task_summary(data)
    return TaskDetail(
        **base.model_dump(),
        draft_content=data.get("draft_content"),
        draft_version=data.get("draft_version"),
        agent_id=data.get("agent_id"),
        agent_version=data.get("agent_version"),
        confidence_score=data.get("confidence_score"),
        citations=data.get("citations", []),
        thought_chain_file_id=data.get("thought_chain_file_id"),
        source_email=data.get("source_email"),
        attachments=data.get("attachments", []),
        phase=data.get("phase"),
        rejection_reason=data.get("rejection_reason"),
        rejection_notes=data.get("rejection_notes"),
    )


def _push_status_history(task_data: dict, new_status: str, note: str, actor: str) -> None:
    history = task_data.get("status_history", [])
    history.append({
        "status": new_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "triggered_by": actor,
        "note": note,
    })
    task_data["status_history"] = history


def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None
