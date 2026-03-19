from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import logging

from ai_engine.gcp import GCPIntegration
from integrations.drive.service import DriveService
from .service import GmailService

logger = logging.getLogger(__name__)

app = FastAPI(title="TeterAI CA - Gmail Poller")

class PollResponse(BaseModel):
    status: str
    message: str
    processed_count: int

@app.post("/poll", response_model=PollResponse)
async def trigger_poll(background_tasks: BackgroundTasks):
    try:
        gcp = GCPIntegration()
        try:
            drive_service = DriveService()
        except Exception as e:
            logger.warning(f"DriveService unavailable — attachments will use stub paths: {e}")
            drive_service = None
        service = GmailService(gcp, drive_service=drive_service)

        # We process inline for simplicity and to return the count,
        # but in a real-world high-volume scenario, background_tasks could be used.
        processed_ids = service.poll()

        return PollResponse(
            status="success",
            message="Polling cycle complete.",
            processed_count=len(processed_ids)
        )
    except Exception as e:
        logger.error(f"Error in /poll endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during polling")

@app.get("/health")
async def health_check():
    return {"status": "ok"}
