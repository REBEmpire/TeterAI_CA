<<<<<<< SEARCH
@router.post("/settings")
async def update_settings(
    body: UpdateSettingsRequest,
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("ADMIN")),
):
    """Update active user settings (Desktop mode only)."""
    cfg = LocalConfig.ensure_exists()

    if body.neo4j_uri is not None:
        cfg.neo4j_uri = body.neo4j_uri
    if body.neo4j_username is not None:
        cfg.neo4j_username = body.neo4j_username
    if body.neo4j_password is not None:
        cfg.neo4j_password = body.neo4j_password

    if body.anthropic_api_key is not None:
        cfg.anthropic_api_key = body.anthropic_api_key
    if body.google_ai_api_key is not None:
        cfg.google_ai_api_key = body.google_ai_api_key
    if body.xai_api_key is not None:
        cfg.xai_api_key = body.xai_api_key

    if body.poll_interval_seconds is not None:
        cfg.poll_interval_seconds = body.poll_interval_seconds

    cfg.save()
    cfg.push_to_env()
    return {"status": "ok"}
=======
@router.post("/settings")
async def update_settings(
    body: UpdateSettingsRequest,
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("ADMIN")),
):
    """Update active user settings (Desktop mode only)."""
    cfg = LocalConfig.ensure_exists()

    if body.neo4j_uri is not None:
        cfg.neo4j_uri = body.neo4j_uri
    if body.neo4j_username is not None:
        cfg.neo4j_username = body.neo4j_username
    if body.neo4j_password is not None:
        cfg.neo4j_password = body.neo4j_password

    if body.anthropic_api_key is not None:
        cfg.anthropic_api_key = body.anthropic_api_key
    if body.google_ai_api_key is not None:
        cfg.google_ai_api_key = body.google_ai_api_key
    if body.xai_api_key is not None:
        cfg.xai_api_key = body.xai_api_key

    if body.poll_interval_seconds is not None:
        cfg.poll_interval_seconds = body.poll_interval_seconds
        # Dynamically update job triggers
        from .server import update_scheduler_interval
        update_scheduler_interval(cfg.poll_interval_seconds)

    cfg.save()
    cfg.push_to_env()
    return {"status": "ok"}

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
>>>>>>> REPLACE
