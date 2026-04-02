"""
Apply Neo4j constraints and vector indexes for TeterAI_CA Knowledge Graph.
Safe to re-run -- all statements use IF NOT EXISTS.

Usage:
    python scripts/setup_kg_schema.py
    python scripts/setup_kg_schema.py --dry-run
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import neo4j

# ---------------------------------------------------------------------------
# Uniqueness constraints
# ---------------------------------------------------------------------------
CONSTRAINTS = [
    "CREATE CONSTRAINT agent_unique IF NOT EXISTS FOR (n:Agent) REQUIRE n.agent_id IS UNIQUE",
    "CREATE CONSTRAINT playbook_rule_unique IF NOT EXISTS FOR (n:PlaybookRule) REQUIRE n.rule_id IS UNIQUE",
    "CREATE CONSTRAINT escalation_unique IF NOT EXISTS FOR (n:EscalationCriteria) REQUIRE n.criteria_id IS UNIQUE",
    "CREATE CONSTRAINT doc_type_unique IF NOT EXISTS FOR (n:DocumentType) REQUIRE n.type_id IS UNIQUE",
    "CREATE CONSTRAINT workflow_step_unique IF NOT EXISTS FOR (n:WorkflowStep) REQUIRE n.step_id IS UNIQUE",
    # SpecSection section_number is NOT globally unique — sections are project-scoped.
    # upsert_spec_section MERGEs on {section_number, project_id} for idempotency.
    "CREATE CONSTRAINT contract_clause_unique IF NOT EXISTS FOR (n:ContractClause) REQUIRE n.clause_id IS UNIQUE",
    "CREATE CONSTRAINT project_unique IF NOT EXISTS FOR (n:Project) REQUIRE n.project_id IS UNIQUE",
    "CREATE CONSTRAINT ca_document_unique IF NOT EXISTS FOR (n:CADocument) REQUIRE n.drive_file_id IS UNIQUE",
    "CREATE CONSTRAINT party_unique IF NOT EXISTS FOR (n:Party) REQUIRE n.party_id IS UNIQUE",
    "CREATE CONSTRAINT correction_event_unique IF NOT EXISTS FOR (n:CorrectionEvent) REQUIRE n.event_id IS UNIQUE",
    "CREATE CONSTRAINT rfi_unique IF NOT EXISTS FOR (n:RFI) REQUIRE n.rfi_id IS UNIQUE",
]

# ---------------------------------------------------------------------------
# Vector indexes (Neo4j 5+ / Aura syntax, 768-dim cosine)
# ---------------------------------------------------------------------------
VECTOR_INDEXES = [
    """CREATE VECTOR INDEX spec_section_embeddings IF NOT EXISTS
   FOR (n:SpecSection) ON (n.embedding)
   OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}""",
    """CREATE VECTOR INDEX contract_clause_embeddings IF NOT EXISTS
   FOR (n:ContractClause) ON (n.embedding)
   OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}""",
    """CREATE VECTOR INDEX playbook_rule_embeddings IF NOT EXISTS
   FOR (n:PlaybookRule) ON (n.embedding)
   OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}""",
    """CREATE VECTOR INDEX ca_document_embeddings IF NOT EXISTS
   FOR (n:CADocument) ON (n.embedding)
   OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}""",
    """CREATE VECTOR INDEX rfi_embeddings IF NOT EXISTS
   FOR (n:RFI) ON (n.embedding)
   OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}""",
]

ALL_STATEMENTS = CONSTRAINTS + VECTOR_INDEXES


def apply_schema(driver: neo4j.Driver) -> None:
    """Execute every DDL statement. Safe to call multiple times. Reports all failures."""
    failed = []
    with driver.session() as session:
        for stmt in ALL_STATEMENTS:
            try:
                session.run(stmt).consume()
                label = stmt.split("IF NOT EXISTS")[0].strip()
                print(f"  v {label}")
            except Exception as e:
                label = stmt.split("IF NOT EXISTS")[0].strip()
                print(f"  ERROR: {label}: {e}")
                failed.append((label, e))
    if failed:
        raise RuntimeError(
            f"{len(failed)} schema statement(s) failed:\n" +
            "\n".join(f"  - {label}: {err}" for label, err in failed)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Neo4j KG schema constraints and vector indexes.")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing")
    args = parser.parse_args()

    # Dry-run needs no credentials
    if args.dry_run:
        print(f"=== DRY RUN -- {len(ALL_STATEMENTS)} statements would be applied ===")
        for stmt in ALL_STATEMENTS:
            print(f"  -> {stmt.split(chr(10))[0].strip()}")
        return

    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")

    if not all([uri, username, password]):
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set.")
        sys.exit(1)

    print(f"Applying {len(ALL_STATEMENTS)} schema statements to {uri} ...")
    driver = neo4j.GraphDatabase.driver(uri, auth=(username, password))
    try:
        apply_schema(driver)
        print(f"\nDone. {len(CONSTRAINTS)} constraints + {len(VECTOR_INDEXES)} vector indexes applied.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
