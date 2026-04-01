#!/usr/bin/env python
"""
Process project spec books and drawing sets into the Document Intelligence
content store (SQLite) and enrich the Knowledge Graph (Neo4j).

Usage:
    python scripts/process_project_documents.py                    # all projects
    python scripts/process_project_documents.py --project 11900    # single project
    python scripts/process_project_documents.py --dry-run          # preview only
    python scripts/process_project_documents.py --db-path ./chunks.db  # custom DB path

Reads CADocument nodes from Neo4j to find spec books and drawing sets,
downloads PDFs from Google Drive, and processes them.
"""
import argparse
import logging
import os
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

# Pilot projects
PILOT_PROJECTS = ["11900", "12333", "12556", "12660", "12757"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process project spec books and drawing sets."
    )
    parser.add_argument("--project", type=str, help="Single project ID to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview without processing")
    parser.add_argument("--db-path", type=str, default=DEFAULT_DB_PATH, help="SQLite DB path")
    args = parser.parse_args()

    project_ids = [args.project] if args.project else PILOT_PROJECTS

    # Initialize services
    kg = KnowledgeGraphClient()
    drive = DriveService()
    store = ChunkStore(args.db_path)
    service = DocumentIntelligenceService(chunk_store=store, kg_client=kg)

    total_stats = {"processed": 0, "skipped": 0, "failed": 0, "chunks": 0}

    for project_id in project_ids:
        print(f"\n{'='*60}")
        print(f"Project: {project_id}")
        print(f"{'='*60}")

        # Get CADocument nodes that look like spec books or drawing sets
        docs = kg.get_project_documents(project_id)
        candidates = []
        for doc in docs:
            doc_type = service.classify_document(doc.get("filename", ""))
            if doc_type:
                candidates.append((doc, doc_type))

        if not candidates:
            print(f"  No spec books or drawing sets found for project {project_id}")
            continue

        for doc, doc_type in candidates:
            filename = doc.get("filename", "unknown")
            doc_id = doc.get("doc_id", "")
            drive_file_id = doc.get("drive_file_id", "")

            if args.dry_run:
                print(f"  [DRY RUN] {filename} -> {doc_type}")
                total_stats["processed"] += 1
                continue

            # Download PDF to temp file
            print(f"  Processing: {filename} ({doc_type})...")
            try:
                content, mime = drive.download_file(drive_file_id)
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(content)
                    tmp_path = f.name

                result = service.process_document(
                    project_id=project_id,
                    pdf_path=tmp_path,
                    file_name=filename,
                    doc_type=doc_type,
                    neo4j_doc_id=doc_id,
                )

                if result["status"] == "indexed":
                    print(f"    Indexed: {result['chunks_created']} chunks created")
                    total_stats["processed"] += 1
                    total_stats["chunks"] += result["chunks_created"]
                elif result["status"] == "skipped":
                    print(f"    Already indexed, skipping")
                    total_stats["skipped"] += 1
                else:
                    print(f"    Failed: {result['errors']}")
                    total_stats["failed"] += 1

            except Exception as e:
                print(f"    Error: {e}")
                total_stats["failed"] += 1
            finally:
                try:
                    os.unlink(tmp_path)
                except (OSError, UnboundLocalError):
                    pass

    # Summary
    print(f"\n{'='*60}")
    print(f"Summary: {total_stats['processed']} processed, "
          f"{total_stats['chunks']} chunks created, "
          f"{total_stats['skipped']} skipped, "
          f"{total_stats['failed']} failed")

    store.close()
    kg.close()


if __name__ == "__main__":
    main()
