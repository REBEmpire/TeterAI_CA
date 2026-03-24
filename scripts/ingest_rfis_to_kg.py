"""
Ingest RFI documents from Google Drive into the Neo4j Knowledge Graph (Tier 3).

For each of the three pilot projects, reads all files from the '02 - Construction/RFIs'
Drive folder, extracts structured RFI data via the AI Engine, and upserts Project and
RFI nodes into Neo4j with embeddings for semantic search.

Usage:
    python scripts/ingest_rfis_to_kg.py                    # ingest all 3 projects
    python scripts/ingest_rfis_to_kg.py --project 11900    # single project
    python scripts/ingest_rfis_to_kg.py --dry-run          # list files only, no KG writes
"""
import sys
import os
import io
import json
import logging
import argparse
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from neo4j import GraphDatabase
from ai_engine.engine import engine
from ai_engine.models import AIRequest, CapabilityClass
from ai_engine.gcp import gcp_integration
from integrations.drive.service import DriveService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingest_rfis")

# Projects to ingest — matching seed_drive_folders.py
PROJECTS = [
    {"project_id": "11900", "project_number": "11900", "project_name": "WHCCD - Instructional Center Ph. 1", "client_name": "WHCCD"},
    {"project_id": "12556", "project_number": "12556", "project_name": "Golden Valley USD - Canyon Creek ES", "client_name": "Golden Valley USD"},
    {"project_id": "12333", "project_number": "12333", "project_name": "FUSD Sunnyside HS Lighting & Sound System", "client_name": "FUSD"},
]

RFI_FOLDER_PATH = "02 - Construction/RFIs"

EXTRACT_SYSTEM_PROMPT = """You are a construction administration assistant. Extract structured data from an RFI (Request for Information) document.

Output ONLY a valid JSON object with these fields:
{
  "rfi_number": "<contractor's RFI number as a string, e.g. '045'>",
  "date_submitted": "<ISO date string YYYY-MM-DD, or empty string if not found>",
  "contractor_name": "<contractor company name, or empty string>",
  "question": "<the full RFI question or clarification being asked>",
  "response_text": "<the response/answer text if present, or empty string if unanswered>",
  "response_date": "<ISO date string YYYY-MM-DD of the response, or empty string>",
  "referenced_spec_sections": ["<CSI section number like '03 30 00'>", ...],
  "referenced_drawings": ["<drawing sheet reference like 'S-101'>", ...],
  "status": "<'answered' if a response is present, otherwise 'open'>"
}

Rules:
- rfi_number must be just the number digits/alphanumeric ID, not the full prefix
- Extract ALL spec section references mentioned anywhere in the document
- Extract ALL drawing sheet references (patterns like A-101, S-201, M-301, E-101, etc.)
- If the document is just the question with no response, set status to 'open'
- Output only the JSON object — no explanation, no markdown fences"""


def extract_text_from_file(content: bytes, mime_type: str, file_name: str, drive_service: DriveService, file_id: str) -> str:
    """Extract plain text from a file based on its MIME type."""
    # Google Docs — export as plain text
    if mime_type == "application/vnd.google-apps.document":
        try:
            request = drive_service.service.files().export_media(fileId=file_id, mimeType="text/plain")
            buf = io.BytesIO()
            from googleapiclient.http import MediaIoBaseDownload
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buf.getvalue().decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"  Could not export Google Doc {file_name}: {e}")
            return ""

    # PDF — use pypdf
    if mime_type == "application/pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n".join(pages)
        except Exception as e:
            logger.warning(f"  Could not parse PDF {file_name}: {e}")
            return ""

    # DOCX — use python-docx
    if mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            logger.warning(f"  Could not parse DOCX {file_name}: {e}")
            return ""

    # Plain text
    if mime_type.startswith("text/"):
        return content.decode("utf-8", errors="replace")

    logger.warning(f"  Unsupported MIME type '{mime_type}' for {file_name} — skipping")
    return ""


def extract_rfi_data(text: str, file_name: str) -> Optional[dict]:
    """Use AI Engine EXTRACT capability to parse structured RFI data from document text."""
    if not text.strip():
        logger.warning(f"  Empty text extracted from {file_name} — skipping AI extraction")
        return None

    user_prompt = f"Filename: {file_name}\n\n---\n\n{text[:12000]}"  # cap at ~12k chars

    try:
        request = AIRequest(
            capability_class=CapabilityClass.EXTRACT,
            system_prompt=EXTRACT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            task_id=f"ingest-rfi-{file_name}",
            calling_agent="INGEST-RFI-SCRIPT",
            temperature=0.0,
        )
        response = engine.generate_response(request)
        raw = response.content.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        return data

    except json.JSONDecodeError as e:
        logger.warning(f"  AI returned invalid JSON for {file_name}: {e}")
        return None
    except Exception as e:
        logger.warning(f"  AI extraction failed for {file_name}: {e}")
        return None


def upsert_rfi_to_kg(session, project: dict, rfi_data: dict, file_id: str, file_name: str, embedding: list) -> str:
    """Upsert Project and RFI nodes and relationships into Neo4j. Returns the rfi_id."""
    rfi_number = str(rfi_data.get("rfi_number", "UNKNOWN")).strip()
    rfi_id = f"{project['project_id']}-RFI-{rfi_number}"
    now = datetime.now(timezone.utc).isoformat()

    # Upsert Project node (Tier 3)
    session.run("""
    MERGE (p:Project {project_id: $project_id})
    SET p.project_number = $project_number,
        p.project_name   = $project_name,
        p.client_name    = $client_name,
        p.phase          = 'construction'
    """, project_id=project["project_id"],
         project_number=project["project_number"],
         project_name=project["project_name"],
         client_name=project["client_name"])

    # Upsert RFI node (Tier 3)
    session.run("""
    MERGE (r:RFI {rfi_id: $rfi_id})
    SET r.project_id                = $project_id,
        r.rfi_number                = $rfi_number,
        r.contractor_name           = $contractor_name,
        r.question                  = $question,
        r.response_text             = $response_text,
        r.date_submitted            = $date_submitted,
        r.response_date             = $response_date,
        r.referenced_spec_sections  = $referenced_spec_sections,
        r.referenced_drawings       = $referenced_drawings,
        r.status                    = $status,
        r.source_file_id            = $source_file_id,
        r.source_file_name          = $source_file_name,
        r.embedding                 = $embedding,
        r.embedding_model           = 'vertex_ai/text-embedding-004',
        r.embedding_updated_at      = datetime(),
        r.ingested_at               = $ingested_at
    WITH r
    MATCH (p:Project {project_id: $project_id})
    MERGE (p)-[:HAS_RFI]->(r)
    """,
    rfi_id=rfi_id,
    project_id=project["project_id"],
    rfi_number=rfi_number,
    contractor_name=rfi_data.get("contractor_name", ""),
    question=rfi_data.get("question", ""),
    response_text=rfi_data.get("response_text", ""),
    date_submitted=rfi_data.get("date_submitted", ""),
    response_date=rfi_data.get("response_date", ""),
    referenced_spec_sections=rfi_data.get("referenced_spec_sections", []),
    referenced_drawings=rfi_data.get("referenced_drawings", []),
    status=rfi_data.get("status", "open"),
    source_file_id=file_id,
    source_file_name=file_name,
    embedding=embedding,
    ingested_at=now)

    # Link to existing SpecSection nodes for each referenced spec section
    for section_num in rfi_data.get("referenced_spec_sections", []):
        try:
            session.run("""
            MATCH (r:RFI {rfi_id: $rfi_id})
            MATCH (s:SpecSection {section_number: $section_number})
            MERGE (r)-[:REFERENCES_SPEC]->(s)
            """, rfi_id=rfi_id, section_number=section_num.strip())
        except Exception as e:
            logger.debug(f"    Could not link spec section '{section_num}': {e}")

    return rfi_id


def ingest_project(project: dict, drive: DriveService, neo4j_session, dry_run: bool) -> dict:
    """Ingest all RFIs for one project. Returns counts dict."""
    project_id = project["project_id"]
    project_name = project["project_name"]
    counts = {"found": 0, "ingested": 0, "skipped": 0, "errors": 0}

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Project {project_id}: {project_name}")

    # Look up the RFI folder
    folder_id = drive.get_folder_id(project_id, RFI_FOLDER_PATH)
    if not folder_id:
        logger.error(f"  RFI folder not found in Firestore for project {project_id}. "
                     f"Run seed_drive_folders.py first.")
        counts["errors"] += 1
        return counts

    # List files in the folder
    try:
        files = drive.list_folder_files(folder_id)
    except Exception as e:
        logger.error(f"  Could not list files in RFI folder: {e}")
        counts["errors"] += 1
        return counts

    counts["found"] = len(files)
    print(f"  Found {len(files)} file(s) in '{RFI_FOLDER_PATH}'")

    if dry_run:
        for f in files:
            print(f"    {f['name']} ({f['mimeType']})")
        return counts

    for file_meta in files:
        file_id = file_meta["id"]
        file_name = file_meta["name"]
        mime_type = file_meta["mimeType"]
        print(f"  Processing: {file_name}")

        try:
            # Download file
            content, _ = drive.download_file(file_id)

            # Extract text
            text = extract_text_from_file(content, mime_type, file_name, drive, file_id)
            if not text.strip():
                logger.warning(f"    No text extracted — skipping")
                counts["skipped"] += 1
                continue

            # Extract RFI data via AI
            rfi_data = extract_rfi_data(text, file_name)
            if not rfi_data:
                logger.warning(f"    RFI extraction failed — skipping")
                counts["skipped"] += 1
                continue

            rfi_number = rfi_data.get("rfi_number", "UNKNOWN")
            logger.info(f"    Extracted RFI #{rfi_number}: {rfi_data.get('status', 'open')}")

            # Generate embedding from the question text
            question_text = rfi_data.get("question", file_name)
            try:
                embedding = engine.generate_embedding(question_text)
            except Exception as e:
                logger.warning(f"    Embedding failed: {e} — skipping")
                counts["skipped"] += 1
                continue

            # Write to KG
            rfi_id = upsert_rfi_to_kg(neo4j_session, project, rfi_data, file_id, file_name, embedding)
            print(f"    -> KG node: {rfi_id}")
            counts["ingested"] += 1

        except Exception as e:
            logger.error(f"    Unexpected error processing {file_name}: {e}")
            counts["errors"] += 1

    return counts


def main():
    parser = argparse.ArgumentParser(description="Ingest RFI documents from Google Drive into the Knowledge Graph.")
    parser.add_argument("--dry-run", action="store_true", help="List files only; do not write to KG")
    parser.add_argument("--project", metavar="PROJECT_ID", help="Ingest a single project (e.g. 11900)")
    args = parser.parse_args()

    # Load secrets
    gcp_integration.load_secrets_to_env()

    # Select projects
    if args.project:
        projects = [p for p in PROJECTS if p["project_id"] == args.project]
        if not projects:
            print(f"ERROR: Project '{args.project}' not in ingest list.")
            print("Available:", ", ".join(p["project_id"] for p in PROJECTS))
            sys.exit(1)
    else:
        projects = PROJECTS

    # Initialize Drive
    try:
        drive = DriveService()
    except Exception as e:
        print(f"ERROR: Could not initialize DriveService: {e}")
        sys.exit(1)

    # Initialize Neo4j
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")

    if not uri or not user or not password:
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set.")
        sys.exit(1)

    driver = GraphDatabase.driver(uri, auth=(user, password))

    try:
        with driver.session() as session:
            if not args.dry_run:
                # Ensure RFI schema (constraints + vector index) exists
                print("Setting up RFI schema in Knowledge Graph...")
                from knowledge_graph.client import kg_client
                kg_client.setup_rfi_schema()
                print("Schema ready.")

            total_counts = {"found": 0, "ingested": 0, "skipped": 0, "errors": 0}

            for project in projects:
                counts = ingest_project(project, drive, session, args.dry_run)
                for k in total_counts:
                    total_counts[k] += counts[k]

    finally:
        driver.close()

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done.")
    print(f"  Files found:    {total_counts['found']}")
    if not args.dry_run:
        print(f"  RFIs ingested:  {total_counts['ingested']}")
        print(f"  Skipped:        {total_counts['skipped']}")
        print(f"  Errors:         {total_counts['errors']}")

    if not args.dry_run and total_counts["ingested"] > 0:
        print("\nVerify in Neo4j Browser:")
        print("  MATCH (p:Project)-[:HAS_RFI]->(r:RFI) RETURN p.project_name, count(r) AS rfi_count")
        print("  MATCH (r:RFI)-[:REFERENCES_SPEC]->(s:SpecSection)")
        print("    RETURN s.section_number, s.title, count(r) AS mentions ORDER BY mentions DESC")


if __name__ == "__main__":
    main()
