"""
Seed a test email_ingest document into Firestore for live dispatcher testing.

Usage:
    python scripts/seed_test_ingest.py
    python scripts/seed_test_ingest.py --ingest-id INGEST-TEST-002
"""
import sys
import os
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ai_engine.gcp import GCPIntegration


def seed_ingest(ingest_id: str = "INGEST-TEST-001"):
    gcp = GCPIntegration()
    if not gcp.firestore_client:
        print("ERROR: Firestore client not available. Check GCP credentials.")
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "ingest_id": ingest_id,
        "message_id": f"msg-{ingest_id}",
        "received_at": now,
        "sender_email": "contractor@buildco.com",
        "sender_name": "Bob Builder",
        "subject": "RFI #045 - Concrete Mix Design Clarification [Project 2024-001]",
        "body_text": (
            "Hi Teter team,\n\n"
            "We need clarification on the concrete mix design specified in Section 03300 "
            "for the footing pours on Project 2024-001. The spec calls for 4000 PSI but "
            "our supplier only has 3500 PSI available within the required lead time. "
            "Please advise if a substitution is acceptable or if we need to source elsewhere.\n\n"
            "This is holding our pour scheduled for next week.\n\n"
            "Thanks,\nBob"
        ),
        "body_text_truncated": False,
        "attachment_drive_paths": [],
        "subject_hints": {
            "doc_type_hint": "RFI",
            "doc_number_hint": "045",
            "project_number_hint": "2024-001",
            "is_reply": False,
        },
        "status": "PENDING_CLASSIFICATION",
        "created_at": now,
    }

    try:
        gcp.firestore_client.collection("email_ingests").document(ingest_id).set(doc)
        print(f"✓ Seeded email_ingest: {ingest_id}")
        print(f"  Subject: {doc['subject']}")
        print(f"  Status:  {doc['status']}")
        print(f"\nRun the dispatcher:")
        print(f"  python main.py")
        print(f"\nThen check Firestore:")
        print(f"  email_ingests/{ingest_id}  → status should be PROCESSED")
        print(f"  tasks/TASK-{ingest_id}-*   → status should be ASSIGNED_TO_AGENT")
    except Exception as e:
        print(f"ERROR seeding ingest: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a test email_ingest for dispatcher testing.")
    parser.add_argument("--ingest-id", default="INGEST-TEST-001", help="Ingest document ID")
    args = parser.parse_args()
    seed_ingest(args.ingest_id)
