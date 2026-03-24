import json
import io
import os
from typing import Dict, Any, Optional, Tuple
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.cloud import firestore

from src.ai_engine.gcp import gcp_integration

DRIVE_ROOT_FOLDER_ID = '11VPprN5--8PPvgFoZFQWTqABRUuiNLkQ'

# Global inbox folder for inbound attachments before project classification.
# Set DRIVE_INBOX_FOLDER_ID in Secret Manager or env to the "Holding Folder"
# shared folder ID. Falls back to root if unset.
DRIVE_INBOX_FOLDER_ID = os.environ.get("DRIVE_INBOX_FOLDER_ID", DRIVE_ROOT_FOLDER_ID)

CANONICAL_FOLDERS = {
    "01 - Bid Phase": [
        "PB-RFIs",
        "Addenda",
        "Bid Documents",
        "Pre-Bid Site Visits",
    ],
    "02 - Construction": [
        "RFIs",
        "Submittals",
        "Substitution Requests",
        "PCO-COR",
        "Bulletins",
        "Change Orders",
        "Pay Applications",
        "Meeting Minutes",
        "Punchlist",
    ],
    "03 - Closeout": [
        "Warranties",
        "O&M Manuals",
        "Gov Paperwork",
    ],
    "04 - Agent Workspace": [
        "Holding Folder",
        "Thought Chains",
        "Source Docs",
        "Agent Logs",
    ]
}

class DriveService:
    def __init__(self):
        self.service = self._get_drive_service()
        self.db = gcp_integration.firestore_client

    def _get_drive_service(self):
        secret_json = gcp_integration.get_secret('drive-service-account')
        if not secret_json:
            raise ValueError("Could not load drive-service-account from Secret Manager")

        creds_info = json.loads(secret_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=creds)

    def _create_folder_in_drive(self, name: str, parent_id: str) -> str:
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = self.service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

    def create_project_folders(self, project_id: str, project_name: str) -> Dict[str, Any]:
        """Creates the canonical folder structure for a new project and stores IDs in Firestore."""
        # 1. Create root folder [YYYY-NNN] - [Project Name]
        root_name = f"{project_id} - {project_name}"
        root_folder_id = self._create_folder_in_drive(root_name, DRIVE_ROOT_FOLDER_ID)

        folder_registry = {}

        # 2. Recursively create canonical subfolders
        for phase_folder, subfolders in CANONICAL_FOLDERS.items():
            phase_id = self._create_folder_in_drive(phase_folder, root_folder_id)
            folder_registry[phase_folder] = phase_id

            for sub in subfolders:
                sub_id = self._create_folder_in_drive(sub, phase_id)
                folder_registry[f"{phase_folder}/{sub}"] = sub_id

        # 3. Store in Firestore registry
        if self.db:
            doc_ref = self.db.collection('drive_folders').document(project_id)
            doc_ref.set({
                'root_folder_id': root_folder_id,
                'folders': folder_registry,
                'created_at': firestore.SERVER_TIMESTAMP,
                'last_verified_at': firestore.SERVER_TIMESTAMP
            })

        return {
            'root_folder_id': root_folder_id,
            'folders': folder_registry
        }

    def get_folder_id(self, project_id: str, folder_path: str) -> Optional[str]:
        """Looks up a folder ID from the Firestore registry."""
        if not self.db:
            return None
        doc_ref = self.db.collection('drive_folders').document(project_id)
        doc = doc_ref.get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return data.get('folders', {}).get(folder_path)

    def upload_file(self, folder_id: str, filename: str, content: bytes, mime_type: str) -> str:
        """Uploads a file to a specific Drive folder."""
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=True)
        file = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')

    def move_file(self, file_id: str, destination_folder_id: str, new_name: Optional[str] = None) -> None:
        """Moves a file to a new folder, optionally renaming it."""
        # Retrieve the existing parents to remove
        file = self.service.files().get(fileId=file_id, fields='parents').execute()
        previous_parents = ",".join(file.get('parents', []))

        # Move the file to the new folder
        update_kwargs = {
            'fileId': file_id,
            'addParents': destination_folder_id,
            'removeParents': previous_parents,
            'fields': 'id, parents'
        }

        if new_name:
            update_kwargs['body'] = {'name': new_name}

        self.service.files().update(**update_kwargs).execute()

    def download_file(self, file_id: str) -> Tuple[bytes, str]:
        """Download file bytes and mime_type from Drive by file ID."""
        meta = self.service.files().get(fileId=file_id, fields='mimeType').execute()
        mime_type = meta.get('mimeType', 'application/octet-stream')
        request = self.service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue(), mime_type

    def list_folder_files(self, folder_id: str) -> list[dict]:
        """Returns list of {id, name, mimeType} dicts for all non-trashed files in the given folder."""
        results = []
        page_token = None
        while True:
            resp = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token
            ).execute()
            results.extend(resp.get('files', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        return results

    def next_doc_number(self, project_id: str, doc_type: str) -> int:
        """Atomically increments the document counter in Firestore."""
        if not self.db:
            raise Exception("Firestore client not available")

        counter_ref = self.db.collection('projects').document(project_id).collection('doc_counters').document(doc_type)

        @firestore.transactional
        def increment_in_transaction(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if snapshot.exists:
                new_count = snapshot.get('count') + 1
            else:
                new_count = 1
            transaction.set(ref, {'count': new_count})
            return new_count

        transaction = self.db.transaction()
        return increment_in_transaction(transaction, counter_ref)
