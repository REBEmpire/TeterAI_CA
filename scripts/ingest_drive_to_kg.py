"""
Crawl Google Drive project folders and ingest documents into the Neo4j Knowledge Graph.

Usage:
    python scripts/ingest_drive_to_kg.py                    # all 5 pilot projects
    python scripts/ingest_drive_to_kg.py --project 11900    # single project
    python scripts/ingest_drive_to_kg.py --dry-run          # preview without writes
"""
import sys
import os
import argparse

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(_root, 'src'))
sys.path.insert(0, _root)  # needed for service.py's `from src.ai_engine.gcp import ...`

from ai_engine.gcp import gcp_integration
from integrations.drive.service import DriveService, CANONICAL_FOLDERS, DRIVE_ROOT_FOLDER_ID
from knowledge_graph.client import KnowledgeGraphClient
from knowledge_graph.ingestion import DriveToKGIngester

PILOT_PROJECTS = [
    {"project_id": "11900", "name": "WHCCD - Instructional Center Ph. 1",                     "phase": "construction"},
    {"project_id": "12556", "name": "Golden Valley USD - Canyon Creek ES",                     "phase": "construction"},
    {"project_id": "12333", "name": "FUSD Sunnyside HS Lighting & Sound System",               "phase": "construction"},
    {"project_id": "13055", "name": "Golden Valley USD - Liberty HS Track & Stadium Expansion", "phase": "construction"},
    {"project_id": "13193", "name": "Orosi HS CTE",                                            "phase": "construction"},
]


def _discover_folder_map(drive: DriveService, project_id: str, project_name: str) -> dict:
    """
    Discover the canonical subfolder structure by searching Drive directly.
    Used as a fallback when no Firestore registry exists for a project.
    Searches the Drive root for a folder matching '{project_id}*' then walks
    the CANONICAL_FOLDERS structure within it.
    """
    # Find project root folder inside the shared root
    resp = drive.service.files().list(
        q=(
            f"'{DRIVE_ROOT_FOLDER_ID}' in parents "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and name contains '{project_id}' "
            f"and trashed=false"
        ),
        fields="files(id, name)",
        pageSize=10,
    ).execute()
    candidates = resp.get("files", [])
    if not candidates:
        print(f"  WARNING: No Drive folder found matching project_id {project_id!r}")
        return {}

    project_root_id = candidates[0]["id"]
    print(f"  Discovered project folder: {candidates[0]['name']} ({project_root_id})")

    folder_map = {}
    # Walk each phase folder then each subfolder
    for phase_folder, subfolders in CANONICAL_FOLDERS.items():
        # Find the phase folder
        phase_resp = drive.service.files().list(
            q=(
                f"'{project_root_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and name='{phase_folder}' "
                f"and trashed=false"
            ),
            fields="files(id, name)",
        ).execute()
        phase_candidates = phase_resp.get("files", [])
        if not phase_candidates:
            continue
        phase_id = phase_candidates[0]["id"]

        for sub in subfolders:
            sub_resp = drive.service.files().list(
                q=(
                    f"'{phase_id}' in parents "
                    f"and mimeType='application/vnd.google-apps.folder' "
                    f"and name='{sub}' "
                    f"and trashed=false"
                ),
                fields="files(id, name)",
            ).execute()
            sub_candidates = sub_resp.get("files", [])
            if sub_candidates:
                path = f"{phase_folder}/{sub}"
                folder_map[path] = sub_candidates[0]["id"]

    return folder_map


def _build_folder_map(drive: DriveService, project_id: str, project_name: str) -> dict:
    """Load folder_path -> folder_id map. Tries Firestore first, falls back to Drive discovery."""
    folder_map = {}
    for phase_folder, subfolders in CANONICAL_FOLDERS.items():
        for sub in subfolders:
            path = f"{phase_folder}/{sub}"
            fid = drive.get_folder_id(project_id, path)
            if fid:
                folder_map[path] = fid

    if not folder_map:
        print(f"  No Firestore registry for {project_id} -- discovering from Drive...")
        folder_map = _discover_folder_map(drive, project_id, project_name)

    return folder_map


def ingest_project(
    ingester: DriveToKGIngester,
    drive: DriveService,
    kg: KnowledgeGraphClient,
    project: dict,
    dry_run: bool,
) -> dict:
    project_id = project["project_id"]
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Project {project_id}: {project['name']}")

    # Ensure Project node exists in Neo4j
    if not dry_run:
        root_folder_id = ""
        if gcp_integration.firestore_client:
            doc = gcp_integration.firestore_client.collection("drive_folders").document(project_id).get()
            if doc.exists:
                root_folder_id = doc.to_dict().get("root_folder_id", "")
        kg.upsert_project({
            "project_id":           project_id,
            "project_number":       project_id,
            "name":                 project["name"],
            "phase":                project["phase"],
            "drive_root_folder_id": root_folder_id,
        })

    folder_map = _build_folder_map(drive, project_id, project["name"])
    if not folder_map:
        print(f"  WARNING: No folders found for project {project_id} -- skipping.")
        return {"written": 0, "skipped": 0, "errors": 1, "metadata_only": 0}

    print(f"  Found {len(folder_map)} subfolders")
    stats = ingester.ingest_project(project_id, folder_map=folder_map, dry_run=dry_run)

    status = "[DRY RUN] " if dry_run else ""
    print(
        f"  {status}done: written={stats['written']}  "
        f"skipped={stats['skipped']}  "
        f"errors={stats['errors']}  "
        f"metadata_only={stats['metadata_only']}"
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Drive project documents into Neo4j KG.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project", metavar="PROJECT_ID", help="Ingest a single project")
    args = parser.parse_args()

    # Load secrets into environment
    gcp_integration.load_secrets_to_env()

    missing = [v for v in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    projects = PILOT_PROJECTS
    if args.project:
        projects = [p for p in PILOT_PROJECTS if p["project_id"] == args.project]
        if not projects:
            print(f"ERROR: Project '{args.project}' not in pilot list.")
            print("Available:", ", ".join(p["project_id"] for p in PILOT_PROJECTS))
            sys.exit(1)

    print(f"Ingesting {len(projects)} project(s) from Drive to Neo4j ...")

    drive = DriveService()
    ingester = DriveToKGIngester()
    kg = KnowledgeGraphClient()

    totals = {"written": 0, "skipped": 0, "errors": 0, "metadata_only": 0}
    for p in projects:
        stats = ingest_project(ingester, drive, kg, p, args.dry_run)
        for k in totals:
            totals[k] += stats.get(k, 0)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Summary: "
          f"written={totals['written']}  skipped={totals['skipped']}  "
          f"errors={totals['errors']}  metadata_only={totals['metadata_only']}")

    if not args.dry_run and totals["written"] > 0:
        print("\nVerify in Neo4j console:")
        print("  MATCH (p:Project)-[:HAS_DOCUMENT]->(d:CADocument)")
        print("  RETURN p.project_id, d.doc_type, count(*) ORDER BY p.project_id, count(*) DESC")


if __name__ == "__main__":
    main()
