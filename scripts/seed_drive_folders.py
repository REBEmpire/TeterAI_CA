"""
Seed Firestore project records and Google Drive folder structures for pilot projects.

Creates the canonical folder hierarchy in Drive and registers folder IDs in Firestore
for each project, making them ready to receive training material and CA documents.

Usage:
    python scripts/seed_drive_folders.py                    # seed all 5 pilot projects
    python scripts/seed_drive_folders.py --project 11900    # seed a single project
    python scripts/seed_drive_folders.py --dry-run          # preview without changes
"""
import sys
import os
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ai_engine.gcp import GCPIntegration
from integrations.drive.service import DriveService, DRIVE_ROOT_FOLDER_ID

PILOT_PROJECTS = [
    {"project_number": "11900", "name": "WHCCD - Instructional Center Ph. 1"},
    {"project_number": "12556", "name": "Golden Valley USD - Canyon Creek ES"},
    {"project_number": "12333", "name": "FUSD Sunnyside HS Lighting & Sound System"},
    {"project_number": "13055", "name": "Golden Valley USD - Liberty HS Track & Stadium Expansion-Remodel"},
    {"project_number": "13193", "name": "Orosi HS CTE"},
]


def seed_project(gcp: GCPIntegration, drive: DriveService, project_number: str, name: str, dry_run: bool) -> bool:
    """Seed a single project's Firestore record and Drive folders. Returns True on success."""
    project_id = project_number  # numeric-only project numbers need no transformation
    drive_root_name = f"{project_id} - {name}"

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Project {project_number}: {name}")

    # --- Firestore: check for existing project record ---
    if gcp.firestore_client:
        existing = gcp.firestore_client.collection("projects").document(project_id).get()
        if existing.exists:
            print(f"  ⚠ Firestore record already exists — skipping projects/{project_id}")
            firestore_skipped = True
        else:
            firestore_skipped = False
    else:
        print("  ERROR: Firestore client unavailable.")
        return False

    # --- Drive: check for existing folder registry ---
    if gcp.firestore_client:
        existing_drive = gcp.firestore_client.collection("drive_folders").document(project_id).get()
        drive_skipped = existing_drive.exists
        if drive_skipped:
            print(f"  ⚠ Drive folder registry already exists — skipping drive_folders/{project_id}")
    else:
        drive_skipped = False

    if dry_run:
        if not firestore_skipped:
            print(f"  → Would create Firestore: projects/{project_id}")
        if not drive_skipped:
            print(f"  → Would create Drive folder: \"{drive_root_name}\"")
            print(f"    with 4 phase folders and all canonical subfolders")
        return True

    # --- Write Firestore project record ---
    if not firestore_skipped:
        now = datetime.now(timezone.utc).isoformat()
        project_data = {
            "project_id": project_id,
            "project_number": project_number,
            "name": name,
            "phase": "construction",
            "active": True,
            "known_senders": [],
            "created_at": now,
            "created_by": "seed_script",
        }
        try:
            gcp.firestore_client.collection("projects").document(project_id).set(project_data)
            print(f"  ✓ Firestore: projects/{project_id} created")
        except Exception as e:
            print(f"  ERROR writing Firestore project record: {e}")
            return False

    # --- Create Drive folder hierarchy ---
    if not drive_skipped:
        try:
            result = drive.create_project_folders(project_id, name)
            root_id = result["root_folder_id"]
            folder_count = len(result["folders"])
            drive_url = f"https://drive.google.com/drive/folders/{root_id}"
            print(f"  ✓ Drive: \"{drive_root_name}\" created ({folder_count} subfolders)")
            print(f"    {drive_url}")
        except Exception as e:
            print(f"  ERROR creating Drive folders: {e}")
            return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Seed Google Drive folders for pilot CA projects.")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without making changes")
    parser.add_argument("--project", metavar="PROJECT_NUMBER", help="Seed a single project by number")
    args = parser.parse_args()

    gcp = GCPIntegration()
    if not gcp.firestore_client:
        print("ERROR: Firestore client not available. Check GCP credentials.")
        sys.exit(1)

    if args.dry_run:
        print("=== DRY RUN — no changes will be made ===")
        drive = None
    else:
        try:
            drive = DriveService()
        except Exception as e:
            print(f"ERROR: Could not initialize DriveService: {e}")
            sys.exit(1)

    # Select projects to seed
    if args.project:
        projects = [p for p in PILOT_PROJECTS if p["project_number"] == args.project]
        if not projects:
            print(f"ERROR: Project number '{args.project}' not found in pilot list.")
            print("Available projects:", ", ".join(p["project_number"] for p in PILOT_PROJECTS))
            sys.exit(1)
    else:
        projects = PILOT_PROJECTS

    print(f"\nSeeding {len(projects)} project(s) into Firestore + Google Drive...")
    print(f"Drive root folder ID: {DRIVE_ROOT_FOLDER_ID}")

    success_count = 0
    for p in projects:
        ok = seed_project(gcp, drive, p["project_number"], p["name"], args.dry_run)
        if ok:
            success_count += 1

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done: {success_count}/{len(projects)} project(s) seeded successfully.")
    if not args.dry_run and success_count > 0:
        print("\nVerify in Firestore:")
        for p in projects:
            print(f"  projects/{p['project_number']}")
        print("\nVerify in Google Drive:")
        print(f"  https://drive.google.com/drive/folders/{DRIVE_ROOT_FOLDER_ID}")


if __name__ == "__main__":
    main()
