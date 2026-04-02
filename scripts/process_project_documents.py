#!/usr/bin/env python
"""
Process project spec books and drawing sets into the Document Intelligence
content store (SQLite) and enrich the Knowledge Graph (Neo4j).

Searches each project's Google Drive root folder for files matching:
  - Spec books:    *SPEC_A.pdf, *Conformed Book.pdf
  - Drawing sets:  *DWG_A.pdf,  *Conformed Set.pdf

Usage:
    python scripts/process_project_documents.py                    # all projects
    python scripts/process_project_documents.py --project 11900    # single project
    python scripts/process_project_documents.py --dry-run          # preview without processing
    python scripts/process_project_documents.py --db-path ./chunks.db
"""
import argparse
import logging
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config.local_config import LocalConfig
LocalConfig.ensure_exists().push_to_env()

from knowledge_graph.client import KnowledgeGraphClient
from integrations.drive.service import DriveService
from document_intelligence.storage.chunk_store import ChunkStore
from document_intelligence.service import DocumentIntelligenceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("process_documents")

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "document_intelligence.db"
)

# Substring keywords — case-insensitive
# Drawing sets: DWG_A, Conformed Drawings, Conformed Set, BID Drawings
_DRAWING_KEYWORDS = ["DWG_A", "Conformed Drawings", "Conformed Set", "BID Drawings"]
# Spec books: SPC_A, SPEC_A, Conformed Specifications, Conformed Book, BID Specifications
_SPEC_KEYWORDS = ["SPC_A", "SPEC_A", "Conformed Specifications", "Conformed Book", "BID Specifications"]


def classify_root_file(filename: str) -> str | None:
    """Return 'spec_book', 'drawing_set', or None based on Drive root filename."""
    lower = filename.lower()
    for kw in _SPEC_KEYWORDS:
        if kw.lower() in lower:
            return "spec_book"
    for kw in _DRAWING_KEYWORDS:
        if kw.lower() in lower:
            return "drawing_set"
    return None


def get_project_root_folder_id(kg: KnowledgeGraphClient, project_id: str) -> str | None:
    """Return the Drive root folder ID for a project from Neo4j."""
    result: dict = {}

    def _do():
        with kg._session() as session:
            row = session.run(
                "MATCH (p:Project {project_id: $pid}) RETURN p.drive_root_folder_id AS fid",
                pid=project_id,
            ).single()
            result["fid"] = row["fid"] if row and row["fid"] else None

    kg._run_with_retry(_do)
    return result.get("fid")


def scan_root_for_candidates(drive: DriveService, folder_id: str) -> list[dict]:
    """
    List files in the Drive root folder and return those matching
    spec book or drawing set naming conventions.

    Returns list of {drive_file_id, filename, doc_type}.
    """
    try:
        files = drive.list_folder_files(folder_id)
    except Exception as e:
        logger.error(f"Failed to list Drive folder {folder_id}: {e}")
        return []

    candidates = []
    for f in files:
        if f.get("mimeType") != "application/pdf":
            continue
        doc_type = classify_root_file(f["name"])
        if doc_type:
            candidates.append({
                "drive_file_id": f["id"],
                "filename": f["name"],
                "doc_type": doc_type,
            })
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process project spec books and drawing sets."
    )
    parser.add_argument("--project", type=str, help="Single project ID to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview without processing")
    parser.add_argument("--db-path", type=str, default=DEFAULT_DB_PATH, help="SQLite DB path")
    args = parser.parse_args()

    # Connect
    kg = KnowledgeGraphClient()

    # Discover all projects with a root folder ID if no --project given
    if args.project:
        project_ids = [args.project]
    else:
        result: dict = {}
        def _get_projects():
            with kg._session() as session:
                result["rows"] = session.run(
                    "MATCH (p:Project) WHERE p.drive_root_folder_id IS NOT NULL "
                    "RETURN p.project_id AS pid ORDER BY p.project_id"
                ).data()
        kg._run_with_retry(_get_projects)
        project_ids = [r["pid"] for r in result.get("rows", [])]

    if not args.dry_run:
        os.makedirs(os.path.dirname(os.path.abspath(DEFAULT_DB_PATH)), exist_ok=True)
        store = ChunkStore(args.db_path)
        service = DocumentIntelligenceService(chunk_store=store, kg_client=kg)

    total_stats = {"processed": 0, "skipped": 0, "failed": 0, "chunks": 0}

    for project_id in project_ids:
        print(f"\n{'='*60}")
        print(f"Project: {project_id}")
        print(f"{'='*60}")

        root_folder_id = get_project_root_folder_id(kg, project_id)
        if not root_folder_id:
            print(f"  No Drive root folder ID in KG — skipping")
            continue

        # Fresh DriveService per project — prevents TCP 10053 errors from idle connections
        drive = DriveService()
        candidates = scan_root_for_candidates(drive, root_folder_id)
        if not candidates:
            print(f"  No spec books or drawing sets found in root folder")
            continue

        for candidate in candidates:
            filename = candidate["filename"]
            doc_type = candidate["doc_type"]
            drive_file_id = candidate["drive_file_id"]
            neo4j_doc_id = f"{project_id}_{doc_type.upper()}_{drive_file_id[:8]}"

            if args.dry_run:
                print(f"  [DRY RUN] {filename}  ->  {doc_type}")
                continue

            # Skip if already indexed
            if store.is_document_indexed(neo4j_doc_id):
                print(f"  Already indexed: {filename}")
                total_stats["skipped"] += 1
                continue

            print(f"  Downloading: {filename} ({doc_type})...")
            tmp_path = None
            try:
                # Retry download once with a fresh Drive client on connection error
                try:
                    content, mime = drive.download_file(drive_file_id, timeout=300)
                except OSError:
                    logger.warning("Download connection error, retrying with fresh client...")
                    drive = DriveService()
                    content, mime = drive.download_file(drive_file_id, timeout=300)
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(content)
                    tmp_path = f.name

                print(f"  Processing ({os.path.getsize(tmp_path) // 1024 / 1024:.1f} MB)...")
                result = service.process_document(
                    project_id=project_id,
                    pdf_path=tmp_path,
                    file_name=filename,
                    doc_type=doc_type,
                    neo4j_doc_id=neo4j_doc_id,
                )

                if result["status"] == "indexed":
                    print(f"    Indexed: {result['chunks_created']} chunks created")
                    total_stats["processed"] += 1
                    total_stats["chunks"] += result["chunks_created"]
                elif result["status"] == "skipped":
                    print(f"    Already indexed")
                    total_stats["skipped"] += 1
                else:
                    print(f"    Failed: {result['errors']}")
                    total_stats["failed"] += 1

            except Exception as e:
                logger.exception(f"Error processing {filename}")
                print(f"    Error: {e}")
                total_stats["failed"] += 1
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

    # Summary
    print(f"\n{'='*60}")
    if args.dry_run:
        print("Dry run complete — no files processed.")
    else:
        print(f"Summary: {total_stats['processed']} indexed, "
              f"{total_stats['chunks']} chunks created, "
              f"{total_stats['skipped']} skipped, "
              f"{total_stats['failed']} failed")
        store.close()

    kg.close()


if __name__ == "__main__":
    main()
