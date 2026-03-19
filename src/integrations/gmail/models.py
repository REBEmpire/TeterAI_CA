from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class EmailAttachment(BaseModel):
    filename: str
    mime_type: str
    size_bytes: int
    content: bytes

class ParsedEmail(BaseModel):
    message_id: str
    thread_id: str
    received_at: datetime
    sender_email: str
    sender_name: str
    subject: str
    body_text: str
    body_html: Optional[str] = None
    attachments: List[EmailAttachment] = []
    labels: List[str] = []
    in_reply_to: Optional[str] = None
    subject_hints: Dict[str, str] = {}
