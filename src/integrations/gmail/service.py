import os
import logging
import base64
import re
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.cloud import firestore
from email.utils import parsedate_to_datetime, parseaddr

from ai_engine.gcp import GCPIntegration
from .models import ParsedEmail, EmailAttachment

logger = logging.getLogger(__name__)

class GmailService:
    def __init__(self, gcp: GCPIntegration):
        self.gcp = gcp
        self.inbox_address = os.environ.get("GMAIL_INBOX_ADDRESS", "me")
        self.max_emails = int(os.environ.get("GMAIL_MAX_EMAILS_PER_POLL", 50))
        self.max_attachment_size = int(os.environ.get("GMAIL_ATTACHMENT_MAX_SIZE_MB", 25)) * 1024 * 1024

        self.service = self._init_gmail_client()

    def _init_gmail_client(self):
        try:
            client_id = self.gcp.get_secret("integrations/gmail/oauth-client-id") or os.environ.get("GMAIL_OAUTH_CLIENT_ID")
            client_secret = self.gcp.get_secret("integrations/gmail/oauth-client-secret") or os.environ.get("GMAIL_OAUTH_CLIENT_SECRET")
            refresh_token = self.gcp.get_secret("integrations/gmail/oauth-refresh-token") or os.environ.get("GMAIL_OAUTH_REFRESH_TOKEN")

            if not all([client_id, client_secret, refresh_token]):
                logger.warning("Missing Gmail OAuth credentials. Running without real API.")
                return None

            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.modify"]
            )
            return build("gmail", "v1", credentials=creds)
        except Exception as e:
            logger.error(f"Failed to initialize Gmail client: {e}")
            return None

    def _get_subject_hints(self, subject: str) -> Dict[str, str]:
        hints = {}
        subject_upper = subject.upper()

        # RFI hint
        rfi_match = re.search(r'RFI\s*[-#]?\s*(\d+)', subject_upper)
        if rfi_match:
            hints['doc_type_hint'] = 'RFI'
            hints['doc_number_hint'] = rfi_match.group(1)

        # Submittal hint
        if not rfi_match:
            submittal_match = re.search(r'SUBMITTAL\s*[-#]?\s*(\d+)', subject_upper)
            if submittal_match:
                hints['doc_type_hint'] = 'SUBMITTAL'
                hints['doc_number_hint'] = submittal_match.group(1)

        # Project hint
        project_match = re.search(r'\[(.*?)\]', subject)
        if project_match:
            hints['project_number_hint'] = project_match.group(1)

        # Reply hint
        if subject_upper.startswith('RE:'):
            hints['is_reply'] = 'true'

        return hints

    def _extract_body_and_attachments(self, payload: Dict[str, Any], message_id: str) -> Tuple[str, Optional[str], List[EmailAttachment]]:
        body_text = ""
        body_html = None
        attachments = []

        if 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType')
                filename = part.get('filename')
                body = part.get('body', {})
                data = body.get('data')
                attachment_id = body.get('attachmentId')

                if filename and attachment_id and self.service:
                    # Fetch attachment
                    try:
                        att = self.service.users().messages().attachments().get(
                            userId=self.inbox_address, messageId=message_id, id=attachment_id
                        ).execute()
                        file_data = base64.urlsafe_b64decode(att['data'])
                        if len(file_data) > self.max_attachment_size:
                            logger.warning(f"Skipping attachment {filename} in {message_id} (exceeds max size)")
                            continue

                        attachments.append(EmailAttachment(
                            filename=filename,
                            mime_type=mime_type,
                            size_bytes=len(file_data),
                            content=file_data
                        ))
                    except Exception as e:
                        logger.error(f"Error fetching attachment {filename}: {e}")
                elif mime_type == 'text/plain' and data:
                    body_text += base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                elif mime_type == 'text/html' and data:
                    body_html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                elif 'parts' in part:
                    # Recursive for nested parts
                    t, h, a = self._extract_body_and_attachments(part, message_id)
                    body_text += t
                    if h: body_html = h
                    attachments.extend(a)
        else:
             body = payload.get('body', {})
             data = body.get('data')
             mime_type = payload.get('mimeType')
             if data and mime_type == 'text/plain':
                  body_text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
             elif data and mime_type == 'text/html':
                  body_html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

        return body_text, body_html, attachments

    def parse_message(self, message: Dict[str, Any]) -> ParsedEmail:
        payload = message.get('payload', {})
        headers = payload.get('headers', [])

        header_map = {h['name'].lower(): h['value'] for h in headers}

        subject = header_map.get('subject', '(No Subject)')
        sender = header_map.get('from', '')
        date_str = header_map.get('date', '')
        in_reply_to = header_map.get('in-reply-to')

        sender_name, sender_email = parseaddr(sender)

        try:
            received_at = parsedate_to_datetime(date_str) if date_str else datetime.now(timezone.utc)
        except (TypeError, ValueError):
             received_at = datetime.now(timezone.utc)

        message_id = message['id']
        thread_id = message['threadId']
        labels = message.get('labelIds', [])

        body_text, body_html, attachments = self._extract_body_and_attachments(payload, message_id)

        hints = self._get_subject_hints(subject)

        return ParsedEmail(
            message_id=message_id,
            thread_id=thread_id,
            received_at=received_at,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            labels=labels,
            in_reply_to=in_reply_to,
            subject_hints=hints
        )

    def is_already_processed(self, message_id: str) -> bool:
        if not getattr(self.gcp, 'firestore_client', None):
            return False
        doc_ref = self.gcp.firestore_client.collection("processed_emails").document(message_id)
        return doc_ref.get().exists

    def mark_as_processed(self, message_id: str):
        if not getattr(self.gcp, 'firestore_client', None):
            return
        doc_ref = self.gcp.firestore_client.collection("processed_emails").document(message_id)
        doc_ref.set({
            "processed_at": firestore.SERVER_TIMESTAMP,
            "task_id": "gmail_poll"
        })

    def get_or_create_ai_label(self) -> Optional[str]:
        if not self.service: return None
        try:
            results = self.service.users().labels().list(userId=self.inbox_address).execute()
            labels = results.get('labels', [])
            for label in labels:
                if label['name'] == 'AI-Processed':
                    return label['id']

            # Create if not exists
            new_label = {
                'name': 'AI-Processed',
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            created = self.service.users().labels().create(userId=self.inbox_address, body=new_label).execute()
            return created['id']
        except Exception as e:
            logger.error(f"Error getting/creating label: {e}")
            return None

    def apply_ai_label_and_mark_read(self, message_id: str):
        if not self.service: return
        label_id = self.get_or_create_ai_label()
        try:
            body = {
                'removeLabelIds': ['UNREAD']
            }
            if label_id:
                body['addLabelIds'] = [label_id]

            self.service.users().messages().modify(
                userId=self.inbox_address,
                id=message_id,
                body=body
            ).execute()
        except Exception as e:
            logger.error(f"Failed to apply label to {message_id}: {e}")

    def create_ingest_record(self, parsed: ParsedEmail, attachment_drive_paths: List[str]):
        if not getattr(self.gcp, 'firestore_client', None):
            logger.warning("No Firestore client; skipping ingest record creation")
            return

        import uuid
        ingest_id = str(uuid.uuid4())

        doc_data = {
            "message_id": parsed.message_id,
            "ingest_id": ingest_id,
            "received_at": parsed.received_at,
            "sender_email": parsed.sender_email,
            "sender_name": parsed.sender_name,
            "subject": parsed.subject,
            "body_text": parsed.body_text[:10000],
            "body_text_truncated": len(parsed.body_text) > 10000,
            "attachment_drive_paths": attachment_drive_paths,
            "subject_hints": parsed.subject_hints,
            "status": "PENDING_CLASSIFICATION",
            "created_at": firestore.SERVER_TIMESTAMP
        }

        doc_ref = self.gcp.firestore_client.collection("email_ingests").document(ingest_id)
        doc_ref.set(doc_data)
        logger.info(f"Created EmailIngest record: {ingest_id}")

    def upload_attachments_to_drive(self, parsed: ParsedEmail) -> List[str]:
        # Stubbing Drive integration for now as it's not fully built
        # It should interact with src/integrations/drive/service.py
        paths = []
        for att in parsed.attachments:
            # Simulate upload path
            dt_str = parsed.received_at.strftime("%Y-%m-%d")
            path = f"04 - Agent Workspace/Holding Folder/{dt_str}/{parsed.message_id}/{att.filename}"
            paths.append(path)
        return paths

    def poll(self) -> List[str]:
        logger.info("Starting Gmail polling cycle")
        if not self.service:
            logger.error("Gmail service not initialized. Aborting poll.")
            return []

        try:
            # Fetch unread and not AI-processed
            query = "is:unread -label:AI-Processed"
            results = self.service.users().messages().list(
                userId=self.inbox_address,
                q=query,
                maxResults=self.max_emails
            ).execute()

            messages = results.get('messages', [])
            if not messages:
                logger.info("No new emails to process.")
                return []

            processed_ids = []

            for msg_meta in messages:
                msg_id = msg_meta['id']
                if self.is_already_processed(msg_id):
                    logger.info(f"Skipping already processed message: {msg_id}")
                    continue

                msg_full = self.service.users().messages().get(
                    userId=self.inbox_address,
                    id=msg_id,
                    format='full'
                ).execute()

                parsed = self.parse_message(msg_full)

                drive_paths = self.upload_attachments_to_drive(parsed)

                self.create_ingest_record(parsed, drive_paths)

                self.mark_as_processed(msg_id)
                self.apply_ai_label_and_mark_read(msg_id)

                processed_ids.append(msg_id)

            logger.info(f"Finished polling. Processed {len(processed_ids)} emails.")
            return processed_ids

        except HttpError as e:
            if e.resp.status in (401, 403):
                logger.critical(f"Gmail API Auth Error: {e}")
            elif e.resp.status == 429:
                logger.warning(f"Gmail API Rate Limited: {e}")
            else:
                logger.error(f"Gmail API HTTP Error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during polling: {e}")
            return []
