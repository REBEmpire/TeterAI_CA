"""
LocalStorageService — local filesystem replacement for DriveService.

Mirrors the DriveService public API exactly so no agent code needs
to change when running in DESKTOP_MODE.

Folder IDs in this service are local absolute filesystem paths.
"""
import logging
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

from config.local_config import LocalConfig

logger = logging.getLogger(__name__)

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
    ],
}


class LocalStorageService:
    """Local filesystem storage — drop-in replacement for DriveService."""

    def __init__(self, config: LocalConfig, db_client=None):
        self._root = Path(config.projects_root).expanduser()
        self._root.mkdir(parents=True, exist_ok=True)
        self._db = db_client  # SQLiteClient; may be None

    # ------------------------------------------------------------------
    # Project folder management
    # ------------------------------------------------------------------

    def create_project_folders(self, project_id: str, project_name: str) -> dict:
        """Create canonical folder structure on disk and register paths in SQLite."""
        root_name = f"{project_id} - {project_name}"
        root_path = self._root / root_name
        root_path.mkdir(parents=True, exist_ok=True)

        folder_registry: dict[str, str] = {}

        for phase_folder, subfolders in CANONICAL_FOLDERS.items():
            phase_path = root_path / phase_folder
            phase_path.mkdir(exist_ok=True)
            folder_registry[phase_folder] = str(phase_path)

            for sub in subfolders:
                sub_path = phase_path / sub
                sub_path.mkdir(exist_ok=True)
                folder_registry[f"{phase_folder}/{sub}"] = str(sub_path)

        # Persist to SQLite folder_registry
        if self._db:
            for folder_path, local_path in folder_registry.items():
                self._db.collection("folder_registry").document(
                    f"{project_id}::{folder_path}"
                ).set({
                    "project_id": project_id,
                    "folder_path": folder_path,
                    "local_path": local_path,
                })
            # Store root project info
            self._db.collection("projects").document(project_id).set({
                "project_id": project_id,
                "name": project_name,
                "local_root_path": str(root_path),
            }, merge=True)

        return {
            "root_folder_id": str(root_path),
            "folders": folder_registry,
        }

    def get_folder_id(self, project_id: str, folder_path: str) -> Optional[str]:
        """Return the local filesystem path for a project folder."""
        if self._db:
            try:
                doc = self._db.collection("folder_registry").document(
                    f"{project_id}::{folder_path}"
                ).get()
                if doc.exists:
                    return doc.to_dict().get("local_path")
            except Exception as e:
                logger.debug(f"folder_registry lookup failed: {e}")

        # Fallback: reconstruct from projects_root
        try:
            if self._db:
                proj_doc = self._db.collection("projects").document(project_id).get()
                if proj_doc.exists:
                    root = proj_doc.to_dict().get("local_root_path", "")
                    if root:
                        candidate = Path(root) / folder_path
                        if candidate.exists():
                            return str(candidate)
        except Exception:
            pass

        # Last resort: scan projects root for matching project_id prefix
        for p in self._root.iterdir():
            if p.is_dir() and p.name.startswith(project_id):
                candidate = p / folder_path
                if candidate.exists():
                    return str(candidate)

        return None

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def upload_file(self, folder_id: str, filename: str, content: bytes, mime_type: str) -> str:
        """Write file to local folder. Returns the absolute file path (acts as 'file_id')."""
        dest_dir = Path(folder_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename
        dest_path.write_bytes(content)
        logger.info(f"Saved file: {dest_path}")
        return str(dest_path)

    def move_file(self, file_id: str, destination_folder_id: str, new_name: Optional[str] = None) -> None:
        """Move a file to a new folder, optionally renaming it."""
        src = Path(file_id)
        dest_dir = Path(destination_folder_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = new_name or src.name
        dest_path = dest_dir / dest_name
        shutil.move(str(src), str(dest_path))
        logger.info(f"Moved file: {src} → {dest_path}")

    def download_file(self, file_id: str) -> Tuple[bytes, str]:
        """Read file bytes from local path. file_id is an absolute path."""
        path = Path(file_id)
        if not path.exists():
            raise FileNotFoundError(f"Local file not found: {file_id}")
        mime_type, _ = mimetypes.guess_type(str(path))
        mime_type = mime_type or "application/octet-stream"
        return path.read_bytes(), mime_type

    def list_folder_files(self, folder_id: str) -> list[dict]:
        """Return list of {id, name, mimeType} for files in a local folder."""
        folder = Path(folder_id)
        if not folder.exists():
            return []
        result = []
        for f in folder.iterdir():
            if f.is_file():
                mime_type, _ = mimetypes.guess_type(str(f))
                result.append({
                    "id": str(f),
                    "name": f.name,
                    "mimeType": mime_type or "application/octet-stream",
                })
        return result

    def next_doc_number(self, project_id: str, doc_type: str) -> int:
        """Atomically increment document counter via SQLite."""
        if not self._db:
            raise RuntimeError("SQLiteClient not available for document counter")
        return self._db.increment_counter(project_id, doc_type)

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    TOOL_DELIVERY_FOLDERS: dict[str, str] = {
        "rfi": "RFIs",
        "submittal": "Submittals",
        "cost": "PCOs",
        "payapp": "PayApplications",
        "schedule": "Schedules",
    }

    def deliver_approved_document(
        self,
        task_id: str,
        tool_type: str,
        project_name: str,
        doc_title: str,
        content: bytes,
        filename_suffix: str = "Approved",
    ) -> str:
        """
        Save an approved document to the structured delivery folder.

        Path:
            ~/TeterAI/Delivered/{project_name}/{tool_folder}/{task_id}_{doc_title}_{suffix}.docx

        Returns the full absolute path of the saved file.
        If tool_type is not recognised the subfolder defaults to "Other".
        """
        import re

        def _sanitize(s: str) -> str:
            s = s.replace(" ", "_")
            s = re.sub(r"[^\w\-]", "", s)
            return s or "unnamed"

        tool_folder = self.TOOL_DELIVERY_FOLDERS.get(tool_type.lower(), "Other")
        safe_project = _sanitize(project_name)
        safe_title = _sanitize(doc_title)
        safe_suffix = _sanitize(filename_suffix)

        delivery_root = Path.home() / "TeterAI" / "Delivered"
        dest_dir = delivery_root / safe_project / tool_folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{task_id}_{safe_title}_{safe_suffix}.docx"
        dest_path = dest_dir / filename
        dest_path.write_bytes(content)

        logger.info(f"[{task_id}] Delivered approved document: {dest_path}")
        return str(dest_path)
