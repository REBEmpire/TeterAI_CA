<<<<<<< SEARCH
@router.post("/tasks/{task_id}/escalate")
async def escalate_task(
    task_id: str,
    body: TaskActionRequest,
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("CA_STAFF")),
):
=======
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


@router.post("/tasks/{task_id}/escalate")
async def escalate_task(
    task_id: str,
    body: TaskActionRequest,
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("CA_STAFF")),
):
>>>>>>> REPLACE
