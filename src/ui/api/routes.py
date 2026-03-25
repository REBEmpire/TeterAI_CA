"""
TeterAI web API routes — all endpoints under /api/v1.

Mounts on the FastAPI app in server.py.
"""
import csv
import io
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from ai_engine.gcp import gcp_integration
from audit.logger import AuditLogger
from audit.models import HumanReviewAction, HumanReviewLog

from .auth import create_jwt, get_or_create_user, verify_google_id_token, verify_password_login
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

    # --- Delivery: file the approved draft to storage and transition to DELIVERED ---
    delivery_triggered = False
    final_file_path = None
    storage = _get_drive()
    if storage and final_draft:
        project_id = task_data.get("project_id") or task_data.get("project_number")
        doc_number = task_data.get("document_number", "RFI-???")
        doc_type = task_data.get("document_type", "RFI")
        dest_folder_key = "02 - Construction/RFIs" if doc_type == "RFI" else "04 - Agent Workspace/Thought Chains"
        try:
            folder_id = storage.get_folder_id(project_id, dest_folder_key) if project_id else None
            if folder_id:
                filename = f"{doc_number}_approved_response.md"
                file_ref = storage.upload_file(
                    folder_id=folder_id,
                    filename=filename,
                    content=final_draft.encode("utf-8"),
                    mime_type="text/markdown",
                )
                final_file_path = f"{dest_folder_key}/{filename}"
                delivery_triggered = True
                logger.info(f"[{task_id}] Approved draft filed: {file_ref}")
            else:
                logger.warning(f"[{task_id}] Folder '{dest_folder_key}' not found for project '{project_id}' — skipping file delivery.")
        except Exception as e:
            logger.error(f"[{task_id}] File delivery failed: {e}")

    # Transition to DELIVERED
    delivered_update: dict[str, Any] = {"status": "DELIVERED", "delivered_at": datetime.now(timezone.utc).isoformat()}
    if final_file_path:
        delivered_update["final_drive_path"] = final_file_path
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

    return {"status": "DELIVERED", "task_id": task_id, "delivery_triggered": delivery_triggered}


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
    Proxy Drive file bytes to the browser (used by SplitViewer iframes).
    The file_id is a Google Drive file ID stored in task.attachments[].drive_file_id.
    """
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
