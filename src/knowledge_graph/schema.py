# src/knowledge_graph/schema.py
"""
Neo4j schema setup and Cypher MERGE helpers for the TeterAI Knowledge Graph.

Provides:
  - CONSTRAINTS / VECTOR_INDEXES: DDL statements (IF NOT EXISTS) for all node types
  - apply_schema(driver): idempotent application of all constraints and indexes
  - merge_node(session, label, id_key, data): generic MERGE helper
  - merge_relationship(session, ...): generic relationship MERGE helper

These helpers are used by:
  - scripts/setup_kg_schema.py   (schema DDL)
  - scripts/seed_kg_baseline.py  (baseline data seeding)
  - KnowledgeGraphClient         (runtime writes)
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

import neo4j

from .models import NODE_REGISTRY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Uniqueness constraints
# ---------------------------------------------------------------------------
CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT agent_unique IF NOT EXISTS FOR (n:Agent) REQUIRE n.agent_id IS UNIQUE",
    "CREATE CONSTRAINT playbook_rule_unique IF NOT EXISTS FOR (n:PlaybookRule) REQUIRE n.rule_id IS UNIQUE",
    "CREATE CONSTRAINT escalation_unique IF NOT EXISTS FOR (n:EscalationCriteria) REQUIRE n.criteria_id IS UNIQUE",
    "CREATE CONSTRAINT doc_type_unique IF NOT EXISTS FOR (n:DocumentType) REQUIRE n.type_id IS UNIQUE",
    "CREATE CONSTRAINT workflow_step_unique IF NOT EXISTS FOR (n:WorkflowStep) REQUIRE n.step_id IS UNIQUE",
    "CREATE CONSTRAINT spec_section_unique IF NOT EXISTS FOR (n:SpecSection) REQUIRE n.section_number IS UNIQUE",
    "CREATE CONSTRAINT contract_clause_unique IF NOT EXISTS FOR (n:ContractClause) REQUIRE n.clause_id IS UNIQUE",
    "CREATE CONSTRAINT project_unique IF NOT EXISTS FOR (n:Project) REQUIRE n.project_id IS UNIQUE",
    "CREATE CONSTRAINT ca_document_unique IF NOT EXISTS FOR (n:CADocument) REQUIRE n.drive_file_id IS UNIQUE",
    "CREATE CONSTRAINT party_unique IF NOT EXISTS FOR (n:Party) REQUIRE n.party_id IS UNIQUE",
    "CREATE CONSTRAINT correction_event_unique IF NOT EXISTS FOR (n:CorrectionEvent) REQUIRE n.event_id IS UNIQUE",
    "CREATE CONSTRAINT rfi_unique IF NOT EXISTS FOR (n:RFI) REQUIRE n.rfi_id IS UNIQUE",
    "CREATE CONSTRAINT drawing_sheet_unique IF NOT EXISTS FOR (n:DrawingSheet) REQUIRE (n.sheet_number, n.project_id) IS NODE KEY",
]

# ---------------------------------------------------------------------------
# Vector indexes (Neo4j 5+ / Aura, 768-dim cosine — Vertex AI text-embedding-004)
# ---------------------------------------------------------------------------
VECTOR_INDEXES: list[str] = [
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
    """CREATE VECTOR INDEX drawing_sheet_embeddings IF NOT EXISTS
   FOR (n:DrawingSheet) ON (n.embedding)
   OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}""",
]

ALL_STATEMENTS: list[str] = CONSTRAINTS + VECTOR_INDEXES

# Valid Neo4j labels (used by merge_node for safety)
VALID_LABELS: frozenset[str] = frozenset(
    label for label, _ in NODE_REGISTRY.values()
)


# ---------------------------------------------------------------------------
# Schema application
# ---------------------------------------------------------------------------

def apply_schema(driver: neo4j.Driver) -> list[tuple[str, Exception]]:
    """
    Execute all constraint and vector index DDL statements.
    Safe to call multiple times (IF NOT EXISTS).

    Returns a list of (statement_label, exception) for any failures.
    """
    failed: list[tuple[str, Exception]] = []
    with driver.session() as session:
        for stmt in ALL_STATEMENTS:
            try:
                session.run(stmt).consume()
                label = stmt.split("IF NOT EXISTS")[0].strip()
                logger.info(f"  Applied: {label}")
            except Exception as e:
                label = stmt.split("IF NOT EXISTS")[0].strip()
                logger.error(f"  FAILED: {label}: {e}")
                failed.append((label, e))
    return failed


# ---------------------------------------------------------------------------
# MERGE helpers
# ---------------------------------------------------------------------------

def merge_node(
    session: neo4j.Session,
    label: str,
    id_key: str,
    data: dict[str, Any],
) -> None:
    """
    MERGE a single node by its ID property, setting all other properties.

    Args:
        session: Active Neo4j session.
        label:   Node label (must be in VALID_LABELS).
        id_key:  The property used as the MERGE key (e.g. "agent_id").
        data:    Dict of all properties including the id_key.

    Raises:
        ValueError if label is not in VALID_LABELS.
    """
    if label not in VALID_LABELS:
        raise ValueError(
            f"Invalid node label: {label!r}. Must be one of: {sorted(VALID_LABELS)}"
        )
    props_set = ", ".join(f"n.{k} = ${k}" for k in data if k != id_key)
    if props_set:
        cypher = f"MERGE (n:{label} {{{id_key}: ${id_key}}}) SET {props_set}"
    else:
        cypher = f"MERGE (n:{label} {{{id_key}: ${id_key}}})"
    session.run(cypher, **data)


def merge_node_from_dataclass(session: neo4j.Session, obj: Any) -> None:
    """
    MERGE a node from a dataclass instance, using NODE_REGISTRY to look up
    the label and ID key.

    Args:
        session: Active Neo4j session.
        obj:     A dataclass instance whose type is registered in NODE_REGISTRY.
    """
    cls = type(obj)
    if cls not in NODE_REGISTRY:
        raise ValueError(f"Dataclass {cls.__name__} not in NODE_REGISTRY")
    label, id_key = NODE_REGISTRY[cls]
    data = {k: v for k, v in asdict(obj).items() if v is not None}
    merge_node(session, label, id_key, data)


def merge_relationship(
    session: neo4j.Session,
    from_label: str,
    from_key: str,
    from_value: Any,
    rel_type: str,
    to_label: str,
    to_key: str,
    to_value: Any,
) -> None:
    """
    MERGE a relationship between two existing nodes.

    Example:
        merge_relationship(session,
            "Agent", "agent_id", "AGENT-RFI-001",
            "HAS_RULE",
            "PlaybookRule", "rule_id", "RFI-RULE-001")
    """
    cypher = (
        f"MATCH (a:{from_label} {{{from_key}: $from_val}}) "
        f"MATCH (b:{to_label} {{{to_key}: $to_val}}) "
        f"MERGE (a)-[:{rel_type}]->(b)"
    )
    session.run(cypher, from_val=from_value, to_val=to_value)
