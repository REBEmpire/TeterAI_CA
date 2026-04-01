# src/knowledge_graph/ingestion.py
"""
DriveToKGIngester — crawls project Drive folders and writes CADocument / Party
nodes into Neo4j via KnowledgeGraphClient.

Text extraction hierarchy:
  PDF  → pypdf (metadata_only=True if < 50 chars extracted)
  DOCX → python-docx
  Google Doc → Drive export as text/plain
  Other → metadata_only=True
"""
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from ai_engine.engine import engine
from ai_engine.models import AIRequest, CapabilityClass
from integrations.drive.service import DriveService
from knowledge_graph.client import KnowledgeGraphClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Folder path → document type mapping
# ---------------------------------------------------------------------------
FOLDER_TO_DOC_TYPE: dict[str, str] = {
    "01 - Bid Phase/PB-RFIs":               "PB_RFI",
    "01 - Bid Phase/Addenda":               "ADDENDUM",
    "01 - Bid Phase/Bid Documents":         "BID_DOC",
    "01 - Bid Phase/Pre-Bid Site Visits":   "SITE_VISIT",
    "02 - Construction/RFIs":               "RFI",
    "02 - Construction/Submittals":         "SUBMITTAL",
    "02 - Construction/Substitution Requests": "SUB_REQ",
    "02 - Construction/PCO-COR":            "PCO_COR",
    "02 - Construction/Bulletins":          "BULLETIN",
    "02 - Construction/Change Orders":      "CHANGE_ORDER",
    "02 - Construction/Pay Applications":   "PAY_APP",
    "02 - Construction/Meeting Minutes":    "MEETING_MINUTES",
    "03 - Closeout/Warranties":             "WARRANTY",
    "03 - Closeout/O&M Manuals":            "OM_MANUAL",
    "03 - Closeout/Gov Paperwork":          "GOV_PAPERWORK",
}

# Phase inferred from folder path prefix
FOLDER_TO_PHASE: dict[str, str] = {
    "01 - Bid Phase": "bid",
    "02 - Construction": "construction",
    "03 - Closeout": "closeout",
}

# Folders to skip entirely
SKIP_PREFIXES = ("04 - Agent Workspace",)

# AI extraction prompt
_EXTRACTION_SYSTEM_PROMPT = """You are a construction administration document analyzer for Teter Architects.
Extract structured information from the CA document text provided.
Respond ONLY with valid JSON — no markdown, no explanation.

Return JSON exactly matching this schema (use null for unknown fields):
{
  "doc_number": "<document number as string, e.g. RFI-045, or null>",
  "contractor_name": "<submitting company name, or null>",
  "date_submitted": "<YYYY-MM-DD, or null>",
  "date_responded": "<YYYY-MM-DD, or null>",
  "summary": "<1-2 sentence summary of the document's key question or decision>",
  "spec_sections": ["<CSI section numbers e.g. '03 30 00'>"],
  "parties": [{"name": "<party name>", "type": "<contractor|owner|consultant>"}]
}"""


def infer_doc_type(folder_path: str) -> str:
    """Map a Drive folder path to a document type string. Returns 'UNKNOWN' if not mapped."""
    return FOLDER_TO_DOC_TYPE.get(folder_path, "UNKNOWN")


def infer_phase(folder_path: str) -> str:
    """Return the project phase from a folder path prefix."""
    for prefix, phase in FOLDER_TO_PHASE.items():
        if folder_path.startswith(prefix):
            return phase
    return "unknown"


def slugify(name: str) -> str:
    """Convert a party name to a stable party_id slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def extract_text(content: bytes, mime_type: str) -> tuple[str, bool]:
    """
    Extract plain text from file bytes.

    Returns:
        (text, metadata_only)
        metadata_only=True when extraction fails or text is too short to be useful.
    """
    if mime_type == "text/plain":
        try:
            text = content.decode("utf-8", errors="replace")
            return text, len(text.strip()) == 0
        except Exception:
            return "", True

    if mime_type == "application/pdf":
        # Guard: require at least the 4-byte PDF magic number before parsing.
        if not content or len(content) < 4 or not content.startswith(b"%PDF"):
            logger.warning("PDF extraction skipped: content is empty or not a valid PDF")
            return "", True

        # Run pypdf in a subprocess so a segfault in its C extension (e.g. on a
        # corrupted PDF) cannot kill the ingestion worker process.
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(content)
                tmp_path = f.name

            script = (
                "import pypdf, io, sys\n"
                f"data = open({repr(tmp_path)}, 'rb').read()\n"
                "r = pypdf.PdfReader(io.BytesIO(data))\n"
                "print('\\n'.join(p.extract_text() or '' for p in r.pages))\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0:
                logger.warning(f"PDF subprocess failed (exit {proc.returncode}): {proc.stderr[:200]}")
                return "", True
            text = proc.stdout
            return text, len(text.strip()) < 50
        except subprocess.TimeoutExpired:
            logger.warning("PDF extraction timed out (60s) — marking metadata_only")
            return "", True
        except Exception as e:
            logger.warning(f"PDF extraction failed: {e}")
            return "", True
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    if mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text, len(text.strip()) == 0
        except Exception as e:
            logger.warning(f"DOCX extraction failed: {e}")
            return "", True

    # Unsupported type (DWG, images, spreadsheets, etc.)
    return "", True


def _parse_ai_extraction(raw: str) -> Optional[dict]:
    """Parse JSON from AI response. Returns None on parse failure."""
    try:
        text = raw.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


class DriveToKGIngester:
    """
    Walks a project's Drive folder hierarchy and ingests each document into Neo4j.
    """

    # Number of concurrent worker threads for parallel file processing.
    # Each worker independently downloads, extracts, calls AI, and writes to Neo4j.
    # Configurable via env var; default 4.  Set to 1 to disable concurrency.
    MAX_WORKERS = int(os.environ.get("INGEST_MAX_WORKERS", "4"))

    def __init__(self):
        self._kg = KnowledgeGraphClient()
        self._drive = DriveService()
        self._stats_lock = threading.Lock()

    def ingest_project(
        self,
        project_id: str,
        folder_map: Optional[dict] = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Ingest all documents for a project.

        Args:
            project_id:  Firestore / Neo4j project_id (e.g. "11900")
            folder_map:  Optional pre-loaded {folder_path: folder_id} dict.
                         If None, it will be fetched from Firestore via DriveService.
            dry_run:     If True, list files but do not write to Neo4j.

        Returns:
            dict with keys: written, skipped, errors, metadata_only
        """
        stats = {"written": 0, "skipped": 0, "errors": 0, "metadata_only": 0}

        # Resolve folder map
        if folder_map is None:
            from integrations.drive.service import CANONICAL_FOLDERS
            folder_map = {}
            for phase_folder, subfolders in CANONICAL_FOLDERS.items():
                for sub in subfolders:
                    path = f"{phase_folder}/{sub}"
                    fid = self._drive.get_folder_id(project_id, path)
                    if fid:
                        folder_map[path] = fid

        # Collect all work items first, filtering already-ingested files
        work_items = []
        for folder_path, folder_id in folder_map.items():
            if any(folder_path.startswith(skip) for skip in SKIP_PREFIXES):
                continue
            try:
                files = self._drive.list_folder_files(folder_id)
            except Exception as e:
                logger.error(f"[{project_id}] Failed to list {folder_path}: {e}")
                with self._stats_lock:
                    stats["errors"] += 1
                continue

            for file_meta in files:
                file_id   = file_meta["id"]
                filename  = file_meta["name"]
                mime_type = file_meta.get("mimeType", "application/octet-stream")

                if self._kg.document_exists(file_id):
                    logger.debug(f"[{project_id}] Skipping existing: {filename}")
                    with self._stats_lock:
                        stats["skipped"] += 1
                    continue

                work_items.append((file_id, filename, mime_type, folder_path))

        if not work_items:
            return stats

        logger.info(f"[{project_id}] Processing {len(work_items)} new files with {self.MAX_WORKERS} workers.")

        def _process_one(item):
            file_id, filename, mime_type, folder_path = item
            return self._process_file(
                project_id=project_id,
                file_id=file_id,
                filename=filename,
                mime_type=mime_type,
                folder_path=folder_path,
                dry_run=dry_run,
            )

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            futures = {pool.submit(_process_one, item): item for item in work_items}
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    _, filename, _, _ = futures[future]
                    logger.error(f"[{project_id}] Unhandled exception for {filename}: {exc}")
                    result = "error"
                with self._stats_lock:
                    if result == "written":
                        stats["written"] += 1
                    elif result == "metadata_only":
                        stats["written"] += 1
                        stats["metadata_only"] += 1
                    elif result == "error":
                        stats["errors"] += 1

        return stats

    def _process_file(
        self,
        project_id: str,
        file_id: str,
        filename: str,
        mime_type: str,
        folder_path: str,
        dry_run: bool,
    ) -> str:
        """
        Download, extract, AI-analyse, embed, and write one file.
        Returns: 'written' | 'metadata_only' | 'error'
        """
        doc_type = infer_doc_type(folder_path)
        phase    = infer_phase(folder_path)

        # --- Dry-run: just report what would be processed ---
        if dry_run:
            print(f"  [DRY RUN] {filename} -> {doc_type} ({folder_path})")
            return "written"

        # --- Download ---
        try:
            if mime_type == "application/vnd.google-apps.document":
                # Google Docs: export as plain text
                content = self._drive.service.files().export(
                    fileId=file_id, mimeType="text/plain"
                ).execute()
                if isinstance(content, bytes):
                    raw_bytes = content
                    effective_mime = "text/plain"
                else:
                    raw_bytes = content.encode("utf-8")
                    effective_mime = "text/plain"
            elif mime_type == "application/vnd.google-apps.spreadsheet":
                # Google Sheets: export as CSV
                content = self._drive.service.files().export(
                    fileId=file_id, mimeType="text/csv"
                ).execute()
                if isinstance(content, bytes):
                    raw_bytes = content
                else:
                    raw_bytes = content.encode("utf-8")
                effective_mime = "text/plain"
            else:
                raw_bytes, effective_mime = self._drive.download_file(file_id)
        except Exception as e:
            logger.error(f"[{project_id}] Drive download failed for {filename}: {e}")
            return "error"

        # --- Extract text ---
        text, metadata_only = extract_text(raw_bytes, effective_mime)

        # --- AI extraction ---
        ai_data = None
        if not metadata_only and text:
            try:
                request = AIRequest(
                    capability_class=CapabilityClass.EXTRACT,
                    system_prompt=_EXTRACTION_SYSTEM_PROMPT,
                    user_prompt=(
                        f"FILENAME: {filename}\n"
                        f"FOLDER: {folder_path}\n"
                        f"DOCUMENT TEXT (first 3000 chars):\n{text[:3000]}"
                    ),
                    temperature=0.0,
                    calling_agent="kg_ingester",
                    task_id=f"ingest-{file_id[:8]}",
                )
                response = engine.generate_response(request)
                ai_data = _parse_ai_extraction(response.content)
                if ai_data is None:
                    logger.error(f"[{project_id}] AI parse failed for {filename} — storing metadata only")
                    metadata_only = True
            except Exception as e:
                logger.error(f"[{project_id}] AI extraction failed for {filename}: {e}")
                metadata_only = True

        # --- Assemble document data ---
        summary = (ai_data or {}).get("summary") or f"{doc_type} document: {filename}"
        doc_number = (ai_data or {}).get("doc_number")
        # Always include file_id suffix to guarantee uniqueness across Drive files
        # that may share the same AI-extracted doc_number (e.g. re-issued RFIs).
        doc_id = f"{project_id}_{doc_type}_{doc_number}_{file_id[:8]}" if doc_number else f"{project_id}_{doc_type}_{file_id[:8]}"

        # --- Generate embedding ---
        embedding: list = []
        embedding_model = ""
        try:
            embedding = engine.generate_embedding(summary)
            embedding_model = "text-embedding"
        except Exception as e:
            logger.warning(f"[{project_id}] Embedding failed for {filename}: {e}")

        doc_data = {
            "drive_file_id":     file_id,
            "doc_id":            doc_id,
            "filename":          filename,
            "drive_folder_path": folder_path,
            "doc_type":          doc_type,
            "doc_number":        doc_number,
            "phase":             phase,
            "date_submitted":    (ai_data or {}).get("date_submitted"),
            "date_responded":    (ai_data or {}).get("date_responded"),
            "summary":           summary,
            "embedding":         embedding,
            "embedding_model":   embedding_model,
            "metadata_only":     metadata_only,
        }

        # --- Write to Neo4j ---
        try:
            self._kg.upsert_document(doc_data, project_id)

            # Parties
            for party in (ai_data or {}).get("parties") or []:
                name = party.get("name", "").strip()
                ptype = party.get("type", "contractor")
                if name:
                    party_id = slugify(name)
                    self._kg.upsert_party({"party_id": party_id, "name": name, "type": ptype})
                    self._kg.link_document_to_party(file_id, party_id)

            logger.info(f"[{project_id}] ✓ {filename} ({doc_type}) metadata_only={metadata_only}")
        except Exception as e:
            logger.error(f"[{project_id}] Neo4j write failed for {filename}: {e}")
            return "error"

        return "metadata_only" if metadata_only else "written"
