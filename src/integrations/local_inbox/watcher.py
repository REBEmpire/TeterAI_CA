"""
LocalInboxWatcher — polls ~/TeterAI/Inbox for new files and creates
email_ingests records in SQLite, triggering the agent pipeline.

Replaces the Gmail OAuth polling in GmailService.
Supports .eml (parsed as email), .pdf, .docx (treated as attachments).
"""
import email
import email.policy
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class LocalInboxWatcher:
    """Watches the local inbox folder for new files."""

    def __init__(self, config, db_client):
        from config.local_config import LocalConfig
        self._config: LocalConfig = config
        self._db = db_client
        self._inbox = Path(config.inbox_path).expanduser()
        self._inbox.mkdir(parents=True, exist_ok=True)
        self._processed_paths: set[str] = set()
        self._load_processed()

    def _load_processed(self) -> None:
        """Seed already-processed paths from SQLite processed_emails table."""
        try:
            docs = self._db.collection("processed_emails").stream()
            for doc in docs:
                data = doc.to_dict()
                path = data.get("local_path", "")
                if path:
                    self._processed_paths.add(path)
        except Exception:
            pass

    def poll(self) -> list[str]:
        """
        Scan the inbox folder for new files.
        Returns list of newly created ingest_ids.
        """
        ingest_ids = []
        supported = {".eml", ".pdf", ".docx", ".msg", ".txt"}

        for f in sorted(self._inbox.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() not in supported:
                continue
            if str(f) in self._processed_paths:
                continue

            try:
                ingest_id = self._process_file(f)
                if ingest_id:
                    ingest_ids.append(ingest_id)
                    self._processed_paths.add(str(f))
                    self._db.collection("processed_emails").document(ingest_id).set({
                        "message_id": ingest_id,
                        "local_path": str(f),
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "task_id": None,
                    })
            except Exception as e:
                logger.error(f"Failed to process inbox file {f}: {e}")

        return ingest_ids

    def _process_file(self, path: Path) -> Optional[str]:
        if path.suffix.lower() == ".eml":
            return self._ingest_eml(path)
        else:
            return self._ingest_attachment(path)

    def _ingest_eml(self, path: Path) -> str:
        """Parse a .eml file and create an email_ingest record."""
        raw = path.read_bytes()
        msg = email.message_from_bytes(raw, policy=email.policy.default)

        sender = str(msg.get("From", ""))
        subject = str(msg.get("Subject", path.name))
        date_str = str(msg.get("Date", ""))
        message_id = str(msg.get("Message-ID", str(uuid.uuid4())))

        # Extract body text
        body_text = ""
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                cd = str(part.get("Content-Disposition", ""))
                if ct == "text/plain" and "attachment" not in cd:
                    body_text = part.get_content() or ""
                elif "attachment" in cd or ct in ("application/pdf", "application/msword"):
                    fname = part.get_filename() or "attachment"
                    payload = part.get_payload(decode=True)
                    att_path = self._inbox / f"_att_{uuid.uuid4().hex}_{fname}"
                    if payload:
                        att_path.write_bytes(payload)
                    attachments.append({
                        "filename": fname,
                        "content_type": ct,
                        "local_path": str(att_path),
                    })
        else:
            body_text = msg.get_content() or ""

        truncated = len(body_text) > 8000
        hints = _get_subject_hints(subject)

        ingest_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        self._db.collection("email_ingests").document(ingest_id).set({
            "ingest_id": ingest_id,
            "message_id": message_id,
            "received_at": date_str or now,
            "sender_email": _parse_email_addr(sender),
            "sender_name": _parse_display_name(sender),
            "subject": subject,
            "body_text": body_text[:8000],
            "body_text_truncated": truncated,
            "attachment_metadata": attachments,
            "subject_hints": hints,
            "status": "PENDING_CLASSIFICATION",
            "task_id": None,
            "created_at": now,
            "source": "folder_watch",
        })

        logger.info(f"Ingested .eml from inbox: {path.name} → ingest_id={ingest_id}")
        return ingest_id

    def _ingest_attachment(self, path: Path) -> str:
        """Create a minimal ingest record for a PDF/DOCX dropped into the inbox."""
        ingest_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        self._db.collection("email_ingests").document(ingest_id).set({
            "ingest_id": ingest_id,
            "message_id": ingest_id,
            "received_at": now,
            "sender_email": "",
            "sender_name": "Local Upload",
            "subject": path.name,
            "body_text": "",
            "body_text_truncated": False,
            "attachment_metadata": [{
                "filename": path.name,
                "content_type": _guess_mime(path),
                "local_path": str(path),
            }],
            "subject_hints": _get_subject_hints(path.name),
            "status": "PENDING_CLASSIFICATION",
            "task_id": None,
            "created_at": now,
            "source": "folder_watch",
        })

        logger.info(f"Ingested {path.suffix} from inbox: {path.name} → ingest_id={ingest_id}")
        return ingest_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_email_addr(header: str) -> str:
    if "<" in header and ">" in header:
        return header.split("<")[1].rstrip(">").strip()
    return header.strip()


def _parse_display_name(header: str) -> str:
    if "<" in header:
        return header.split("<")[0].strip().strip('"')
    return ""


def _guess_mime(path: Path) -> str:
    import mimetypes
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"


def _get_subject_hints(subject: str) -> dict:
    """Infer document type hints from filename/subject line."""
    lower = subject.lower()
    hints = {}
    if "rfi" in lower:
        hints["document_type"] = "RFI"
    elif "submittal" in lower or "sub" in lower:
        hints["document_type"] = "SUBMITTAL"
    # Project number: look for NNN-NNN pattern
    import re
    m = re.search(r"\b(\d{4}-\d{3})\b", subject)
    if m:
        hints["project_number"] = m.group(1)
    return hints
