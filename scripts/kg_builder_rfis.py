"""
Build a Knowledge Graph from RFI documents using Neo4j's SimpleKGPipeline.

Downloads RFI files from Google Drive, runs them through the neo4j-graphrag
SimpleKGPipeline with a construction-domain schema (entities: RFI, SpecSection,
Drawing, Contractor, ConstructionIssue, Material), and writes the resulting
lexical graph + extracted entities to Neo4j.

This complements ingest_rfis_to_kg.py (which writes structured Project/RFI nodes)
by adding the chunk-based semantic graph that Neo4j recommends for unstructured docs.

Usage:
    python scripts/kg_builder_rfis.py                    # all 3 pilot projects
    python scripts/kg_builder_rfis.py --project 11900    # single project
    python scripts/kg_builder_rfis.py --dry-run          # list files, no KG writes
    python scripts/kg_builder_rfis.py --limit 2          # first 2 files per project
"""
import asyncio
import io
import logging
import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import neo4j
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
from neo4j_graphrag.llm import AnthropicLLM
from neo4j_graphrag.embeddings.base import Embedder

from ai_engine.engine import engine
from ai_engine.gcp import gcp_integration
from integrations.drive.service import DriveService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("kg_builder_rfis")

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
PROJECTS = [
    {"project_id": "11900", "project_name": "WHCCD - Instructional Center Ph. 1"},
    {"project_id": "12556", "project_name": "Golden Valley USD - Canyon Creek ES"},
    {"project_id": "12333", "project_name": "FUSD Sunnyside HS Lighting & Sound System"},
]

RFI_FOLDER_PATH = "02 - Construction/RFIs"

# ---------------------------------------------------------------------------
# Construction-domain schema for entity / relation extraction
# ---------------------------------------------------------------------------
ENTITIES = [
    {"label": "RFI",               "description": "A Request for Information identified by number, e.g. RFI-045"},
    {"label": "SpecSection",       "description": "A CSI specification section number and title, e.g. '03 30 00 Cast-in-Place Concrete'"},
    {"label": "Drawing",           "description": "A construction drawing sheet reference, e.g. 'S-101', 'A-201', 'M-301'"},
    {"label": "Contractor",        "description": "A general contractor, subcontractor, or specialty contractor company"},
    {"label": "ConstructionIssue", "description": "A specific construction problem, discrepancy, or clarification needed"},
    {"label": "Material",          "description": "A construction material, product, or system"},
]

RELATIONS = [
    {"label": "REFERENCES_SPEC",    "description": "RFI references or asks about a specification section"},
    {"label": "REFERENCES_DRAWING", "description": "RFI references a construction drawing sheet"},
    {"label": "SUBMITTED_BY",       "description": "RFI was submitted by this contractor"},
    {"label": "ADDRESSES",          "description": "RFI addresses or describes this construction issue"},
    {"label": "INVOLVES",           "description": "Construction issue involves this material or product"},
]

POTENTIAL_SCHEMA = [
    ("RFI", "REFERENCES_SPEC",    "SpecSection"),
    ("RFI", "REFERENCES_DRAWING", "Drawing"),
    ("RFI", "SUBMITTED_BY",       "Contractor"),
    ("RFI", "ADDRESSES",          "ConstructionIssue"),
    ("ConstructionIssue", "INVOLVES", "Material"),
]


# ---------------------------------------------------------------------------
# Custom embedder — wraps the existing AI Engine (Vertex AI text-embedding-004)
# ---------------------------------------------------------------------------
class EngineEmbedder(Embedder):
    def embed_query(self, text: str) -> list[float]:
        return engine.generate_embedding(text)


# ---------------------------------------------------------------------------
# Text extraction helpers for non-PDF files
# ---------------------------------------------------------------------------
def _export_google_doc(drive: DriveService, file_id: str, file_name: str) -> str:
    try:
        from googleapiclient.http import MediaIoBaseDownload
        request = drive.service.files().export_media(fileId=file_id, mimeType="text/plain")
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"  Could not export Google Doc {file_name}: {e}")
        return ""


def _extract_docx(content: bytes, file_name: str) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        logger.warning(f"  Could not parse DOCX {file_name}: {e}")
        return ""


def extract_text(
    content: bytes,
    mime_type: str,
    file_name: str,
    drive: DriveService,
    file_id: str,
) -> str:
    if mime_type == "application/vnd.google-apps.document":
        return _export_google_doc(drive, file_id, file_name)
    if mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        return _extract_docx(content, file_name)
    if mime_type.startswith("text/"):
        return content.decode("utf-8", errors="replace")
    logger.warning(f"  Unsupported MIME type '{mime_type}' for {file_name}")
    return ""


# ---------------------------------------------------------------------------
# Per-file pipeline execution
# ---------------------------------------------------------------------------
async def process_file(
    kg_builder: SimpleKGPipeline,
    file_meta: dict,
    drive: DriveService,
    content: bytes,
    mime_type: str,
) -> None:
    file_name = file_meta["name"]
    file_id = file_meta["id"]

    if mime_type == "application/pdf":
        # Write to a temp file so SimpleKGPipeline can parse it with from_pdf=True
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            await kg_builder.run_async(file_path=str(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        text = extract_text(content, mime_type, file_name, drive, file_id)
        if not text.strip():
            logger.warning(f"  No text extracted from {file_name} — skipping")
            return
        await kg_builder.run_async(text=text)


# ---------------------------------------------------------------------------
# Per-project ingest
# ---------------------------------------------------------------------------
async def process_project(
    project: dict,
    drive: DriveService,
    kg_builder: SimpleKGPipeline,
    dry_run: bool,
    limit: int = 0,
) -> dict:
    project_id = project["project_id"]
    project_name = project["project_name"]
    counts = {"found": 0, "processed": 0, "skipped": 0, "errors": 0}

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Project {project_id}: {project_name}")

    folder_id = drive.get_folder_id(project_id, RFI_FOLDER_PATH)
    if not folder_id:
        logger.error(f"  RFI folder not found in Firestore for project {project_id}. "
                     "Run seed_drive_folders.py first.")
        counts["errors"] += 1
        return counts

    try:
        files = drive.list_folder_files(folder_id)
    except Exception as e:
        logger.error(f"  Could not list RFI folder files: {e}")
        counts["errors"] += 1
        return counts

    counts["found"] = len(files)
    if limit:
        files = files[:limit]

    print(f"  Found {counts['found']} file(s)" + (f" (processing first {limit})" if limit else ""))

    if dry_run:
        for f in files:
            print(f"    {f['name']} ({f['mimeType']})")
        return counts

    for file_meta in files:
        file_name = file_meta["name"]
        mime_type = file_meta["mimeType"]
        print(f"  Processing: {file_name}")

        try:
            content, _ = drive.download_file(file_meta["id"])
            await process_file(kg_builder, file_meta, drive, content, mime_type)
            counts["processed"] += 1
            logger.info(f"    -> KG updated for {file_name}")
        except Exception as e:
            logger.error(f"    Error processing {file_name}: {e}")
            counts["errors"] += 1

    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a KG from RFI PDFs using Neo4j SimpleKGPipeline."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="List files only; do not write to KG")
    parser.add_argument("--project", metavar="PROJECT_ID",
                        help="Ingest a single project (e.g. 11900)")
    parser.add_argument("--limit", type=int, default=0, metavar="N",
                        help="Max files per project (default: all)")
    args = parser.parse_args()

    # Load secrets (falls back to env vars if Secret Manager unreachable)
    gcp_integration.load_secrets_to_env()

    # Project selection
    projects = PROJECTS
    if args.project:
        projects = [p for p in PROJECTS if p["project_id"] == args.project]
        if not projects:
            print(f"ERROR: Project '{args.project}' not in ingest list.")
            print("Available:", ", ".join(p["project_id"] for p in PROJECTS))
            sys.exit(1)

    # Drive
    try:
        drive = DriveService()
    except Exception as e:
        print(f"ERROR: Could not initialize DriveService: {e}")
        sys.exit(1)

    # Neo4j
    neo4j_uri = os.environ.get("NEO4J_URI")
    neo4j_user = os.environ.get("NEO4J_USERNAME")
    neo4j_pass = os.environ.get("NEO4J_PASSWORD")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not all([neo4j_uri, neo4j_user, neo4j_pass]):
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set.")
        sys.exit(1)
    if not anthropic_key:
        print("ERROR: ANTHROPIC_API_KEY must be set.")
        sys.exit(1)

    neo4j_driver = neo4j.GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))

    # LLM + Embedder
    llm = AnthropicLLM(
        model_name="claude-3-5-haiku-20241022",
        api_key=anthropic_key,
    )
    embedder = EngineEmbedder()

    # Pipeline
    kg_builder = SimpleKGPipeline(
        llm=llm,
        driver=neo4j_driver,
        embedder=embedder,
        from_pdf=True,
        entities=ENTITIES,
        relations=RELATIONS,
        potential_schema=POTENTIAL_SCHEMA,
        neo4j_database="neo4j",
    )

    total = {"found": 0, "processed": 0, "skipped": 0, "errors": 0}
    try:
        for project in projects:
            counts = await process_project(project, drive, kg_builder, args.dry_run, args.limit)
            for k in total:
                total[k] += counts[k]
    finally:
        neo4j_driver.close()

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done.")
    print(f"  Files found:     {total['found']}")
    if not args.dry_run:
        print(f"  Processed:       {total['processed']}")
        print(f"  Errors:          {total['errors']}")

    if not args.dry_run and total["processed"] > 0:
        print("\nVerify in Neo4j Browser:")
        print("  MATCH (n) WHERE n:RFI OR n:SpecSection OR n:Contractor OR n:Drawing")
        print("    RETURN labels(n)[0] AS type, count(n) AS count")
        print("  MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)-[:MENTIONS]->(e)")
        print("    RETURN d.id, c.text, labels(e)[0], e.id LIMIT 10")


if __name__ == "__main__":
    asyncio.run(main())
