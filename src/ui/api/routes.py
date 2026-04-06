"""
TeterAI web API routes — all endpoints under /api/v1.

Mounts on the FastAPI app in server.py.
"""
import csv
import io
import logging
import mimetypes
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from ai_engine.gcp import gcp_integration
from audit.logger import AuditLogger
from audit.models import HumanReviewAction, HumanReviewLog

from .auth import create_jwt, get_or_create_user, verify_google_id_token, verify_password_login
from .middleware import UserInfo, require_auth, require_role
from .models import (
    AddChecklistItemRequest,
    AddDivergenceNotesRequest,
    ApproveRequest,
    AuditEntrySummary,
    CloseoutChecklistItem,
    CloseoutDeficiency,
    CloseoutScanResult,
    CloseoutSummary,
    ComparisonViewResponse,
    CreateDeficiencyRequest,
    CreateProjectRequest,
    DocumentAnalysisRequest,
    DocumentAnalysisResponse,
    EscalateRequest,
    GradeAnalysisRequest,
    GradingSessionResponse,
    GradingSessionSummary,
    HumanGradeRequest,
    ModelRegistryEntry,
    ModelResponseSummary,
    ProjectSummary,
    RejectRequest,
    ScanProjectsResponse,
    TaskDetail,
    TaskSummary,
    TokenResponse,
    UpdateChecklistItemRequest,
    UpdateModelRequest,
    UpdateProjectRequest,
    UpdateRoleRequest,
    UserSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_DESKTOP_MODE = os.environ.get("DESKTOP_MODE", "").lower() in ("true", "1")

# ---------------------------------------------------------------------------
# Shared storage/DB dependency (supports both cloud and desktop mode)
# ---------------------------------------------------------------------------

_gcp = gcp_integration
_audit = AuditLogger(_gcp)


def _db():
    return _gcp.firestore_client


def _get_drive():
    """Return storage service (LocalStorageService in desktop mode, DriveService in cloud)."""
    try:
        from storage import get_storage_service
        return get_storage_service(db_client=_db())
    except Exception as e:
        logger.warning(f"Storage service unavailable: {e}")
        return None


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


class PasswordLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/password", response_model=TokenResponse, tags=["auth"])
def password_login(body: PasswordLoginRequest):
    """
    Exchange a username + password for a TeterAI JWT (test users only).
    """
    user = verify_password_login(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
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
# Gmail OAuth setup — disabled in desktop mode; available in cloud mode only
# ---------------------------------------------------------------------------

_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]
_gmail_oauth_states: set[str] = set()


def _build_gmail_flow():
    if _DESKTOP_MODE:
        raise HTTPException(status_code=501, detail="Gmail OAuth is not available in desktop mode. Use the inbox folder or file upload instead.")
    client_id = _gcp.get_secret("integrations/gmail/oauth-client-id") or os.environ.get("GMAIL_OAUTH_CLIENT_ID")
    client_secret = _gcp.get_secret("integrations/gmail/oauth-client-secret") or os.environ.get("GMAIL_OAUTH_CLIENT_SECRET")
    redirect_uri = os.environ.get(
        "GMAIL_OAUTH_REDIRECT_URI",
        "https://teterai-ca.run.app/api/v1/auth/gmail/callback",
    )
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Gmail OAuth credentials not configured.")
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {"web": {"client_id": client_id, "client_secret": client_secret,
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                 "token_uri": "https://oauth2.googleapis.com/token",
                 "redirect_uris": [redirect_uri]}},
        scopes=_GMAIL_SCOPES,
    )
    flow.redirect_uri = redirect_uri
    return flow


@router.get("/auth/gmail/authorize", tags=["auth"], dependencies=[Depends(require_role("ADMIN"))])
def gmail_authorize():
    """Start the Gmail OAuth flow (cloud mode only)."""
    flow = _build_gmail_flow()
    state = secrets.token_urlsafe(32)
    _gmail_oauth_states.add(state)
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return RedirectResponse(url=auth_url)


@router.get("/auth/gmail/callback", tags=["auth"])
def gmail_callback(code: str = Query(...), state: str = Query(...)):
    """Handle the Gmail OAuth callback (cloud mode only)."""
    if _DESKTOP_MODE:
        raise HTTPException(status_code=501, detail="Gmail OAuth is not available in desktop mode.")
    if state not in _gmail_oauth_states:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
    _gmail_oauth_states.discard(state)
    flow = _build_gmail_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials
    if not credentials.refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token returned.")
    return {"message": "Gmail authorized.", "refresh_token": credentials.refresh_token}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

# All non-terminal task statuses shown in the dashboard.
# Terminal statuses (APPROVED, REJECTED, DELIVERED) are excluded by default.
ACTIVE_STATUSES = {
    "PENDING_CLASSIFICATION",
    "CLASSIFYING",
    "ASSIGNED_TO_AGENT",
    "PROCESSING",
    "STAGED_FOR_REVIEW",
    "ESCALATED_TO_HUMAN",
}
# Backwards-compat alias used in approval/rejection handlers
REVIEWABLE_STATUSES = {"STAGED_FOR_REVIEW", "ESCALATED_TO_HUMAN"}


@router.get("/tasks", response_model=list[TaskSummary], tags=["tasks"])
def list_tasks(
    current_user: Annotated[UserInfo, Depends(require_auth)],
    project: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    urgency: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Filter by exact status; omit for all active"),
    limit: int = Query(50, le=200),
):
    """
    Return all active tasks (PENDING_CLASSIFICATION → ESCALATED_TO_HUMAN), sorted by
    urgency DESC then created_at ASC. Optionally filtered by project/type/urgency/status.
    Terminal statuses (APPROVED, REJECTED, DELIVERED) are excluded unless ?status= is set.
    """
    db = _db()
    if db is None:
        return []

    try:
        if status:
            query = db.collection("tasks").where("status", "==", status)
        else:
            query = db.collection("tasks").where("status", "in", list(ACTIVE_STATUSES))
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

    # Merge thought_chains data (RFI Agent draft + confidence) into the task dict.
    # setdefault means the task doc fields take precedence if they already exist.
    tc = _load_thought_chain(db, task_id)
    if tc:
        data.setdefault("draft_content", tc.get("draft_rfi_response", ""))
        data.setdefault("confidence_score", tc.get("confidence_score"))
        data.setdefault("citations", tc.get("references", []))

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
    final_draft = body.edited_draft if edits_made else original_draft

    action = HumanReviewAction.EDITED_AND_APPROVED if edits_made else HumanReviewAction.APPROVED

    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {
        "status": "APPROVED",
        "approved_by": current_user.uid,
        "approved_at": now.isoformat(),
    }
    if edits_made:
        update["draft_content"] = final_draft
        update["draft_edited"] = True

    _push_status_history(task_data, "APPROVED", f"Human review: {action.value}", current_user.uid)
    update["status_history"] = task_data.get("status_history", [])
    task_ref.update(update)

    # --- Delivery: file the approved draft to the structured Delivered/ hierarchy ---
    delivery_triggered = False
    delivered_path: str | None = None
    storage = _get_drive()
    if storage and final_draft and hasattr(storage, "deliver_approved_document"):
        project_id = task_data.get("project_id") or task_data.get("project_number", "")
        project_name = task_data.get("project_name") or project_id or "UnknownProject"
        doc_type = task_data.get("document_type", "rfi").lower()
        doc_number = task_data.get("document_number") or task_id
        try:
            delivered_path = storage.deliver_approved_document(
                task_id=task_id,
                tool_type=doc_type,
                project_name=project_name,
                doc_title=doc_number,
                content=final_draft.encode("utf-8"),
                filename_suffix="Approved",
            )
            delivery_triggered = True
        except Exception as e:
            logger.error(f"[{task_id}] Delivery failed (non-fatal): {e}")

    # Transition to DELIVERED
    delivered_update: dict[str, Any] = {"status": "DELIVERED", "delivered_at": datetime.now(timezone.utc).isoformat()}
    if delivered_path:
        delivered_update["delivered_path"] = delivered_path
    _push_status_history(task_data, "DELIVERED", "Delivered after approval.", current_user.uid)
    delivered_update["status_history"] = task_data.get("status_history", [])
    task_ref.update(delivered_update)

    _audit.log(HumanReviewLog(
        task_id=task_id,
        reviewer_uid=current_user.uid,
        reviewer_name=current_user.display_name,
        action=action,
        original_draft_version=task_data.get("draft_version", ""),
        edits_made=edits_made,
        edit_summary="Reviewer edited draft before approval." if edits_made else None,
        duration_seconds=0,
        delivery_triggered=delivery_triggered,
    ))

    # Extract structured entities into Neo4j for ALL document types
    _doc_type = task_data.get("document_type", "").lower()
    _project_id = task_data.get("project_id", "")
    _ai_engine = None
    try:
        from ai_engine.engine import engine as _ae
        _ai_engine = _ae
    except Exception:
        pass

    try:
        from agents.kg.universal_entity_extractor import extract_and_store_entities
        _document_text = (
            (task_data.get("rfi_question", task_data.get("email_subject", "")) + "\n\n")
            + (final_draft or "")
        )
        _metadata = {
            "contractor_name": task_data.get("contractor_name", ""),
            "vendor_name":     task_data.get("vendor_name", ""),
            "doc_number":      task_data.get("document_number") or task_data.get("rfi_number", ""),
        }
        extract_and_store_entities(
            task_id=task_id,
            document_text=_document_text,
            document_type=_doc_type or "rfi",
            project_id=_project_id,
            metadata=_metadata,
            ai_engine=_ai_engine,
        )
    except Exception as e:
        logger.warning(f"[{task_id}] KG universal extraction failed (non-fatal): {e}")

    # Additionally, run design-flaw extraction for RFI tasks
    if _doc_type == "rfi":
        try:
            from agents.kg.flaw_extractor import extract_and_store_flaw
            extract_and_store_flaw(
                task_id=task_id,
                rfi_question=task_data.get("rfi_question", task_data.get("email_subject", "")),
                rfi_response=final_draft or "",
                spec_sections=task_data.get("citations", []),
                project_id=_project_id,
                ai_engine=_ai_engine,
            )
        except Exception as e:
            logger.warning(f"[{task_id}] KG flaw extraction failed (non-fatal): {e}")

    return {
        "status": "DELIVERED",
        "task_id": task_id,
        "delivery_triggered": delivery_triggered,
        "delivered_path": delivered_path,
    }


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
    """
    Return the agent's draft text for a task.

    Primary source: thought_chains/{task_id} (written by RFI Agent).
    Fallback: draft_content field on the task document (future agents).
    """
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    # Primary: thought_chains collection (RFI Agent writes here)
    tc = _load_thought_chain(db, task_id)
    if tc:
        return {
            "task_id": task_id,
            "draft_content": tc.get("draft_rfi_response", ""),
            "confidence_score": tc.get("confidence_score"),
            "citations": tc.get("references", []),
            "review_flag": tc.get("review_flag"),
            "agent_id": "",
        }

    # Fallback: task document (non-RFI agents or legacy)
    task_doc = db.collection("tasks").document(task_id).get()
    if not task_doc.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")
    data = task_doc.to_dict()
    return {
        "task_id": task_id,
        "draft_content": data.get("draft_content", ""),
        "confidence_score": data.get("confidence_score"),
        "citations": data.get("citations", []),
        "review_flag": None,
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


@router.get("/tasks/{task_id}/source/files/{file_id}", tags=["tasks"])
def get_source_file(
    task_id: str,
    file_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Serve source file bytes to the browser (used by SplitViewer iframes).
    For locally-uploaded files the file_id matches attachment[].file_id and the
    bytes are read from attachment[].local_path.  For Drive-backed tasks the
    file_id is a Google Drive file ID and bytes are fetched via the Drive proxy.
    """
    # Local-file path: look up the task's attachment by file_id and serve from disk.
    db = _db()
    if db is not None:
        try:
            task_doc = db.collection("tasks").document(task_id).get()
            if task_doc.exists:
                for att in (task_doc.to_dict() or {}).get("attachments", []):
                    if att.get("file_id") == file_id and att.get("local_path"):
                        local_path = Path(att["local_path"])
                        if local_path.exists():
                            mime_type = att.get("content_type", "application/octet-stream")
                            return Response(content=local_path.read_bytes(), media_type=mime_type)
        except Exception as e:
            logger.warning(f"[source/files] Local lookup failed for {file_id}: {e}")

    # Drive path: proxy the file through the storage service.
    drive = _get_drive()
    if drive is None:
        raise HTTPException(status_code=503, detail="Drive service unavailable.")
    try:
        content, mime_type = drive.download_file(file_id)
    except Exception as e:
        logger.error(f"Drive download failed for file {file_id}: {e}")
        raise HTTPException(status_code=404, detail="File not found in Drive.")
    return Response(content=content, media_type=mime_type)


# ---------------------------------------------------------------------------
# Submittal Review
# ---------------------------------------------------------------------------


class SubmittalSelectionsRequest(BaseModel):
    selected_items: dict[str, bool]


@router.get("/tasks/{task_id}/submittal-review", tags=["tasks"])
def get_submittal_review(
    task_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Return submittal review data for a task — all 3 model outputs and current item selections.
    Only valid for tasks with document_type == SUBMITTAL.
    """
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    doc = db.collection("submittal_reviews").document(task_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Submittal review for task {task_id} not found.")

    data = doc.to_dict()
    return {
        "task_id": task_id,
        "model_results": data.get("model_results", {}),
        "selected_items": data.get("selected_items", {}),
    }


@router.get("/tasks/{task_id}/red-team-audit", tags=["tasks"])
def get_red_team_audit(
    task_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Return the Red Team audit trail for a task:
    initial_review, red_team_critique, and final_output.

    For RFI tasks the data lives in thought_chains/{task_id}.
    For SUBMITTAL tasks it lives in submittal_reviews/{task_id}.
    Returns 404 if the audit fields are not present.
    """
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    # Determine which collection to query based on document_type
    task_doc = db.collection("tasks").document(task_id).get()
    if not task_doc.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")
    task_data = task_doc.to_dict()
    doc_type = (task_data.get("document_type") or "").upper()

    if doc_type == "SUBMITTAL":
        source_doc = db.collection("submittal_reviews").document(task_id).get()
    else:
        # Default: thought_chains (covers RFI and any other type)
        source_doc = db.collection("thought_chains").document(task_id).get()

    if not source_doc.exists:
        raise HTTPException(
            status_code=404,
            detail=f"No Red Team audit data found for task {task_id}.",
        )

    data = source_doc.to_dict()
    initial_review = data.get("initial_review")
    red_team_critique = data.get("red_team_critique")
    final_output = data.get("final_output")

    if not initial_review or not red_team_critique or not final_output:
        raise HTTPException(
            status_code=404,
            detail=f"Red Team audit fields not present for task {task_id}.",
        )

    return {
        "initial_review": initial_review,
        "red_team_critique": red_team_critique,
        "final_output": final_output,
    }


@router.post("/tasks/{task_id}/submittal-review/approve", tags=["tasks"])
def approve_submittal_review(
    task_id: str,
    body: SubmittalSelectionsRequest,
    current_user: Annotated[UserInfo, Depends(require_role("CA_STAFF", "ADMIN"))],
):
    """
    Approve a submittal review with the selected items. Generates a formatted report,
    files it to Drive, and transitions the task to DELIVERED.
    """
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    task_ref = db.collection("tasks").document(task_id)
    task = task_ref.get()
    if not task.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")
    task_data = task.to_dict()

    review_ref = db.collection("submittal_reviews").document(task_id)
    review_doc = review_ref.get()
    if not review_doc.exists:
        raise HTTPException(status_code=404, detail=f"Submittal review for task {task_id} not found.")

    review_data = review_doc.to_dict()
    model_results = review_data.get("model_results", {})

    # Persist the reviewer's selections
    now = datetime.now(timezone.utc)
    review_ref.update({
        "selected_items": body.selected_items,
        "approved_by": current_user.uid,
        "approved_at": now.isoformat(),
        "status": "APPROVED",
    })

    # Build the final report from selected items across all models
    report = _build_submittal_report(model_results, body.selected_items, task_data, task_id)

    # Transition task to APPROVED
    _push_status_history(task_data, "APPROVED", "Submittal review approved by human reviewer.", current_user.uid)
    task_ref.update({
        "status": "APPROVED",
        "approved_by": current_user.uid,
        "approved_at": now.isoformat(),
        "draft_content": report,
        "status_history": task_data.get("status_history", []),
    })

    # Deliver to storage (local folder or Drive depending on mode)
    delivery_triggered = False
    final_drive_path = None
    storage = _get_drive()
    if storage and report:
        project_id = task_data.get("project_id") or task_data.get("project_number")
        doc_number = task_data.get("document_number", "SUB-???")
        dest_folder_key = "02 - Construction/Submittals"
        try:
            folder_id = storage.get_folder_id(project_id, dest_folder_key) if project_id else None
            if folder_id:
                filename = f"{doc_number}_submittal_review.md"
                storage.upload_file(
                    folder_id=folder_id,
                    filename=filename,
                    content=report.encode("utf-8"),
                    mime_type="text/markdown",
                )
                final_drive_path = f"{dest_folder_key}/{filename}"
                delivery_triggered = True
                logger.info(f"[{task_id}] Submittal review report filed.")
        except Exception as e:
            logger.error(f"[{task_id}] File delivery failed: {e}")

    # Transition to DELIVERED
    delivered_update: dict[str, Any] = {
        "status": "DELIVERED",
        "delivered_at": datetime.now(timezone.utc).isoformat(),
    }
    if final_drive_path:
        delivered_update["final_drive_path"] = final_drive_path
    _push_status_history(task_data, "DELIVERED", "Submittal review report delivered.", current_user.uid)
    delivered_update["status_history"] = task_data.get("status_history", [])
    task_ref.update(delivered_update)

    # Extract submittal entities into Neo4j
    try:
        from agents.kg.universal_entity_extractor import extract_and_store_entities
        _sub_project_id = task_data.get("project_id", "")
        _sub_text = report or ""
        _sub_metadata = {
            "vendor_name": task_data.get("vendor_name", task_data.get("contractor_name", "")),
            "doc_number":  task_data.get("document_number", ""),
        }
        _sub_ai = None
        try:
            from ai_engine.engine import engine as _sae
            _sub_ai = _sae
        except Exception:
            pass
        extract_and_store_entities(
            task_id=task_id,
            document_text=_sub_text,
            document_type="submittal",
            project_id=_sub_project_id,
            metadata=_sub_metadata,
            ai_engine=_sub_ai,
        )
    except Exception as e:
        logger.warning(f"[{task_id}] KG submittal extraction failed (non-fatal): {e}")

    return {"status": "DELIVERED", "task_id": task_id, "delivery_triggered": delivery_triggered}


def _build_submittal_report(
    model_results: dict,
    selected_items: dict[str, bool],
    task_data: dict,
    task_id: str,
) -> str:
    """
    Generate a markdown report from the selected review items across all model outputs.
    Items are deduplicated by ID; if the same id appears in multiple model outputs and
    is selected, it is included once.
    """
    doc_number = task_data.get("document_number", "")
    project_number = task_data.get("project_number", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        f"# Submittal Review Report",
        f"**Document:** {doc_number}  ",
        f"**Project:** {project_number}  ",
        f"**Date:** {now}  ",
        f"**Task ID:** {task_id}  ",
        "",
    ]

    # Collect all selected items across tiers (deduplicate by id)
    seen_ids: set[str] = set()
    selected_table_items: list[dict] = []
    selected_warnings: list[dict] = []
    selected_missing: list[dict] = []
    summaries: list[str] = []

    for tier_key in ("tier_1", "tier_2", "tier_3"):
        tier_data = model_results.get(tier_key, {})
        provider = tier_data.get("provider", tier_key)
        model = tier_data.get("model", "")
        items = tier_data.get("items", {})

        for row in items.get("comparison_table", []):
            item_id = row.get("id", "")
            if selected_items.get(item_id, True) and item_id not in seen_ids:
                selected_table_items.append({**row, "_source": f"{provider}/{model}"})
                seen_ids.add(item_id)

        for warn in items.get("warnings", []):
            item_id = warn.get("id", "")
            if selected_items.get(item_id, True) and item_id not in seen_ids:
                selected_warnings.append({**warn, "_source": f"{provider}/{model}"})
                seen_ids.add(item_id)

        for miss in items.get("missing_info", []):
            item_id = miss.get("id", "")
            if selected_items.get(item_id, True) and item_id not in seen_ids:
                selected_missing.append({**miss, "_source": f"{provider}/{model}"})
                seen_ids.add(item_id)

        summary = items.get("summary", "")
        if summary:
            summaries.append(f"**{provider}/{model}:** {summary}")

    # Comparison table section
    if selected_table_items:
        lines += [
            "## Comparison Table",
            "",
            "| Category | Item | Specified | Submitted | Difference | Compliant | Severity | Comments |",
            "|----------|------|-----------|-----------|------------|-----------|----------|----------|",
        ]
        for row in selected_table_items:
            compliant_str = "Yes" if row.get("compliance") else "**No**"
            severity = row.get("severity", "OK")
            severity_str = f"⚠ {severity}" if severity == "MAJOR_WARNING" else severity
            lines.append(
                f"| {row.get('category','')} | {row.get('item','')} "
                f"| {row.get('specified_value','')} | {row.get('submitted_value','')} "
                f"| {row.get('difference','')} | {compliant_str} "
                f"| {severity_str} | {row.get('comments','')} |"
            )
        lines.append("")

    # Warnings section
    if selected_warnings:
        lines += ["## Major Warnings", ""]
        for i, warn in enumerate(selected_warnings, 1):
            lines += [
                f"### Warning {i} — {warn.get('type', 'MAJOR_WARNING')}",
                f"**{warn.get('description', '')}**",
                f"",
                f"*Recommendation:* {warn.get('recommendation', '')}",
                f"",
            ]

    # Missing info section
    if selected_missing:
        lines += ["## Missing Information", ""]
        for i, miss in enumerate(selected_missing, 1):
            lines += [
                f"### Missing Info {i}",
                f"**{miss.get('description', '')}**",
                f"",
                f"*Recommendation:* {miss.get('recommendation', '')}",
                f"",
            ]

    # Summaries
    if summaries:
        lines += ["## AI Model Summaries", ""]
        lines += summaries
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Knowledge Graph — new unified endpoints
# ---------------------------------------------------------------------------

@router.get("/knowledge-graph/full-graph", tags=["knowledge-graph"])
def kg_full_graph(
    project_id: str = Query(..., description="Project ID"),
    doc_type: Optional[str] = Query(None, description="Filter: rfi|submittal|schedule_review|pay_app|cost_analysis"),
    current_user: Annotated[UserInfo, Depends(require_auth)] = None,
):
    """Return nodes+edges for the full project graph across all document types."""
    from knowledge_graph.client import kg_client
    return kg_client.get_full_project_graph(
        project_id=project_id,
        doc_type_filter=doc_type,
    )


@router.get("/knowledge-graph/search", tags=["knowledge-graph"])
def kg_search(
    q: str = Query(..., description="Semantic search query"),
    project_id: Optional[str] = Query(None, description="Optional project filter"),
    top_k: int = Query(10, ge=1, le=50),
    current_user: Annotated[UserInfo, Depends(require_auth)] = None,
):
    """Semantic search across the knowledge graph using vector embeddings."""
    from knowledge_graph.client import kg_client
    return kg_client.semantic_search_graph(
        query=q,
        project_id=project_id,
        top_k=top_k,
    )


@router.get("/knowledge-graph/stats", tags=["knowledge-graph"])
def kg_stats(
    project_id: str = Query(..., description="Project ID"),
    current_user: Annotated[UserInfo, Depends(require_auth)] = None,
):
    """Return document counts and top patterns for a project's knowledge graph."""
    from knowledge_graph.client import kg_client
    return kg_client.get_project_graph_stats(project_id=project_id)


@router.post("/admin/setup-kg-schema", tags=["admin"])
def setup_kg_schema(
    current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))],
):
    """Create Neo4j constraints and indexes for all document-type nodes. Idempotent."""
    from knowledge_graph.client import kg_client
    kg_client.setup_universal_schema()
    return {"status": "ok", "message": "Knowledge graph schema setup complete."}


# ---------------------------------------------------------------------------
# Document Analysis — Multi-Model Analysis
# ---------------------------------------------------------------------------

@router.post("/document-analysis/analyze", tags=["document-analysis"])
def analyze_document_content(
    body: "DocumentAnalysisRequest",
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Analyze document content using all three AI models (Claude Opus 4.6, 
    Gemini 3.1 Pro, Grok 4.2) in parallel.
    
    Returns structured analysis with side-by-side comparison capability.
    """
    from .models import DocumentAnalysisRequest, DocumentAnalysisResponse, ModelResponseSummary
    from document_analysis import DocumentAnalysisService
    
    if not body.content:
        raise HTTPException(status_code=400, detail="Document content is required")
    
    service = DocumentAnalysisService()
    result = service.analyze_document(
        content=body.content,
        document_name=body.document_name,
        document_type=body.document_type,
        analysis_prompt=body.analysis_prompt,
        use_construction_prompt=body.use_construction_prompt,
        calling_agent=f"web_user:{current_user.uid}",
    )
    
    # Convert to response model
    models_dict = {}
    model_names = {1: "Claude Opus 4.6", 2: "Gemini 3.1 Pro", 3: "Grok 4.2"}
    
    for tier_key, response in [
        ("tier_1", result.tier_1_response),
        ("tier_2", result.tier_2_response),
        ("tier_3", result.tier_3_response),
    ]:
        tier_num = int(tier_key.split("_")[1])
        if response:
            models_dict[tier_key] = ModelResponseSummary(
                tier=tier_num,
                model_name=model_names[tier_num],
                provider=response.metadata.provider if response.metadata else "",
                status=response.status.value,
                latency_ms=response.metadata.latency_ms if response.metadata else 0,
                tokens_used=response.metadata.total_tokens if response.metadata else 0,
                summary=response.summary,
                key_findings=response.key_findings or [],
                recommendations=response.recommendations or [],
                confidence_score=response.confidence_score,
                error=response.error,
            )
    
    return DocumentAnalysisResponse(
        analysis_id=result.analysis_id,
        document_name=result.document_name,
        document_type=result.document_type,
        started_at=result.started_at,
        completed_at=result.completed_at,
        total_latency_ms=result.total_latency_ms,
        successful_models=result.successful_models,
        failed_models=result.failed_models,
        models=models_dict,
    )


@router.post("/document-analysis/analyze-file", tags=["document-analysis"])
async def analyze_document_file(
    file: UploadFile = File(..., description="Document file to analyze"),
    use_construction_prompt: bool = Form(default=False),
    analysis_prompt: Optional[str] = Form(default=None),
    current_user: Annotated[UserInfo, Depends(require_auth)] = None,
):
    """
    Upload and analyze a document file using all three AI models in parallel.
    
    Supports: PDF, Word (.docx), Excel (.xlsx), CSV, Text, Markdown, JSON files.
    """
    from .models import DocumentAnalysisResponse, ModelResponseSummary
    from document_analysis import DocumentAnalysisService
    import tempfile
    import shutil
    
    # Validate file type
    allowed_extensions = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt", ".md", ".json"}
    file_ext = Path(file.filename).suffix.lower() if file.filename else ""
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    
    try:
        service = DocumentAnalysisService()
        result = service.analyze_document(
            file_path=tmp_path,
            document_name=file.filename,
            analysis_prompt=analysis_prompt,
            use_construction_prompt=use_construction_prompt,
            calling_agent=f"web_user:{current_user.uid}" if current_user else "anonymous",
        )
        
        # Convert to response model
        models_dict = {}
        model_names = {1: "Claude Opus 4.6", 2: "Gemini 3.1 Pro", 3: "Grok 4.2"}
        
        for tier_key, response in [
            ("tier_1", result.tier_1_response),
            ("tier_2", result.tier_2_response),
            ("tier_3", result.tier_3_response),
        ]:
            tier_num = int(tier_key.split("_")[1])
            if response:
                models_dict[tier_key] = ModelResponseSummary(
                    tier=tier_num,
                    model_name=model_names[tier_num],
                    provider=response.metadata.provider if response.metadata else "",
                    status=response.status.value,
                    latency_ms=response.metadata.latency_ms if response.metadata else 0,
                    tokens_used=response.metadata.total_tokens if response.metadata else 0,
                    summary=response.summary,
                    key_findings=response.key_findings or [],
                    recommendations=response.recommendations or [],
                    confidence_score=response.confidence_score,
                    error=response.error,
                )
        
        return DocumentAnalysisResponse(
            analysis_id=result.analysis_id,
            document_name=result.document_name,
            document_type=result.document_type,
            started_at=result.started_at,
            completed_at=result.completed_at,
            total_latency_ms=result.total_latency_ms,
            successful_models=result.successful_models,
            failed_models=result.failed_models,
            models=models_dict,
        )
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("/document-analysis/comparison", tags=["document-analysis"])
def get_comparison_view(
    body: "DocumentAnalysisRequest",
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Analyze document and return a side-by-side comparison view of all model outputs.
    
    Returns formatted comparison data optimized for UI rendering.
    """
    from .models import DocumentAnalysisRequest, ComparisonViewResponse
    from document_analysis import DocumentAnalysisService
    
    if not body.content:
        raise HTTPException(status_code=400, detail="Document content is required")
    
    service = DocumentAnalysisService()
    result = service.analyze_document(
        content=body.content,
        document_name=body.document_name,
        document_type=body.document_type,
        analysis_prompt=body.analysis_prompt,
        use_construction_prompt=body.use_construction_prompt,
        calling_agent=f"web_user:{current_user.uid}",
    )
    
    comparison = service.get_comparison_view(result)
    comparison_json = comparison.to_json()
    
    return ComparisonViewResponse(
        analysis_id=comparison_json["analysis_id"],
        document=comparison_json["document"],
        timing=comparison_json["timing"],
        summary=comparison_json["summary"],
        columns=comparison_json["columns"],
    )


@router.post("/document-analysis/export-markdown", tags=["document-analysis"])
def export_analysis_markdown(
    body: "DocumentAnalysisRequest",
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Analyze document and return the comparison as a downloadable markdown report.
    """
    from .models import DocumentAnalysisRequest
    from document_analysis import DocumentAnalysisService
    
    if not body.content:
        raise HTTPException(status_code=400, detail="Document content is required")
    
    service = DocumentAnalysisService()
    result = service.analyze_document(
        content=body.content,
        document_name=body.document_name,
        document_type=body.document_type,
        analysis_prompt=body.analysis_prompt,
        use_construction_prompt=body.use_construction_prompt,
        calling_agent=f"web_user:{current_user.uid}",
    )
    
    comparison = service.get_comparison_view(result)
    markdown_content = comparison.to_markdown()
    
    filename = f"document_analysis_{result.analysis_id[:8]}.md"
    
    return Response(
        content=markdown_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ---------------------------------------------------------------------------
# Grading — Auto-grading and Human Comparison
# ---------------------------------------------------------------------------

@router.post("/grading/grade", tags=["grading"])
def grade_analysis_result(
    body: "GradeAnalysisRequest",
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Auto-grade a multi-model analysis result using Claude as the AI judge.
    
    Evaluates each model's response on:
    - Accuracy: Factual correctness against document content
    - Completeness: Coverage of key document elements  
    - Relevance: Alignment with analysis query/purpose
    - Citation Quality: Proper references to document sections
    
    Returns a grading session with AI grades for all successful models.
    """
    from .models import GradeAnalysisRequest, GradingSessionResponse
    from grading import get_auto_grader
    from document_analysis import DocumentAnalysisService
    
    # Get the analysis result
    service = DocumentAnalysisService()
    
    # For now, re-run analysis to get the result
    # In production, this would be cached/stored
    result = service.analyze_document(
        content=body.document_content,
        analysis_prompt=None,
        use_construction_prompt=False,
        calling_agent=f"grading:{current_user.uid}",
    )
    
    # Grade the analysis
    grader = get_auto_grader()
    session = grader.grade_analysis(
        analysis_result=result,
        document_content=body.document_content,
        analysis_purpose=body.analysis_purpose,
    )
    
    return {
        "session_id": session.session_id,
        "analysis_id": session.analysis_id,
        "document_name": session.document_name,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "ai_grades": {
            k: v.to_dict() for k, v in session.ai_grades.items()
        },
        "models_graded": len(session.ai_grades),
    }


@router.post("/grading/human-grade", tags=["grading"])
def submit_human_grade(
    body: "HumanGradeRequest",
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Submit human grades for a model in a grading session.
    
    Compares the human grade against the AI grade and computes divergence.
    Returns the human grade, divergence analysis, and AI grade summary.
    """
    from .models import HumanGradeRequest
    from grading import get_human_grading_interface
    
    interface = get_human_grading_interface()
    
    # Convert scores from Pydantic model to dict
    scores_dict = {
        k: {"score": v.score, "reasoning": v.reasoning, "evidence": v.evidence}
        for k, v in body.scores.items()
    }
    
    result = interface.submit_human_grade(
        session_id=body.session_id,
        model_id=body.model_id,
        grader_id=body.grader_id or current_user.uid,
        scores=scores_dict,
        notes=body.notes,
    )
    
    return result


@router.get("/grading/sessions/{session_id}", tags=["grading"])
def get_grading_session(
    session_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Retrieve a grading session with all grades and divergence analyses.
    """
    from grading import get_auto_grader
    
    grader = get_auto_grader()
    session = grader.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    return session.to_dict()


@router.get("/grading/sessions/{session_id}/for-grading", tags=["grading"])
def get_session_for_human_grading(
    session_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Get session details formatted for the human grading interface.
    
    Returns models with their AI grades that await human grading.
    """
    from grading import get_human_grading_interface
    
    interface = get_human_grading_interface()
    result = interface.get_session_for_grading(session_id)
    
    if not result:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    return result


@router.get("/grading/sessions/{session_id}/ai-grade/{model_id}", tags=["grading"])
def get_ai_grade_for_review(
    session_id: str,
    model_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Get detailed AI grade for a specific model to assist human grading.
    """
    from grading import get_human_grading_interface
    
    interface = get_human_grading_interface()
    result = interface.get_ai_grade_for_review(session_id, model_id)
    
    if not result:
        raise HTTPException(
            status_code=404, 
            detail=f"AI grade not found for model {model_id} in session {session_id}"
        )
    
    return result


@router.get("/grading/sessions", tags=["grading"])
def list_grading_sessions(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Annotated[UserInfo, Depends(require_auth)] = None,
):
    """
    List grading sessions with optional filtering.
    
    Status values: pending, ai_graded, human_graded, complete
    """
    from grading import get_auto_grader
    
    grader = get_auto_grader()
    sessions = grader.list_sessions(status=status, limit=limit, offset=offset)
    
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/grading/pending", tags=["grading"])
def get_pending_sessions(
    limit: int = Query(default=20, ge=1, le=50),
    current_user: Annotated[UserInfo, Depends(require_auth)] = None,
):
    """
    Get sessions awaiting human grading (status=ai_graded).
    """
    from grading import get_human_grading_interface
    
    interface = get_human_grading_interface()
    sessions = interface.get_pending_sessions(limit=limit)
    
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/grading/divergence-report", tags=["grading"])
def get_divergence_report(
    start_date: Optional[str] = Query(default=None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(default=None, description="End date (ISO format)"),
    model_filter: Optional[str] = Query(default=None, description="Filter by model ID"),
    current_user: Annotated[UserInfo, Depends(require_auth)] = None,
):
    """
    Generate a divergence analysis report.
    
    Returns aggregated statistics on AI vs human grading divergence,
    per-criterion analysis, and calibration recommendations.
    """
    from datetime import datetime
    from grading import get_human_grading_interface
    
    interface = get_human_grading_interface()
    
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    
    report = interface.get_divergence_report(
        start_date=start_dt,
        end_date=end_dt,
        model_filter=model_filter,
    )
    
    return report.to_dict()


@router.post("/grading/sessions/{session_id}/divergence/{model_id}/notes", tags=["grading"])
def add_divergence_notes(
    session_id: str,
    model_id: str,
    body: "AddDivergenceNotesRequest",
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Add calibration notes to a divergence analysis.
    
    Used to document why divergence occurred and suggest AI grading improvements.
    """
    from .models import AddDivergenceNotesRequest
    from grading import get_human_grading_interface
    
    interface = get_human_grading_interface()
    success = interface.add_divergence_notes(
        session_id=session_id,
        model_id=model_id,
        calibration_notes=body.calibration_notes,
        action_items=body.action_items,
    )
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Divergence analysis not found for model {model_id} in session {session_id}"
        )
    
    return {"success": True, "message": "Calibration notes added"}


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

    # In desktop mode, also create the canonical folder structure on disk
    if _DESKTOP_MODE:
        storage = _get_drive()
        if storage:
            try:
                storage.create_project_folders(project_id, body.name)
            except Exception as exc:
                logger.error(f"Failed to create local folders for {project_id}: {exc}")

    return ProjectSummary(**project_data)


@router.post(
    "/projects/scan",
    response_model=ScanProjectsResponse,
    tags=["projects"],
    dependencies=[Depends(require_role("ADMIN"))],
)
def scan_project_folders(
    current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))],
):
    """Scan local Projects directory for unregistered folders and import them."""
    if not _DESKTOP_MODE:
        raise HTTPException(status_code=400, detail="Only available in desktop mode.")

    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    storage = _get_drive()
    if storage is None:
        raise HTTPException(status_code=503, detail="Storage service unavailable.")

    projects_root = storage._root
    imported: list[ProjectSummary] = []
    skipped = 0
    errors: list[str] = []

    for entry in projects_root.iterdir():
        if not entry.is_dir():
            continue
        parts = entry.name.split(" - ", 1)
        if len(parts) != 2:
            continue
        project_id, project_name = parts[0].strip(), parts[1].strip()
        if not project_id or not project_name:
            continue

        doc_ref = db.collection("projects").document(project_id)
        if doc_ref.get().exists:
            skipped += 1
            continue

        try:
            storage.create_project_folders(project_id, project_name)
            project_data = {
                "project_number": project_id,
                "name": project_name,
                "phase": "Construction",
                "known_senders": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": current_user.uid,
                "drive_root_folder_id": "",
            }
            doc_ref.set(project_data)

            try:
                from knowledge_graph.client import kg_client
                kg_client.upsert_project({
                    "project_id": project_id,
                    "project_number": project_id,
                    "name": project_name,
                    "phase": "Construction",
                    "drive_root_folder_id": ""
                })
            except Exception as e:
                logger.warning(f"Failed to upsert scanned project {project_id} to KG: {e}")

            imported.append(ProjectSummary(**project_data))
        except Exception as e:
            errors.append(f"Failed importing '{entry.name}': {e}")

    return ScanProjectsResponse(imported=imported, skipped=skipped, errors=errors)


# ---------------------------------------------------------------------------
# Project phase transition
# ---------------------------------------------------------------------------

_VALID_PHASES = {"bid", "construction", "closeout"}


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectSummary,
    tags=["projects"],
    dependencies=[Depends(require_role("ADMIN"))],
)
def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))],
):
    """Update a project (phase transition, name, active status)."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    doc = db.collection("projects").document(project_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Project not found.")

    project_data = doc.to_dict()
    old_phase = project_data.get("phase", "")

    updates: dict = {}
    if body.phase is not None:
        phase = body.phase.lower()
        if phase not in _VALID_PHASES:
            raise HTTPException(status_code=400, detail=f"Invalid phase: {body.phase}. Must be one of: {', '.join(_VALID_PHASES)}")
        updates["phase"] = phase
    if body.active is not None:
        updates["active"] = body.active
    if body.name is not None:
        updates["name"] = body.name

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    db.collection("projects").document(project_id).set(updates, merge=True)

    # If transitioning TO closeout, seed the checklist
    new_phase = updates.get("phase", old_phase)
    if new_phase == "closeout" and old_phase != "closeout":
        _seed_closeout_checklist(db, project_id)
        logger.info(f"Closeout checklist seeded for project {project_id}")

    # Log phase transition in audit
    if "phase" in updates and updates["phase"] != old_phase:
        _audit.log(
            log_type="PROJECT_PHASE_TRANSITION",
            task_id=None,
            payload={
                "project_id": project_id,
                "from_phase": old_phase,
                "to_phase": updates["phase"],
                "triggered_by": current_user.uid,
            },
        )

    # Fetch updated record
    updated = db.collection("projects").document(project_id).get().to_dict()
    updated["project_id"] = project_id
    return ProjectSummary(**updated)


# ---------------------------------------------------------------------------
# Closeout checklist seed data & helpers
# ---------------------------------------------------------------------------

_DEFAULT_CLOSEOUT_SECTIONS = [
    ("01 31 00", "Project Management & Coordination", "PROJECT_DIRECTORY", "LOW"),
    ("01 33 00", "Submittal Procedures", "RFI_LOG", "LOW"),
    ("01 77 00", "Closeout Procedures — As-Builts", "AS_BUILT", "MEDIUM"),
    ("01 77 00", "Closeout Procedures — Testing", "TESTING_REPORT", "MEDIUM"),
    ("01 78 23", "Operation & Maintenance Data", "OM_MANUAL", "MEDIUM"),
    ("01 78 36", "Warranties & Bonds — Workmanship", "WARRANTY", "MEDIUM"),
    ("01 78 36", "Warranties & Bonds — Manufacturer", "WARRANTY", "MEDIUM"),
    ("01 78 39", "Project Record Documents", "AS_BUILT", "MEDIUM"),
    ("01 41 00", "Regulatory Requirements", "GOV_PAPERWORK", "HIGH"),
]


def _seed_closeout_checklist(db, project_id: str) -> None:
    """Generate default closeout checklist items for a project entering closeout phase."""
    now = datetime.now(timezone.utc).isoformat()
    for spec_section, spec_title, doc_type, urgency in _DEFAULT_CLOSEOUT_SECTIONS:
        item_id = str(uuid.uuid4())
        label = f"Section {spec_section} {spec_title} — {doc_type.replace('_', ' ').title()}"
        data = {
            "item_id": item_id,
            "project_id": project_id,
            "spec_section": spec_section,
            "spec_title": spec_title,
            "document_type": doc_type,
            "label": label,
            "urgency": urgency,
            "status": "NOT_RECEIVED",
            "created_at": now,
            "updated_at": now,
        }
        db.collection("closeout_checklist").document(item_id).set(data)


# ---------------------------------------------------------------------------
# Closeout CRUD endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/closeout",
    response_model=CloseoutSummary,
    tags=["closeout"],
)
def get_closeout_summary(
    project_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Get closeout checklist summary and all items for a project."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    # Verify project exists
    proj_doc = db.collection("projects").document(project_id).get()
    if not proj_doc.exists:
        raise HTTPException(status_code=404, detail="Project not found.")

    project_data = proj_doc.to_dict()

    # Fetch checklist items
    items_raw = list(
        db.collection("closeout_checklist")
        .where("project_id", "==", project_id)
        .stream()
    )
    items = []
    for doc in items_raw:
        d = doc.to_dict()
        d["item_id"] = doc.id
        items.append(CloseoutChecklistItem(**d))

    # Fetch deficiencies
    deficiencies_raw = list(
        db.collection("closeout_deficiencies")
        .where("project_id", "==", project_id)
        .stream()
    )
    deficiencies = []
    for doc in deficiencies_raw:
        d = doc.to_dict()
        d["deficiency_id"] = doc.id
        deficiencies.append(CloseoutDeficiency(**d))

    # Compute stats
    total = len(items)
    status_counts = {"NOT_RECEIVED": 0, "RECEIVED": 0, "UNDER_REVIEW": 0, "ACCEPTED": 0, "DEFICIENT": 0}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    completion_pct = (status_counts["ACCEPTED"] / total * 100) if total > 0 else 0.0

    return CloseoutSummary(
        project_id=project_id,
        project_name=project_data.get("name", ""),
        total_items=total,
        not_received=status_counts["NOT_RECEIVED"],
        received=status_counts["RECEIVED"],
        under_review=status_counts["UNDER_REVIEW"],
        accepted=status_counts["ACCEPTED"],
        deficient=status_counts["DEFICIENT"],
        completion_pct=round(completion_pct, 1),
        items=items,
        deficiencies=deficiencies,
    )


@router.patch(
    "/projects/{project_id}/closeout/{item_id}",
    response_model=CloseoutChecklistItem,
    tags=["closeout"],
)
def update_checklist_item(
    project_id: str,
    item_id: str,
    body: UpdateChecklistItemRequest,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Update a closeout checklist item's status, document path, or notes."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    doc = db.collection("closeout_checklist").document(item_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Checklist item not found.")

    existing = doc.to_dict()
    if existing.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="Item does not belong to this project.")

    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.status is not None:
        updates["status"] = body.status
        if body.status in ("ACCEPTED", "DEFICIENT"):
            updates["reviewed_by"] = current_user.uid
            updates["reviewed_at"] = updates["updated_at"]
    if body.document_path is not None:
        updates["document_path"] = body.document_path
    if body.responsible_party is not None:
        updates["responsible_party"] = body.responsible_party
    if body.notes is not None:
        updates["notes"] = body.notes

    db.collection("closeout_checklist").document(item_id).set(updates, merge=True)

    updated = db.collection("closeout_checklist").document(item_id).get().to_dict()
    updated["item_id"] = item_id
    return CloseoutChecklistItem(**updated)


@router.post(
    "/projects/{project_id}/closeout/{item_id}/deficiency",
    response_model=CloseoutDeficiency,
    status_code=status.HTTP_201_CREATED,
    tags=["closeout"],
)
def create_deficiency(
    project_id: str,
    item_id: str,
    body: CreateDeficiencyRequest,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Create a deficiency notice for a checklist item."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    # Verify item exists and belongs to project
    item_doc = db.collection("closeout_checklist").document(item_id).get()
    if not item_doc.exists:
        raise HTTPException(status_code=404, detail="Checklist item not found.")
    if item_doc.to_dict().get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="Item does not belong to this project.")

    now = datetime.now(timezone.utc).isoformat()
    deficiency_id = str(uuid.uuid4())
    data = {
        "deficiency_id": deficiency_id,
        "item_id": item_id,
        "project_id": project_id,
        "description": body.description,
        "severity": body.severity,
        "status": "OPEN",
        "created_by": current_user.uid,
        "created_at": now,
    }
    db.collection("closeout_deficiencies").document(deficiency_id).set(data)

    # Mark the checklist item as DEFICIENT
    db.collection("closeout_checklist").document(item_id).set(
        {"status": "DEFICIENT", "updated_at": now}, merge=True
    )

    return CloseoutDeficiency(**data)


@router.post(
    "/projects/{project_id}/closeout/scan",
    response_model=CloseoutScanResult,
    tags=["closeout"],
    dependencies=[Depends(require_role("ADMIN"))],
)
def scan_closeout_folder(
    project_id: str,
    current_user: Annotated[UserInfo, Depends(require_role("ADMIN"))],
):
    """Scan the project's 03 - Closeout/ folder and auto-match files to checklist items."""
    if not _DESKTOP_MODE:
        raise HTTPException(status_code=400, detail="Only available in desktop mode.")

    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    storage = _get_drive()
    if storage is None:
        raise HTTPException(status_code=503, detail="Storage service unavailable.")

    # Find the project's local root
    proj_doc = db.collection("projects").document(project_id).get()
    if not proj_doc.exists:
        raise HTTPException(status_code=404, detail="Project not found.")

    # Locate the 03 - Closeout folder
    project_root = None
    projects_root = storage._root
    for entry in projects_root.iterdir():
        if entry.is_dir() and entry.name.startswith(project_id):
            project_root = entry
            break

    if project_root is None:
        # Try local_root_path from project record
        local_root = proj_doc.to_dict().get("local_root_path")
        if local_root:
            project_root = Path(local_root)

    if project_root is None or not project_root.exists():
        raise HTTPException(status_code=404, detail="Project folder not found on disk.")

    closeout_dir = project_root / "03 - Closeout"
    if not closeout_dir.exists():
        raise HTTPException(status_code=404, detail="03 - Closeout folder not found.")

    # Keyword-to-document-type mapping for file matching
    _FILE_MATCHERS = [
        (["project index", "project directory", "directory"], "PROJECT_DIRECTORY"),
        (["rfi", "request for information"], "RFI_LOG"),
        (["as-built", "as built", "asbuilt", "testing report", "testing cert", "test report"], "AS_BUILT"),
        (["testing", "test cert", "certificate"], "TESTING_REPORT"),
        (["workmanship warrant", "workmanship"], "WARRANTY"),
        (["manufacturer warrant", "manufacturer"], "WARRANTY"),
        (["warranty", "warranties"], "WARRANTY"),
        (["o&m", "o & m", "operation", "maintenance", "om index", "om manual"], "OM_MANUAL"),
        (["gov", "government", "regulatory", "permit", "certificate of occupancy"], "GOV_PAPERWORK"),
    ]

    # Collect all files in closeout dir (recursively)
    all_files = []
    for f in closeout_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".jpg", ".png"):
            all_files.append(f)

    # Fetch existing checklist items
    items_raw = list(
        db.collection("closeout_checklist")
        .where("project_id", "==", project_id)
        .stream()
    )
    items_by_type: dict[str, list] = {}
    for doc in items_raw:
        d = doc.to_dict()
        d["item_id"] = doc.id
        doc_type = d.get("document_type", "")
        items_by_type.setdefault(doc_type, []).append(d)

    matched = []
    unmatched = []
    now = datetime.now(timezone.utc).isoformat()

    for f in all_files:
        fname_lower = f.name.lower()
        matched_type = None

        for keywords, doc_type in _FILE_MATCHERS:
            if any(kw in fname_lower for kw in keywords):
                matched_type = doc_type
                break

        # Also match by subdirectory name
        if matched_type is None:
            parent_lower = f.parent.name.lower()
            if "warrant" in parent_lower:
                matched_type = "WARRANTY"
            elif "o&m" in parent_lower or "o & m" in parent_lower or "maintenance" in parent_lower:
                matched_type = "OM_MANUAL"
            elif "gov" in parent_lower:
                matched_type = "GOV_PAPERWORK"

        if matched_type and matched_type in items_by_type:
            # Find the first NOT_RECEIVED item of this type
            target = None
            for item in items_by_type[matched_type]:
                if item.get("status") == "NOT_RECEIVED":
                    target = item
                    break

            if target:
                db.collection("closeout_checklist").document(target["item_id"]).set(
                    {"status": "RECEIVED", "document_path": str(f), "updated_at": now},
                    merge=True,
                )
                target["status"] = "RECEIVED"  # mark used
                matched.append({
                    "item_id": target["item_id"],
                    "file_path": str(f),
                    "spec_section": target.get("spec_section", ""),
                    "document_type": matched_type,
                })
            else:
                unmatched.append(str(f))
        else:
            unmatched.append(str(f))

    logger.info(f"Closeout scan for {project_id}: {len(matched)} matched, {len(unmatched)} unmatched")
    return CloseoutScanResult(matched=matched, unmatched=unmatched)


@router.post(
    "/projects/{project_id}/closeout/items",
    response_model=CloseoutChecklistItem,
    status_code=status.HTTP_201_CREATED,
    tags=["closeout"],
)
def add_checklist_item(
    project_id: str,
    body: AddChecklistItemRequest,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Add a custom spec section checklist item."""
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    proj_doc = db.collection("projects").document(project_id).get()
    if not proj_doc.exists:
        raise HTTPException(status_code=404, detail="Project not found.")

    now = datetime.now(timezone.utc).isoformat()
    item_id = str(uuid.uuid4())
    label = f"Section {body.spec_section} {body.spec_title} — {body.document_type.replace('_', ' ').title()}"
    data = {
        "item_id": item_id,
        "project_id": project_id,
        "spec_section": body.spec_section,
        "spec_title": body.spec_title,
        "document_type": body.document_type,
        "label": label,
        "urgency": body.urgency,
        "status": "NOT_RECEIVED",
        "responsible_party": body.responsible_party,
        "created_at": now,
        "updated_at": now,
    }
    db.collection("closeout_checklist").document(item_id).set(data)

    return CloseoutChecklistItem(**data)


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
# Knowledge Graph — RFI Pattern Visualization (Phase D)
# ---------------------------------------------------------------------------

_KG_MOCK_DATA = {
    "nodes": [
        {
            "id": "ss_08_41_13",
            "type": "SPEC_SECTION",
            "label": "08 41 13",
            "properties": {"section_number": "08 41 13", "title": "Aluminum-Framed Entrances and Storefronts"},
        },
        {
            "id": "ss_03_30_00",
            "type": "SPEC_SECTION",
            "label": "03 30 00",
            "properties": {"section_number": "03 30 00", "title": "Cast-in-Place Concrete"},
        },
        {
            "id": "rfi_demo_001",
            "type": "RFI",
            "label": "RFI-001",
            "properties": {"rfi_id": "demo_001", "question": "Storefront anchor detail conflicts with structural slab edge.", "status": "DELIVERED"},
        },
        {
            "id": "rfi_demo_002",
            "type": "RFI",
            "label": "RFI-002",
            "properties": {"rfi_id": "demo_002", "question": "Concrete mix design compressive strength not specified for elevated deck.", "status": "DELIVERED"},
        },
        {
            "id": "rfi_demo_003",
            "type": "RFI",
            "label": "RFI-003",
            "properties": {"rfi_id": "demo_003", "question": "Glazing bite dimension missing from curtain wall shop drawings.", "status": "DELIVERED"},
        },
        {
            "id": "df_coord_conflict",
            "type": "DESIGN_FLAW",
            "label": "Coordination Conflict",
            "properties": {
                "flaw_id": "demo_df_1",
                "category": "Coordination Conflict",
                "description": "Structural and architectural drawings conflict at storefront slab edge.",
            },
        },
        {
            "id": "df_spec_ambiguity",
            "type": "DESIGN_FLAW",
            "label": "Specification Ambiguity",
            "properties": {
                "flaw_id": "demo_df_2",
                "category": "Specification Ambiguity",
                "description": "Mix design strength requirements omitted for elevated concrete deck.",
            },
        },
        {
            "id": "ca_coord_review",
            "type": "CORRECTIVE_ACTION",
            "label": "Coordinate structural and architectural drawings at all curtain wall locations.",
            "properties": {
                "action_id": "demo_ca_1",
                "action": "Coordinate structural and architectural drawings at all curtain wall locations.",
            },
        },
        {
            "id": "ca_spec_review",
            "type": "CORRECTIVE_ACTION",
            "label": "Issue specification addendum clarifying concrete strength for each pour location.",
            "properties": {
                "action_id": "demo_ca_2",
                "action": "Issue specification addendum clarifying concrete strength for each pour location.",
            },
        },
    ],
    "edges": [
        {"source": "rfi_demo_001", "target": "ss_08_41_13", "type": "REFERENCES_SPEC"},
        {"source": "rfi_demo_002", "target": "ss_03_30_00", "type": "REFERENCES_SPEC"},
        {"source": "rfi_demo_003", "target": "ss_08_41_13", "type": "REFERENCES_SPEC"},
        {"source": "rfi_demo_001", "target": "df_coord_conflict", "type": "REVEALS"},
        {"source": "rfi_demo_003", "target": "df_coord_conflict", "type": "REVEALS"},
        {"source": "rfi_demo_002", "target": "df_spec_ambiguity", "type": "REVEALS"},
        {"source": "df_coord_conflict", "target": "ca_coord_review", "type": "SUGGESTS"},
        {"source": "df_spec_ambiguity", "target": "ca_spec_review", "type": "SUGGESTS"},
    ],
}


@router.get("/knowledge-graph/rfi-patterns", tags=["knowledge-graph"])
def get_rfi_pattern_graph(
    current_user: Annotated[UserInfo, Depends(require_auth)],
    project_id: str = Query(..., description="Firestore project ID"),
    spec_division: Optional[str] = Query(None, description='CSI division prefix, e.g. "08"'),
    date_from: Optional[str] = Query(None, description="ISO date, e.g. 2024-01-01"),
    date_to: Optional[str] = Query(None, description="ISO date, e.g. 2024-12-31"),
):
    """
    Return graph nodes and edges for the RFI pattern knowledge graph.

    Node types: SPEC_SECTION | RFI | DESIGN_FLAW | CORRECTIVE_ACTION
    Edge types: REFERENCES_SPEC | REVEALS | SUGGESTS

    Falls back to a built-in demo dataset when Neo4j is unavailable, so the
    frontend always has data to render for management demonstrations.
    """
    try:
        from knowledge_graph.client import kg_client
        result = kg_client.get_rfi_pattern_graph(
            project_id=project_id,
            spec_division=spec_division,
            date_from=date_from,
            date_to=date_to,
        )
        # If Neo4j returned nothing meaningful, serve the demo dataset
        if not result.get("nodes"):
            logger.info(f"get_rfi_pattern_graph: no nodes for project '{project_id}', serving mock data.")
            return _KG_MOCK_DATA
        return result
    except Exception as e:
        logger.warning(f"get_rfi_pattern_graph: KG unavailable ({e}), serving mock data.")
        return _KG_MOCK_DATA


# ---------------------------------------------------------------------------
# Project Intelligence Dashboard
# ---------------------------------------------------------------------------

@router.get("/projects/compare", tags=["knowledge-graph"])
def compare_projects(
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Cross-project KPI comparison for all ingested projects."""
    try:
        from knowledge_graph.client import kg_client
        return kg_client.get_cross_project_summary()
    except Exception as e:
        logger.error(f"compare_projects failed: {e}")
        return {"projects": []}


@router.get("/projects/{project_id}/intelligence", tags=["knowledge-graph"])
def get_project_intelligence(
    project_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Aggregate KPIs for a project: doc counts, response rate, party count, dates."""
    try:
        from knowledge_graph.client import kg_client
        result = kg_client.get_project_intelligence(project_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"No KG data for project '{project_id}'.")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_project_intelligence failed: {e}")
        raise HTTPException(status_code=500, detail="Knowledge graph unavailable.")


@router.get("/projects/{project_id}/party-network", tags=["knowledge-graph"])
def get_party_network(
    project_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Party nodes + submission counts by doc_type for project."""
    try:
        from knowledge_graph.client import kg_client
        return kg_client.get_party_network(project_id)
    except Exception as e:
        logger.error(f"get_party_network failed: {e}")
        return {"parties": []}


@router.get("/projects/{project_id}/timeline", tags=["knowledge-graph"])
def get_document_timeline(
    project_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Document submission counts grouped by month for timeline chart."""
    try:
        from knowledge_graph.client import kg_client
        return kg_client.get_document_timeline(project_id)
    except Exception as e:
        logger.error(f"get_document_timeline failed: {e}")
        return {"months": []}


@router.post("/projects/{project_id}/ai-summary", tags=["knowledge-graph"])
def generate_ai_summary(
    project_id: str,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Generate a Project Health Narrative using AI from KG data.
    Returns JSON with keys: overview, document_status, key_parties,
    risk_flags, recommendations.
    """
    import json as _json
    import uuid as _uuid
    from datetime import datetime, timezone

    # Pull KG data
    try:
        from knowledge_graph.client import kg_client
        intel = kg_client.get_project_intelligence(project_id)
        if not intel:
            raise HTTPException(status_code=404, detail=f"No KG data for project '{project_id}'.")
        parties = kg_client.get_party_network(project_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ai-summary KG fetch failed: {e}")
        raise HTTPException(status_code=500, detail="Knowledge graph unavailable.")

    # Build structured context for the AI
    top_parties = [p["name"] for p in parties.get("parties", [])[:5]]
    doc_breakdown = ", ".join(
        f"{k}: {v}" for k, v in (intel.get("doc_counts_by_type") or {}).items()
    )
    context_block = (
        f"Project ID: {project_id}\n"
        f"Total documents ingested: {intel.get('total_docs', 0)}\n"
        f"Documents by type: {doc_breakdown or 'none'}\n"
        f"Response rate: {round((intel.get('response_rate') or 0) * 100, 1)}%\n"
        f"Metadata-only ratio (docs without extractable text): "
        f"{round((intel.get('metadata_only_ratio') or 0) * 100, 1)}%\n"
        f"Distinct parties involved: {intel.get('party_count', 0)}\n"
        f"Top submitting parties: {', '.join(top_parties) if top_parties else 'none identified'}\n"
        f"Date range: {intel.get('earliest_date') or 'unknown'} to "
        f"{intel.get('latest_date') or 'unknown'}\n"
    )

    system_prompt = (
        "You are a senior construction administration specialist at Teter Architects. "
        "You analyze project documentation data and write concise, professional health narratives. "
        "Respond ONLY with a valid JSON object with exactly these five string keys: "
        "overview, document_status, key_parties, risk_flags, recommendations. "
        "Each value must be a single paragraph of 2-4 sentences. "
        "No markdown fences, no extra keys, no explanatory text outside the JSON object."
    )
    user_prompt = (
        "Generate a Project Health Narrative from this construction administration data:\n\n"
        f"{context_block}\n"
        "Risk flag guidance: metadata_only_ratio > 50% means many documents could not be "
        "text-extracted (likely scanned PDFs or drawings — flag for manual review). "
        "response_rate < 70% means many documents lack recorded responses — flag as a tracking gap."
    )

    from ai_engine.engine import engine
    from ai_engine.models import AIRequest, CapabilityClass

    ai_req = AIRequest(
        capability_class=CapabilityClass.ANALYZE,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        calling_agent="project_intelligence_dashboard",
        task_id=str(_uuid.uuid4()),
        temperature=0.3,
    )

    try:
        ai_resp = engine.generate_response(ai_req)
        raw = ai_resp.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        narrative = _json.loads(raw)
    except _json.JSONDecodeError:
        narrative = {
            "overview": ai_resp.content[:600],
            "document_status": "Structured response could not be parsed.",
            "key_parties": "",
            "risk_flags": "",
            "recommendations": "",
        }
    except Exception as e:
        logger.error(f"AI summary generation failed: {e}")
        raise HTTPException(status_code=500, detail="AI summary generation failed.")

    return {
        "project_id": project_id,
        "narrative": narrative,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_used": ai_resp.metadata.model,
        "tier_used": ai_resp.metadata.tier_used,
    }


# ---------------------------------------------------------------------------
# Pre-Bid Lessons Learned
# ---------------------------------------------------------------------------

class PreBidLessonsRequest(BaseModel):
    """
    Request body for POST /prebid-lessons.

    Attributes:
        query_text:          Plain-English description of a design concern or topic.
                             This text is embedded and compared against historical
                             RFI / Change Order summaries via cosine similarity.
        source_project_ids:  IDs of completed projects to mine for lessons.
                             Must match the project_id values stored in Neo4j
                             (e.g. "11900", "12556").
        doc_types:           Optional override of which document types to search.
                             Defaults to ['RFI', 'CO', 'CHANGE_ORDER', 'Change Order',
                             'COR', 'POTENTIAL_CO'] when omitted.
    """
    query_text: str
    source_project_ids: list[str]
    doc_types: list[str] | None = None   # defaults to RFI / CO types in KG method


@router.post("/prebid-lessons", tags=["knowledge-graph"])
def get_prebid_lessons(
    body: PreBidLessonsRequest,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """
    Pre-Bid Lessons Learned review.

    Mine historical completed-project RFIs and Change Orders for patterns
    that match a design concern described in *query_text*.  An AI model
    then synthesises the findings into an actionable pre-bid checklist so
    the design team can address known problem areas before going to bid.

    Request body:
      query_text          – free-text description of a design topic / concern
      source_project_ids  – list of completed-project IDs to mine
      doc_types           – optional override (default: RFI / CO variants)
    """
    import json as _json
    import uuid as _uuid
    from datetime import datetime, timezone

    if not body.query_text.strip():
        raise HTTPException(status_code=422, detail="query_text must not be empty.")
    if not body.source_project_ids:
        raise HTTPException(status_code=422, detail="At least one source_project_id is required.")

    try:
        from knowledge_graph.client import kg_client

        kwargs: dict = {"query_text": body.query_text, "source_project_ids": body.source_project_ids}
        if body.doc_types:
            kwargs["doc_types"] = body.doc_types

        similar_docs = kg_client.get_prebid_lessons(**kwargs)
        hotspots = kg_client.get_hotspot_topics(body.source_project_ids)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"prebid-lessons KG fetch failed: {e}")
        raise HTTPException(status_code=500, detail="Knowledge graph unavailable.")

    # -----------------------------------------------------------------------
    # Build AI prompt
    # -----------------------------------------------------------------------
    def _fmt_docs(docs, limit=8):
        lines = []
        for i, d in enumerate(docs[:limit], 1):
            proj = d.get("project_name") or d.get("project_id", "?")
            num = d.get("doc_number") or ""
            dt = d.get("doc_type", "")
            summary = (d.get("summary") or "").strip()[:300]
            score = d.get("score")
            score_str = f" [similarity {score:.2f}]" if score else ""
            lines.append(
                f"{i}. [{proj}] {dt} {num}{score_str}: {summary}"
            )
        return "\n".join(lines) if lines else "None found."

    doc_type_counts = hotspots.get("doc_type_counts", {})
    counts_str = ", ".join(f"{k}: {v}" for k, v in doc_type_counts.items()) or "none"
    similar_str = _fmt_docs(similar_docs)
    top_docs_str = _fmt_docs(hotspots.get("top_docs", []))

    system_prompt = (
        "You are a senior construction administration specialist and licensed architect at Teter. "
        "Your job is to review historical RFI and Change Order patterns from completed projects "
        "and help the design team eliminate known problem areas from new designs before bid. "
        "Be specific, practical, and reference the historical evidence. "
        "Respond ONLY with a valid JSON object with exactly these four string keys: "
        "summary, design_risks, spec_sections_to_clarify, bid_checklist. "
        "Each value is a paragraph or bulleted list (use \\n for newlines within values). "
        "No markdown fences, no extra keys, no text outside the JSON."
    )

    user_prompt = (
        f"Design concern: {body.query_text}\n\n"
        f"Historical RFI/CO volume from source projects: {counts_str}\n\n"
        f"Most similar historical RFIs / Change Orders (by semantic match):\n{similar_str}\n\n"
        f"Top historically responded RFIs/COs from source projects:\n{top_docs_str}\n\n"
        "Based on this evidence:\n"
        "1. Summarize the recurring design issues seen historically.\n"
        "2. Identify specific design risks the team should address before bid.\n"
        "3. List spec sections or drawing details that need clarification.\n"
        "4. Provide a concrete pre-bid checklist (5-10 action items) to eliminate these issues."
    )

    from ai_engine.engine import engine
    from ai_engine.models import AIRequest, CapabilityClass

    ai_req = AIRequest(
        capability_class=CapabilityClass.ANALYZE,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        calling_agent="prebid_lessons_learned",
        task_id=str(_uuid.uuid4()),
        temperature=0.25,
    )

    try:
        ai_resp = engine.generate_response(ai_req)
        raw = ai_resp.content.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        checklist = _json.loads(raw)
    except _json.JSONDecodeError:
        checklist = {
            "summary": ai_resp.content[:800],
            "design_risks": "",
            "spec_sections_to_clarify": "",
            "bid_checklist": "",
        }
    except Exception as e:
        logger.error(f"prebid-lessons AI generation failed: {e}")
        raise HTTPException(status_code=500, detail="AI checklist generation failed.")

    return {
        "query_text": body.query_text,
        "source_project_ids": body.source_project_ids,
        "similar_docs": similar_docs,
        "doc_type_counts": doc_type_counts,
        "checklist": checklist,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_used": ai_resp.metadata.model,
        "tier_used": ai_resp.metadata.tier_used,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _min_confidence(value) -> Optional[float]:
    """
    classification_confidence is stored by the Dispatcher Agent as a dict:
      { "project_id": 0.9, "phase": 0.85, "document_type": 0.91, "urgency": 0.88 }
    Return the minimum (worst-case) dimension as the overall confidence score.
    Falls back gracefully for legacy scalar values.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        values = [v for v in value.values() if isinstance(v, (int, float))]
        return min(values) if values else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_thought_chain(db, task_id: str) -> dict:
    """
    Read thought_chains/{task_id} written by the RFI Agent.
    Fields: draft_rfi_response, confidence_score, review_flag, references.
    Returns empty dict if the document does not exist.
    """
    try:
        doc = db.collection("thought_chains").document(task_id).get()
        return doc.to_dict() if doc.exists else {}
    except Exception as exc:
        logger.warning(f"Could not load thought_chains/{task_id}: {exc}")
        return {}


def _to_task_summary(data: dict) -> TaskSummary:
    # Use `or` fallbacks rather than dict.get() defaults because the key may
    # exist with a None value (e.g. freshly-uploaded tasks before classification).
    return TaskSummary(
        task_id=data.get("task_id") or "",
        status=data.get("status") or "PENDING_CLASSIFICATION",
        urgency=data.get("urgency") or "LOW",
        document_type=data.get("document_type") or "UNKNOWN",
        document_number=data.get("document_number"),
        project_number=data.get("project_number"),
        sender_name=data.get("sender_name"),
        subject=data.get("subject"),
        created_at=_parse_dt(data.get("created_at")),
        response_due=_parse_dt(data.get("response_due")),
        classification_confidence=_min_confidence(data.get("classification_confidence")),
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


# ---------------------------------------------------------------------------
# Desktop Settings (DESKTOP_MODE only)
# ---------------------------------------------------------------------------

class DesktopSettingsResponse(BaseModel):
    anthropic_api_key: str = ""
    google_api_key: str = ""
    xai_api_key: str = ""
    neo4j_uri: str = ""
    neo4j_username: str = ""
    projects_root: str = ""
    db_path: str = ""
    inbox_path: str = ""
    poll_interval_seconds: int = 30
    neo4j_connected: bool = False
    desktop_mode: bool = True


class DesktopSettingsUpdate(BaseModel):
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    xai_api_key: Optional[str] = None
    neo4j_uri: Optional[str] = None
    neo4j_username: Optional[str] = None
    neo4j_password: Optional[str] = None
    projects_root: Optional[str] = None
    inbox_path: Optional[str] = None
    poll_interval_seconds: Optional[int] = None


@router.get("/settings", response_model=DesktopSettingsResponse, tags=["desktop"])
def get_settings(current_user: Annotated[UserInfo, Depends(require_auth)]):
    """Return current desktop configuration (desktop mode only)."""
    if not _DESKTOP_MODE:
        raise HTTPException(status_code=404, detail="Settings endpoint is only available in desktop mode.")

    from config.local_config import LocalConfig
    cfg = LocalConfig.ensure_exists()

    neo4j_connected = False
    if cfg.neo4j_uri:
        try:
            from knowledge_graph.client import KnowledgeGraphClient
            kg = KnowledgeGraphClient()
            neo4j_connected = kg.is_connected()
        except Exception:
            pass

    return DesktopSettingsResponse(
        anthropic_api_key="***" if cfg.anthropic_api_key else "",
        google_api_key="***" if cfg.google_api_key else "",
        xai_api_key="***" if cfg.xai_api_key else "",
        neo4j_uri=cfg.neo4j_uri,
        neo4j_username=cfg.neo4j_username,
        projects_root=cfg.projects_root,
        db_path=cfg.db_path,
        inbox_path=cfg.inbox_path,
        poll_interval_seconds=cfg.poll_interval_seconds,
        neo4j_connected=neo4j_connected,
        desktop_mode=True,
    )


@router.post("/settings", tags=["desktop"])
def update_settings(
    body: DesktopSettingsUpdate,
    current_user: Annotated[UserInfo, Depends(require_auth)],
):
    """Update desktop configuration and persist to ~/.teterai/config.env."""
    if not _DESKTOP_MODE:
        raise HTTPException(status_code=404, detail="Settings endpoint is only available in desktop mode.")

    from config.local_config import LocalConfig
    cfg = LocalConfig.ensure_exists()

    if body.anthropic_api_key is not None:
        cfg.anthropic_api_key = body.anthropic_api_key
    if body.google_api_key is not None:
        cfg.google_api_key = body.google_api_key
    if body.xai_api_key is not None:
        cfg.xai_api_key = body.xai_api_key
    if body.neo4j_uri is not None:
        cfg.neo4j_uri = body.neo4j_uri
    if body.neo4j_username is not None:
        cfg.neo4j_username = body.neo4j_username
    if body.neo4j_password is not None:
        cfg.neo4j_password = body.neo4j_password
    if body.projects_root is not None:
        cfg.projects_root = body.projects_root
    if body.inbox_path is not None:
        cfg.inbox_path = body.inbox_path
    if body.poll_interval_seconds is not None:
        cfg.poll_interval_seconds = body.poll_interval_seconds

    cfg.save()
    cfg.push_to_env()

    # Reinitialize the Knowledge Graph client if Neo4j settings changed
    if body.neo4j_uri is not None or body.neo4j_username is not None or body.neo4j_password is not None:
        try:
            from knowledge_graph.client import kg_client
            kg_client._reconnect()
        except Exception as exc:
            logger.warning(f"Failed to reconnect kg_client after settings update: {exc}")

    return {"status": "saved"}


# ---------------------------------------------------------------------------
# File Upload / Manual Ingest (desktop mode)
# ---------------------------------------------------------------------------

@router.post("/ingest/upload", tags=["desktop"])
async def upload_ingest(
    current_user: Annotated[UserInfo, Depends(require_auth)],
    file: "UploadFile" = None,
):
    """
    Accept a file upload (PDF, DOCX, EML) and create an email_ingest record.
    Triggers the agent pipeline just like a folder-watch ingest.
    """
    from fastapi import UploadFile
    if file is None:
        raise HTTPException(status_code=422, detail="No file provided.")

    if not _DESKTOP_MODE:
        raise HTTPException(status_code=404, detail="Upload endpoint is only available in desktop mode.")

    from config.local_config import LocalConfig
    from integrations.local_inbox.watcher import LocalInboxWatcher
    import shutil

    cfg = LocalConfig.ensure_exists()
    inbox = __import__("pathlib").Path(cfg.inbox_path).expanduser()
    inbox.mkdir(parents=True, exist_ok=True)

    dest = inbox / file.filename
    content = await file.read()
    dest.write_bytes(content)

    watcher = LocalInboxWatcher(cfg, _db())
    ingest_id = watcher._process_file(dest)

    if ingest_id:
        watcher._processed_paths.add(str(dest))
        _db().collection("processed_emails").document(ingest_id).set({
            "message_id": ingest_id,
            "local_path": str(dest),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "task_id": None,
        })

    return {"ingest_id": ingest_id, "filename": file.filename, "status": "queued"}


# ---------------------------------------------------------------------------
# Document Upload — structured ingest with project/tool metadata (Phase C1)
# ---------------------------------------------------------------------------

_TOOL_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("rfi",      ["rfi"]),
    ("submittal", ["sub", "submittal"]),
    ("cost",     ["pco", "change"]),
    ("payapp",   ["pa", "pay", "application"]),
    ("schedule", ["sch", "schedule"]),
]


def _detect_tool_type(filename: str) -> str:
    """Auto-detect tool_type from filename keywords (case-insensitive)."""
    lower = filename.lower()
    for tool_type, keywords in _TOOL_TYPE_KEYWORDS:
        for kw in keywords:
            if kw in lower:
                return tool_type
    return "unknown"


def _guess_content_type(filename: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


def _extract_upload_text(content: bytes, filename: str, max_chars: int = 8000) -> str:
    """
    Extract plain text from an uploaded file's bytes.
    Runs pypdf / python-docx in a subprocess sandbox so a corrupt file can't
    crash the API process.  Returns text truncated to max_chars, or "" on failure.
    """
    import subprocess
    import sys
    import tempfile

    mime = _guess_content_type(filename)

    # ---------- plain text ----------
    if mime == "text/plain":
        try:
            return content.decode("utf-8", errors="replace")[:max_chars]
        except Exception:
            return ""

    # ---------- PDF ----------
    if mime == "application/pdf":
        if not content or len(content) < 4 or not content.startswith(b"%PDF"):
            logger.warning(f"[upload] {filename!r}: not a valid PDF")
            return ""
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(content)
                tmp = f.name
            script = (
                "import pypdf, io, sys\n"
                "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n"
                "try:\n"
                f"    r = pypdf.PdfReader(open({repr(tmp)}, 'rb'))\n"
                "    if r.is_encrypted:\n"
                "        try:\n"
                "            r.decrypt('')\n"
                "        except:\n"
                "            pass\n"
                "    text = []\n"
                "    for p in r.pages:\n"
                "        try:\n"
                "            t = p.extract_text()\n"
                "            if t: text.append(t)\n"
                "        except:\n"
                "            pass\n"
                "    print('\\n'.join(text))\n"
                "except Exception as e:\n"
                "    print(f'ERROR: {e}', file=sys.stderr)\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, encoding="utf-8", errors="replace", timeout=60,
            )
            if proc.returncode != 0:
                logger.warning(f"[upload] PDF extraction failed for {filename!r}: {proc.stderr[:200]}")
                return ""
            text = proc.stdout
            if len(text.strip()) < 20:
                logger.warning(f"[upload] PDF {filename!r} produced very little text — may be scanned/image-only")
            return text[:max_chars]
        except subprocess.TimeoutExpired:
            logger.warning(f"[upload] PDF extraction timed out for {filename!r}")
            return ""
        except Exception as e:
            logger.warning(f"[upload] PDF extraction error for {filename!r}: {e}")
            return ""
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # ---------- DOCX ----------
    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
                f.write(content)
                tmp = f.name
            script = (
                "import io, sys\n"
                "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n"
                "from docx import Document\n"
                f"doc = Document({repr(tmp)})\n"
                "print('\\n'.join(p.text for p in doc.paragraphs if p.text.strip()))\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            if proc.returncode != 0:
                logger.warning(f"[upload] DOCX extraction failed for {filename!r}: {proc.stderr[:200]}")
                return ""
            return proc.stdout[:max_chars]
        except subprocess.TimeoutExpired:
            logger.warning(f"[upload] DOCX extraction timed out for {filename!r}")
            return ""
        except Exception as e:
            logger.warning(f"[upload] DOCX extraction error for {filename!r}: {e}")
            return ""
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    logger.info(f"[upload] No text extractor for MIME type {mime!r} ({filename!r})")
    return ""


@router.post("/upload/document", tags=["upload"])
async def upload_document(
    current_user: Annotated[UserInfo, Depends(require_auth)],
    primary_file: UploadFile = File(...),
    supporting_files: list[UploadFile] = File(default=[]),
    project_id: str = Form(...),
    tool_type: Optional[str] = Form(default=None),
):
    """
    Accept a primary document (PDF/DOCX/XER/XML) plus optional supporting files,
    save them to ~/TeterAI/Inbox/uploads/{timestamp}_{filename},
    create an email_ingest record in Firestore with source='manual_upload',
    and return a task_id + resolved tool_type.

    Works in both desktop and cloud modes.
    tool_type values: rfi | submittal | cost | payapp | schedule | unknown | auto (auto-detect)
    """
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    # Resolve project — accept either Firestore doc ID or project_number string
    project_data: dict = {}
    resolved_project_id = project_id
    project_doc = db.collection("projects").document(project_id).get()
    if project_doc.exists:
        project_data = project_doc.to_dict() or {}
        resolved_project_id = project_doc.id
    else:
        proj_query = list(
            db.collection("projects").where("project_number", "==", project_id).limit(1).stream()
        )
        if proj_query:
            project_doc = proj_query[0]
            project_data = project_doc.to_dict() or {}
            resolved_project_id = project_doc.id
        else:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")

    project_number = project_data.get("project_number", resolved_project_id)

    # Resolve tool_type: explicit wins; "auto" or absent triggers filename detection
    resolved_tool_type = (
        tool_type
        if tool_type and tool_type not in ("auto", "")
        else _detect_tool_type(primary_file.filename or "")
    )

    # Determine upload directory (desktop uses configured inbox; cloud uses ~/TeterAI/Inbox)
    if _DESKTOP_MODE:
        try:
            from config.local_config import LocalConfig
            cfg = LocalConfig.ensure_exists()
            inbox_base = Path(cfg.inbox_path).expanduser()
        except Exception:
            inbox_base = Path("~/TeterAI/Inbox").expanduser()
    else:
        inbox_base = Path("~/TeterAI/Inbox").expanduser()

    upload_dir = inbox_base / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    primary_filename = primary_file.filename or f"upload_{timestamp}.bin"

    # Save primary file and extract its text so agents have content to work from.
    # (Agents read body_text from the ingest record; without extraction it would be empty.)
    primary_dest = upload_dir / f"{timestamp}_{primary_filename}"
    primary_content = await primary_file.read()
    primary_dest.write_bytes(primary_content)
    extracted_body_text = _extract_upload_text(primary_content, primary_filename)
    if extracted_body_text:
        logger.info(
            f"[upload/document] Extracted {len(extracted_body_text)} chars from {primary_filename!r}"
        )
    else:
        logger.warning(
            f"[upload/document] No text extracted from {primary_filename!r} — agents will classify from filename only"
        )

    # Save supporting files
    supporting_metadata: list[dict] = []
    for sf in supporting_files:
        sf_name = sf.filename or ""
        if sf_name:
            sf_dest = upload_dir / f"{timestamp}_supporting_{sf_name}"
            sf_content = await sf.read()
            sf_dest.write_bytes(sf_content)
            supporting_metadata.append({
                "filename": sf_name,
                "content_type": _guess_content_type(sf_name),
                "local_path": str(sf_dest),
                "file_id": sf_dest.name,
            })

    # Build ingest record (mirrors email_ingest schema from watcher._ingest_attachment)
    ingest_id = str(uuid.uuid4())
    task_id = f"TASK-{ingest_id[:8].upper()}-{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    attachment_metadata = [
        {
            "filename": primary_filename,
            "content_type": _guess_content_type(primary_filename),
            "local_path": str(primary_dest),
            "file_id": primary_dest.name,
        },
        *supporting_metadata,
    ]

    # Smart bypass: if user explicitly selected project AND tool type (not auto)
    # we jump straight to ASSIGNED_TO_AGENT status to bypass the AI classifier dispatcher.
    has_explicit_project = bool(project_id)
    has_explicit_tool = bool(tool_type and tool_type not in ("auto", ""))
    bypass_classification = has_explicit_project and has_explicit_tool

    initial_status = "ASSIGNED_TO_AGENT" if bypass_classification else "PENDING_CLASSIFICATION"


    ingest_record = {
        "ingest_id": ingest_id,
        "message_id": ingest_id,
        "received_at": now,
        "sender_email": current_user.email,
        "sender_name": current_user.display_name,
        "subject": primary_filename,
        "body_text": extracted_body_text,
        "body_text_truncated": len(extracted_body_text) >= 8000,
        "attachment_metadata": attachment_metadata,
        "subject_hints": {
            "doc_type_hint": resolved_tool_type.upper(),
            "project_number_hint": project_number,
        },
        "status": initial_status,
        "task_id": task_id,
        "created_at": now,
        # Distinguishes manual uploads from folder_watch and email ingests
        "source": "manual_upload",
        # Extra context fields for the dispatcher
        "project_id": resolved_project_id,
        "project_number": project_number,
        "tool_type_hint": resolved_tool_type,
        "uploaded_by": current_user.uid,
    }

    try:
        db.collection("email_ingests").document(ingest_id).set(ingest_record)
        logger.info(
            f"[upload/document] ingest_id={ingest_id} task_id={task_id} "
            f"file={primary_filename} tool_type={resolved_tool_type} "
            f"project={resolved_project_id} user={current_user.uid}"
        )
    except Exception as exc:
        logger.error(f"[upload/document] Failed to write ingest record: {exc}")
        raise HTTPException(status_code=500, detail="Failed to create ingest record.")

    # Create the task record immediately so the dashboard can find it
    task_doc = {
        "task_id": task_id,
        "ingest_id": ingest_id,
        "status": initial_status,
        "assigned_agent": None,
        "assigned_reviewer": None,
        "created_at": now,
        "updated_at": now,
        "status_history": [{
            "from_status": None,
            "to_status": initial_status,
            "triggered_by": current_user.uid,
            "trigger_type": "HUMAN",
            "timestamp": now,
            "notes": f"Manual upload{' (bypassed classification)' if bypass_classification else ''}",
        }],
        "project_id": resolved_project_id,
        "project_number": project_number,
        "document_type": resolved_tool_type.upper() if resolved_tool_type else None,
        "document_number": None,
        "phase": None,
        "urgency": None,
        "classification_confidence": None,
        "error_message": None,
        "correction_captured": False,
        "sender_name": current_user.display_name,
        "subject": primary_filename,
        "source_email": {
            "from": f"{current_user.display_name} <{current_user.email}>",
            "subject": primary_filename,
            "date": now,
            "body": "",
        },
        "attachments": attachment_metadata,
    }
    try:
        db.collection("tasks").document(task_id).set(task_doc)
    except Exception as exc:
        logger.error(f"[upload/document] Failed to create task record: {exc}")
        raise HTTPException(status_code=500, detail="Failed to create task record.")

    # Prevent the folder watcher from double-ingesting the same file
    try:
        db.collection("processed_emails").document(ingest_id).set({
            "message_id": ingest_id,
            "local_path": str(primary_dest),
            "processed_at": now,
            "task_id": task_id,
        })
    except Exception as exc:
        logger.warning(f"[upload/document] Could not write processed_emails guard record: {exc}")

    # Kick off an immediate dispatcher run so the task doesn't sit in
    # PENDING_CLASSIFICATION until the next background poll cycle.
    # Only do this if we actually need classification!
    def _dispatch_now() -> None:
        if bypass_classification:
            return
        try:
            from ai_engine.gcp import gcp_integration as _gcp
            from ai_engine.engine import engine as _ai_engine
            from agents.dispatcher.agent import DispatcherAgent
            result = DispatcherAgent(gcp=_gcp, ai_engine=_ai_engine).run()
            if result:
                logger.info(f"[upload/document] Immediate dispatch: classified {result}")
        except Exception as _e:
            logger.warning(f"[upload/document] Immediate dispatch failed (background poll will retry): {_e}")

    threading.Thread(target=_dispatch_now, daemon=True, name=f"dispatch-{task_id[:12]}").start()

    return {
        "task_id": task_id,
        "ingest_id": ingest_id,
        "tool_type": resolved_tool_type,
        "status": "queued",
    }

@router.get("/health")
async def get_health():
    """Return backend health and task stats."""
    from .server import system_health_state
    from ai_engine.gcp import gcp_integration
    from config.local_config import LocalConfig

    cfg = LocalConfig.ensure_exists()
    db = gcp_integration.firestore_client

    now = datetime.now(timezone.utc)
    last_poll = system_health_state["last_poll_at"]

    status_str = "ok"
    try:
        # Quick check if DB is reachable by just fetching tasks collection logic
        # Count PENDING and ERROR
        pending_count = 0
        error_count = 0
        tasks = list(db.collection("tasks").where("status", "in", ["PENDING_CLASSIFICATION", "CLASSIFYING", "ERROR"]).stream())
        for doc in tasks:
            t_status = doc.to_dict().get("status")
            if t_status == "ERROR":
                error_count += 1
            else:
                # Need to check stuck logic if necessary, but this provides count
                pending_count += 1

                # if stuck > 10 min
                updated_str = doc.to_dict().get("updated_at")
                if updated_str:
                    try:
                        updated_time = datetime.fromisoformat(updated_str)
                        if (now - updated_time).total_seconds() > 600:
                            status_str = "degraded"
                    except:
                        pass

        if error_count > 3:
            status_str = "error"

        # Check last poll time
        if last_poll and cfg.poll_interval_seconds:
            if (now - last_poll).total_seconds() > (cfg.poll_interval_seconds * 2):
                status_str = "degraded" if status_str != "error" else "error"

    except Exception as e:
        status_str = "error"
        pending_count = 0
        error_count = 0
        logging.getLogger(__name__).error(f"Health check failed: {e}")

    return {
        "status": status_str,
        "last_dispatch_at": last_poll.isoformat() if last_poll else None,
        "pending_count": pending_count,
        "error_count": error_count,
        "poll_interval_seconds": cfg.poll_interval_seconds
    }

@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: str,
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("CA_STAFF")),
):
    """Reset an ERROR task back to PENDING_CLASSIFICATION."""
    from ai_engine.gcp import gcp_integration
    db = gcp_integration.firestore_client

    doc_ref = db.collection("tasks").document(task_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Task not found")

    task_data = doc.to_dict()
    if task_data.get("status") != "ERROR":
        raise HTTPException(status_code=400, detail="Only tasks in ERROR status can be retried")

    now = datetime.now(timezone.utc)

    try:
        # Update task state
        history = task_data.get("status_history", [])
        history.append({
            "from_status": "ERROR",
            "to_status": "PENDING_CLASSIFICATION",
            "triggered_by": user.email,
            "trigger_type": "HUMAN",
            "timestamp": now.isoformat(),
            "notes": "Manually retried from UI"
        })

        doc_ref.update({
            "status": "PENDING_CLASSIFICATION",
            "error_message": None,
            "updated_at": now.isoformat(),
            "status_history": history
        })

        # Reset ingest
        ingest_id = task_data.get("ingest_id")
        if ingest_id:
            db.collection("email_ingests").document(ingest_id).update({
                "status": "PENDING_CLASSIFICATION"
            })

        return {"status": "ok", "task_id": task_id}
    except Exception as e:
        logger.error(f"Failed to retry task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retry task")


@router.post("/settings/embeddings")
async def get_embedding_settings(
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("ADMIN")),
):
    from config.local_config import LocalConfig
    from embeddings.service import get_embedding_service

    cfg = LocalConfig.ensure_exists()
    embed_svc = get_embedding_service()

    active_provider = "not configured"
    if embed_svc and embed_svc.provider:
        active_provider = embed_svc.provider.name if hasattr(embed_svc.provider, 'name') else str(embed_svc.provider.__class__.__name__)

    return {
        "active_provider": active_provider
    }

@router.post("/settings/test-key")
async def test_api_key(
    body: dict,
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("ADMIN")),
):
    provider = body.get("provider")
    key = body.get("key")

    if not provider or not key:
        return {"valid": False, "error": "Provider and key are required"}

    try:
        if provider == "google":
            from litellm import embedding
            import os
            os.environ["GEMINI_API_KEY"] = key
            res = embedding(model="gemini/text-embedding-004", input=["test"])
            return {"valid": True}
        elif provider == "anthropic":
            from litellm import completion
            import os
            os.environ["ANTHROPIC_API_KEY"] = key
            res = completion(model="anthropic/claude-3-haiku-20240307", messages=[{"role": "user", "content": "hi"}], max_tokens=5)
            return {"valid": True}
        else:
            return {"valid": False, "error": f"Testing not implemented for provider {provider}"}
    except Exception as e:
        return {"valid": False, "error": f"Key validation failed: {str(e)}"}

@router.get("/projects/{project_id}/search")
async def search_project_chunks(
    project_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    user: UserInfo = Depends(require_auth),
):
    try:
        from embeddings.service import get_embedding_service
        from document_intelligence.storage.chunk_store import ChunkStore
        from config.local_config import LocalConfig

        cfg = LocalConfig.ensure_exists()
        embed_svc = get_embedding_service()
        chunk_store = ChunkStore(db_path=cfg.db_path)

        if not embed_svc:
            return []

        # 1. Embed query
        query_embedding = embed_svc.embed(q)

        # 2. Get all chunks for project
        all_chunks = chunk_store.get_chunks_for_document(project_id) # Using this temporarily since there's no get_by_project implemented in the snippet
        # Actually ChunkStore probably has a method to get by project. Let's just load everything.
        # SQLite querying would be better, but we are doing in-memory cosine sim for desktop mode.
        import sqlite3
        conn = sqlite3.connect(cfg.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, document_id, chunk_index, text_content, chunk_type, embedding, metadata FROM chunks WHERE project_id = ?", (project_id,))
        rows = cursor.fetchall()

        if not rows:
            return []

        # 3. Compute cosine similarity
        import json
        import math

        def cosine_sim(vec1, vec2):
            dot = sum(a * b for a, b in zip(vec1, vec2))
            norm1 = math.sqrt(sum(a * a for a in vec1))
            norm2 = math.sqrt(sum(a * a for a in vec2))
            if norm1 == 0 or norm2 == 0:
                return 0
            return dot / (norm1 * norm2)

        results = []
        for row in rows:
            try:
                emb_bytes = row[5]
                chunk_emb = json.loads(emb_bytes.decode('utf-8'))

                sim = cosine_sim(query_embedding, chunk_emb)

                meta = json.loads(row[6]) if row[6] else {}

                results.append({
                    "id": row[0],
                    "document_id": row[1],
                    "text_content": row[3],
                    "chunk_type": row[4],
                    "similarity": sim,
                    "metadata": meta
                })
            except:
                pass

        # 4. Return top N
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Search failed: {e}")
        return []


@router.post("/admin/force-stuck-records")
async def force_stuck_records(current_user: Annotated[UserInfo, Depends(require_auth)]):
    """
    Diagnostic endpoint to find stuck PENDING_CLASSIFICATION or CLASSIFYING records
    and kick off the dispatcher again, or reset them.
    """
    if current_user.role not in ("ADMIN", "REVIEWER"):
        raise HTTPException(status_code=403, detail="Not authorized")

    db = _db()
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Reset CLASSIFYING -> PENDING_CLASSIFICATION
    ingests_ref = db.collection("email_ingests")
    stuck_ingests = ingests_ref.where("status", "in", ["CLASSIFYING", "PENDING_CLASSIFICATION", "ERROR"]).stream()

    count = 0
    for doc in stuck_ingests:
        try:
            doc.reference.update({"status": "PENDING_CLASSIFICATION"})
            count += 1
        except Exception as e:
            logger.warning(f"Failed to reset ingest {doc.id}: {e}")

    # Try to reset task status as well
    tasks_ref = db.collection("tasks")
    stuck_tasks = tasks_ref.where("status", "in", ["CLASSIFYING", "PENDING_CLASSIFICATION", "ERROR"]).stream()
    for doc in stuck_tasks:
        try:
            doc.reference.update({"status": "PENDING_CLASSIFICATION"})
        except Exception as e:
            logger.warning(f"Failed to reset task {doc.id}: {e}")

    # Kick off dispatcher
    def _run_dispatcher_bg():
        try:
            from agents.dispatcher.agent import DispatcherAgent
            from ai_engine.gcp import gcp_integration
            from ai_engine.engine import engine
            DispatcherAgent(gcp=gcp_integration, ai_engine=engine).run()
        except Exception as e:
            logger.error(f"Failed to run dispatcher from diagnostic endpoint: {e}")

    import threading
    threading.Thread(target=_run_dispatcher_bg, daemon=True).start()

    return {"status": "success", "reset_count": count, "message": "Dispatcher triggered for stuck records."}
