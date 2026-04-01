# Knowledge Graph Implementation & Drive Ingestion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `src/knowledge_graph/client.py`, seed the Neo4j KG with Tier 1/2/4 baseline data, and build a Drive-to-KG ingestion pipeline that crawls existing project folders and extracts structured document nodes.

**Architecture:** `KnowledgeGraphClient` wraps the `neo4j` Python driver and exposes typed query methods that agents call directly. Baseline seed scripts populate the graph with playbooks, workflow steps, CSI divisions, and AIA clauses. `DriveToKGIngester` walks each project's Drive folder tree, extracts text with `pypdf`/`python-docx`, calls `AIEngine.generate_response` to summarise and extract metadata, generates an embedding via `AIEngine.generate_embedding`, and MERGEs `CADocument` + `Party` nodes into Neo4j.

**Tech Stack:** Python 3.12, neo4j>=6.1.0, pypdf, python-docx, litellm (via AIEngine), google-api-python-client (DriveService), pytest + unittest.mock

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/knowledge_graph/__init__.py` | Package init + re-export `kg_client` |
| Create | `src/knowledge_graph/client.py` | `KnowledgeGraphClient` class + `kg_client` singleton |
| Create | `scripts/setup_kg_schema.py` | CLI: idempotent constraints + vector indexes |
| Create | `scripts/seed_kg_baseline.py` | CLI: Tier 1 (playbooks), Tier 2 (workflows), Tier 4 (CSI/AIA) |
| Create | `src/knowledge_graph/ingestion.py` | `DriveToKGIngester` service |
| Create | `scripts/ingest_drive_to_kg.py` | CLI: Drive → KG ingestion runner |
| Extend | `tests/test_kg_client.py` | Add tests for new project-layer methods |
| Create | `tests/test_kg_ingestion.py` | Tests for `DriveToKGIngester` |

---

## Task 1: `src/knowledge_graph/client.py` — Core KG Client

**Files:**
- Create: `src/knowledge_graph/__init__.py`
- Create: `src/knowledge_graph/client.py`
- Extend: `tests/test_kg_client.py`

> **Context:** `tests/test_kg_client.py` already exists with 3 passing-once-implemented tests. `agents/kg/flaw_extractor.py` imports `from knowledge_graph.client import kg_client` and accesses `kg_client._driver` directly. The test file patches `src.knowledge_graph.client.engine` — so `engine` must be a module-level import.

- [ ] **Step 1.1: Run the existing failing tests to establish baseline**

```bash
cd 'C:\Users\RussellBybee\Documents\Adventures in AI Land\TeterAI_CA\TeterAI_CA'
python -m pytest tests/test_kg_client.py -v 2>&1 | head -40
```
Expected: 3 ERRORs — `ModuleNotFoundError: No module named 'knowledge_graph'`

- [ ] **Step 1.2: Create `src/knowledge_graph/__init__.py`**

```python
# src/knowledge_graph/__init__.py
from .client import KnowledgeGraphClient, kg_client

__all__ = ["KnowledgeGraphClient", "kg_client"]
```

- [ ] **Step 1.3: Create `src/knowledge_graph/client.py`**

```python
# src/knowledge_graph/client.py
import os
import logging
from typing import Optional

import neo4j

from ai_engine.engine import engine

logger = logging.getLogger(__name__)


class KnowledgeGraphClient:
    """
    Wraps the Neo4j Python driver. All agents call this — never raw Cypher.
    Gracefully degrades when Neo4j env vars are absent (returns empty lists / None).
    """

    def __init__(self):
        uri = os.environ.get("NEO4J_URI")
        username = os.environ.get("NEO4J_USERNAME")
        password = os.environ.get("NEO4J_PASSWORD")

        if uri and username and password:
            try:
                self._driver = neo4j.GraphDatabase.driver(uri, auth=(username, password))
            except Exception as e:
                logger.warning(f"Neo4j connection failed: {e}")
                self._driver = None
        else:
            logger.debug("NEO4J_* env vars not set — KG client running in no-op mode.")
            self._driver = None

    # ------------------------------------------------------------------
    # Tier 1 — Agent Playbooks
    # ------------------------------------------------------------------

    def get_agent_playbook(self, agent_id: str) -> list[dict]:
        """Return PlaybookRule dicts for the given agent, ordered by priority."""
        if not self._driver:
            return []
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (:Agent {agent_id: $agent_id})-[:HAS_RULE]->(r:PlaybookRule)
                RETURN r.rule_id AS rule_id, r.description AS description,
                       r.condition AS condition, r.action AS action,
                       r.confidence_threshold AS confidence_threshold,
                       r.priority AS priority
                ORDER BY r.priority
                """,
                agent_id=agent_id,
            )
            return [record.data() for record in result]

    def log_correction(
        self,
        event_id: str,
        agent_id: str,
        task_id: str,
        original_text: str,
        corrected_text: str,
        correction_type: str,
        reviewed_by: str,
        rule_id: Optional[str] = None,
    ) -> None:
        """Persist a CorrectionEvent node and optionally link it to a PlaybookRule."""
        if not self._driver:
            return
        with self._driver.session() as session:
            session.run(
                """
                MERGE (c:CorrectionEvent {event_id: $event_id})
                SET c.agent_id         = $agent_id,
                    c.task_id          = $task_id,
                    c.original_text    = $original_text,
                    c.corrected_text   = $corrected_text,
                    c.correction_type  = $correction_type,
                    c.reviewed_by      = $reviewed_by,
                    c.timestamp        = datetime()
                """,
                event_id=event_id,
                agent_id=agent_id,
                task_id=task_id,
                original_text=original_text,
                corrected_text=corrected_text,
                correction_type=correction_type,
                reviewed_by=reviewed_by,
            )
            if rule_id:
                session.run(
                    """
                    MATCH (c:CorrectionEvent {event_id: $event_id})
                    MATCH (r:PlaybookRule {rule_id: $rule_id})
                    MERGE (c)-[:UPDATES]->(r)
                    """,
                    event_id=event_id,
                    rule_id=rule_id,
                )

    # ------------------------------------------------------------------
    # Tier 2 — Workflow Process
    # ------------------------------------------------------------------

    def get_document_workflow(self, doc_type: str) -> list[dict]:
        """Return WorkflowStep dicts for the given document type, ordered by sequence."""
        if not self._driver:
            return []
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (:DocumentType {type_id: $doc_type})-[:FOLLOWS_WORKFLOW]->(ws:WorkflowStep)
                RETURN ws.step_id          AS step_id,
                       ws.name             AS name,
                       ws.description      AS description,
                       ws.responsible_party AS responsible_party,
                       ws.sequence         AS sequence
                ORDER BY ws.sequence
                """,
                doc_type=doc_type,
            )
            return [record.data() for record in result]

    # ------------------------------------------------------------------
    # Tier 4 — Industry Knowledge
    # ------------------------------------------------------------------

    def search_spec_sections(self, query: str, top_k: int = 5) -> list[dict]:
        """Semantic search over SpecSection nodes using the embedding vector index."""
        if not self._driver:
            return []
        embedding = engine.generate_embedding(query)
        with self._driver.session() as session:
            result = session.run(
                """
                CALL db.index.vector.queryNodes('spec_section_embeddings', $top_k, $embedding)
                YIELD node, score
                WHERE score > 0.75
                RETURN node.csi_division    AS csi_division,
                       node.section_number  AS section_number,
                       node.title           AS title,
                       node.content_summary AS content_summary,
                       score
                ORDER BY score DESC
                """,
                top_k=top_k,
                embedding=embedding,
            )
            return [record.data() for record in result]

    def get_contract_clause(self, clause_id: str) -> Optional[dict]:
        """Fetch a single ContractClause by its clause_id. Returns None if not found."""
        if not self._driver:
            return None
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (c:ContractClause {clause_id: $clause_id})
                RETURN c.clause_id    AS clause_id,
                       c.standard     AS standard,
                       c.clause_number AS clause_number,
                       c.title        AS title,
                       c.text         AS text
                """,
                clause_id=clause_id,
            )
            records = [record.data() for record in result]
            return records[0] if records else None

    # ------------------------------------------------------------------
    # Project Document Layer (Tier 3 extension)
    # ------------------------------------------------------------------

    def upsert_project(self, project_data: dict) -> None:
        """MERGE a Project node. Keys: project_id, project_number, name, phase, drive_root_folder_id."""
        if not self._driver:
            return
        with self._driver.session() as session:
            session.run(
                """
                MERGE (p:Project {project_id: $project_id})
                SET p.project_number       = $project_number,
                    p.name                 = $name,
                    p.phase                = $phase,
                    p.drive_root_folder_id = $drive_root_folder_id
                """,
                **project_data,
            )

    def document_exists(self, drive_file_id: str) -> bool:
        """Return True if a CADocument with this drive_file_id already exists in the graph."""
        if not self._driver:
            return False
        with self._driver.session() as session:
            result = session.run(
                "MATCH (d:CADocument {drive_file_id: $drive_file_id}) RETURN count(d) AS cnt",
                drive_file_id=drive_file_id,
            )
            record = result.single()
            return (record["cnt"] > 0) if record else False

    def upsert_document(self, doc_data: dict, project_id: str) -> None:
        """
        MERGE a CADocument node and link it to its Project.

        Required keys in doc_data:
            drive_file_id, doc_id, filename, drive_folder_path, doc_type,
            doc_number, phase, date_submitted, date_responded,
            summary, embedding, embedding_model, metadata_only
        """
        if not self._driver:
            return
        with self._driver.session() as session:
            session.run(
                """
                MERGE (d:CADocument {drive_file_id: $drive_file_id})
                SET d.doc_id             = $doc_id,
                    d.filename           = $filename,
                    d.drive_folder_path  = $drive_folder_path,
                    d.doc_type           = $doc_type,
                    d.doc_number         = $doc_number,
                    d.phase              = $phase,
                    d.date_submitted     = $date_submitted,
                    d.date_responded     = $date_responded,
                    d.summary            = $summary,
                    d.embedding          = $embedding,
                    d.embedding_model    = $embedding_model,
                    d.embedding_updated_at = datetime(),
                    d.metadata_only      = $metadata_only
                WITH d
                MATCH (p:Project {project_id: $project_id})
                MERGE (p)-[:HAS_DOCUMENT]->(d)
                """,
                **doc_data,
                project_id=project_id,
            )

    def upsert_party(self, party_data: dict) -> None:
        """MERGE a Party node. Keys: party_id, name, type."""
        if not self._driver:
            return
        with self._driver.session() as session:
            session.run(
                """
                MERGE (party:Party {party_id: $party_id})
                SET party.name = $name,
                    party.type = $type
                """,
                **party_data,
            )

    def link_document_to_party(self, drive_file_id: str, party_id: str) -> None:
        """Create (:CADocument)-[:SUBMITTED_BY]->(:Party) relationship."""
        if not self._driver:
            return
        with self._driver.session() as session:
            session.run(
                """
                MATCH (d:CADocument {drive_file_id: $drive_file_id})
                MATCH (party:Party {party_id: $party_id})
                MERGE (d)-[:SUBMITTED_BY]->(party)
                """,
                drive_file_id=drive_file_id,
                party_id=party_id,
            )

    def get_project_documents(
        self, project_id: str, doc_type: Optional[str] = None
    ) -> list[dict]:
        """Return CADocument dicts for a project, optionally filtered by doc_type."""
        if not self._driver:
            return []
        with self._driver.session() as session:
            if doc_type:
                result = session.run(
                    """
                    MATCH (p:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(d:CADocument {doc_type: $doc_type})
                    RETURN d.doc_id AS doc_id, d.drive_file_id AS drive_file_id,
                           d.filename AS filename, d.doc_type AS doc_type,
                           d.doc_number AS doc_number, d.phase AS phase,
                           d.date_submitted AS date_submitted, d.summary AS summary,
                           d.metadata_only AS metadata_only
                    ORDER BY d.date_submitted
                    """,
                    project_id=project_id,
                    doc_type=doc_type,
                )
            else:
                result = session.run(
                    """
                    MATCH (p:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(d:CADocument)
                    RETURN d.doc_id AS doc_id, d.drive_file_id AS drive_file_id,
                           d.filename AS filename, d.doc_type AS doc_type,
                           d.doc_number AS doc_number, d.phase AS phase,
                           d.date_submitted AS date_submitted, d.summary AS summary,
                           d.metadata_only AS metadata_only
                    ORDER BY d.date_submitted
                    """,
                    project_id=project_id,
                )
            return [record.data() for record in result]

    def search_project_documents(
        self,
        query: str,
        project_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Semantic search over CADocument nodes, optionally scoped to a project."""
        if not self._driver:
            return []
        embedding = engine.generate_embedding(query)
        with self._driver.session() as session:
            if project_id:
                result = session.run(
                    """
                    CALL db.index.vector.queryNodes('ca_document_embeddings', $top_k, $embedding)
                    YIELD node, score
                    WHERE score > 0.70
                    MATCH (p:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(node)
                    RETURN node.doc_id AS doc_id, node.filename AS filename,
                           node.doc_type AS doc_type, node.summary AS summary, score
                    ORDER BY score DESC
                    """,
                    top_k=top_k,
                    embedding=embedding,
                    project_id=project_id,
                )
            else:
                result = session.run(
                    """
                    CALL db.index.vector.queryNodes('ca_document_embeddings', $top_k, $embedding)
                    YIELD node, score
                    WHERE score > 0.70
                    RETURN node.doc_id AS doc_id, node.filename AS filename,
                           node.doc_type AS doc_type, node.summary AS summary, score
                    ORDER BY score DESC
                    """,
                    top_k=top_k,
                    embedding=embedding,
                )
            return [record.data() for record in result]


# Module-level singleton — imported by agents/kg/flaw_extractor.py as:
#   from knowledge_graph.client import kg_client
kg_client = KnowledgeGraphClient()
```

- [ ] **Step 1.4: Run the existing tests — verify all 3 pass**

```bash
python -m pytest tests/test_kg_client.py -v
```
Expected:
```
PASSED tests/test_kg_client.py::test_kg_client_init
PASSED tests/test_kg_client.py::test_kg_get_document_workflow
PASSED tests/test_kg_client.py::test_kg_search_spec_sections
```

- [ ] **Step 1.5: Write tests for the new project-layer methods**

Append to `tests/test_kg_client.py`:

```python
from unittest.mock import patch, MagicMock


# ---- upsert_project --------------------------------------------------------

@patch('os.environ.get')
def test_kg_upsert_project(mock_env, mock_driver):
    mock_env.side_effect = lambda k, default=None: "value" if k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] else default
    from src.knowledge_graph.client import KnowledgeGraphClient
    client = KnowledgeGraphClient()

    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    client.upsert_project({
        "project_id": "11900",
        "project_number": "11900",
        "name": "WHCCD - Instructional Center Ph. 1",
        "phase": "construction",
        "drive_root_folder_id": "abc123",
    })

    mock_session.run.assert_called_once()
    call_kwargs = mock_session.run.call_args
    assert "project_id" in call_kwargs.kwargs or "11900" in str(call_kwargs)


# ---- document_exists -------------------------------------------------------

@patch('os.environ.get')
def test_kg_document_exists_false(mock_env, mock_driver):
    mock_env.side_effect = lambda k, default=None: "value" if k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] else default
    from src.knowledge_graph.client import KnowledgeGraphClient
    client = KnowledgeGraphClient()

    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_record = MagicMock()
    mock_record.__getitem__ = lambda self, k: 0  # cnt = 0
    mock_session.run.return_value.single.return_value = mock_record

    result = client.document_exists("nonexistent-file-id")
    assert result is False


@patch('os.environ.get')
def test_kg_document_exists_true(mock_env, mock_driver):
    mock_env.side_effect = lambda k, default=None: "value" if k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] else default
    from src.knowledge_graph.client import KnowledgeGraphClient
    client = KnowledgeGraphClient()

    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_record = MagicMock()
    mock_record.__getitem__ = lambda self, k: 1  # cnt = 1
    mock_session.run.return_value.single.return_value = mock_record

    result = client.document_exists("existing-file-id")
    assert result is True


# ---- get_project_documents -------------------------------------------------

@patch('os.environ.get')
def test_kg_get_project_documents(mock_env, mock_driver):
    mock_env.side_effect = lambda k, default=None: "value" if k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] else default
    from src.knowledge_graph.client import KnowledgeGraphClient
    client = KnowledgeGraphClient()

    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    mock_record = MagicMock()
    mock_record.data.return_value = {
        "doc_id": "11900_RFI_001",
        "doc_type": "RFI",
        "filename": "RFI-001_Foundation_Query.pdf",
    }
    mock_session.run.return_value.__iter__ = lambda self: iter([mock_record])

    docs = client.get_project_documents("11900", doc_type="RFI")
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "RFI"


# ---- search_project_documents ----------------------------------------------

@patch('src.knowledge_graph.client.engine.generate_embedding')
@patch('os.environ.get')
def test_kg_search_project_documents(mock_env, mock_embed, mock_driver):
    mock_env.side_effect = lambda k, default=None: "value" if k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] else default
    from src.knowledge_graph.client import KnowledgeGraphClient
    client = KnowledgeGraphClient()

    mock_embed.return_value = [0.1] * 768

    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_record = MagicMock()
    mock_record.data.return_value = {"doc_id": "11900_RFI_001", "summary": "Query about foundations."}
    mock_session.run.return_value.__iter__ = lambda self: iter([mock_record])

    results = client.search_project_documents("foundation detail", project_id="11900", top_k=3)

    mock_embed.assert_called_with("foundation detail")
    assert len(results) == 1
    assert results[0]["doc_id"] == "11900_RFI_001"


# ---- no-op mode (no env vars) ----------------------------------------------

def test_kg_client_noop_without_env():
    """Client must not raise when NEO4J_* vars are absent — returns empty lists."""
    import importlib
    import sys

    # Remove cached modules so env is read fresh
    for mod in list(sys.modules.keys()):
        if "knowledge_graph" in mod:
            del sys.modules[mod]

    import os
    old = {k: os.environ.pop(k) for k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] if k in os.environ}
    try:
        from src.knowledge_graph.client import KnowledgeGraphClient
        client = KnowledgeGraphClient()
        assert client._driver is None
        assert client.get_document_workflow("RFI") == []
        assert client.get_project_documents("11900") == []
        assert client.document_exists("abc") is False
    finally:
        os.environ.update(old)
```

- [ ] **Step 1.6: Run new tests to verify all pass**

```bash
python -m pytest tests/test_kg_client.py -v
```
Expected: All tests PASS (including the 3 original + 6 new).

- [ ] **Step 1.7: Commit**

```bash
git add src/knowledge_graph/__init__.py src/knowledge_graph/client.py tests/test_kg_client.py
git commit -m "feat(kg): implement KnowledgeGraphClient with project-layer methods"
```

---

## Task 2: `scripts/setup_kg_schema.py` — Neo4j Constraints & Vector Indexes

**Files:**
- Create: `scripts/setup_kg_schema.py`

> **Context:** Neo4j Aura is already provisioned (`NEO4J_URI=neo4j+s://2d93324b.databases.neo4j.io`). Vector index syntax for Neo4j 5+ uses `CREATE VECTOR INDEX ... FOR (n:Label) ON (n.property)`. All Cypher statements use `IF NOT EXISTS` so the script is safely re-runnable.

- [ ] **Step 2.1: Write a failing smoke-test for the schema runner**

Add to a new file `tests/test_setup_kg_schema.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, call


def test_setup_schema_runs_all_statements():
    """setup_kg_schema must execute both constraint and vector index statements."""
    with patch('neo4j.GraphDatabase.driver') as mock_gdb:
        driver = MagicMock()
        mock_gdb.return_value = driver
        session = MagicMock()
        driver.session.return_value.__enter__.return_value = session

        with patch.dict('os.environ', {
            'NEO4J_URI': 'neo4j+s://test',
            'NEO4J_USERNAME': 'neo4j',
            'NEO4J_PASSWORD': 'password',
        }):
            import importlib, sys
            for mod in list(sys.modules.keys()):
                if 'setup_kg_schema' in mod:
                    del sys.modules[mod]

            import importlib.util, os
            spec = importlib.util.spec_from_file_location(
                "setup_kg_schema",
                os.path.join(os.path.dirname(__file__), '..', 'scripts', 'setup_kg_schema.py')
            )
            mod = importlib.util.module_from_spec(spec)

            # Intercept main() call
            with patch.object(mod, '__name__', 'not_main'):
                spec.loader.exec_module(mod)

            mod.apply_schema(driver)

        # Should have called session.run many times (constraints + indexes)
        assert session.run.call_count >= 12, (
            f"Expected ≥12 Cypher statements, got {session.run.call_count}"
        )
```

```bash
python -m pytest tests/test_setup_kg_schema.py -v
```
Expected: FAIL — `ModuleNotFoundError` or `AttributeError: module has no attribute 'apply_schema'`

- [ ] **Step 2.2: Create `scripts/setup_kg_schema.py`**

```python
"""
Apply Neo4j constraints and vector indexes for TeterAI_CA Knowledge Graph.
Safe to re-run — all statements use IF NOT EXISTS.

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
    "CREATE CONSTRAINT spec_section_unique IF NOT EXISTS FOR (n:SpecSection) REQUIRE n.section_number IS UNIQUE",
    "CREATE CONSTRAINT contract_clause_unique IF NOT EXISTS FOR (n:ContractClause) REQUIRE n.clause_id IS UNIQUE",
    "CREATE CONSTRAINT project_unique IF NOT EXISTS FOR (n:Project) REQUIRE n.project_id IS UNIQUE",
    "CREATE CONSTRAINT ca_document_unique IF NOT EXISTS FOR (n:CADocument) REQUIRE n.drive_file_id IS UNIQUE",
    "CREATE CONSTRAINT party_unique IF NOT EXISTS FOR (n:Party) REQUIRE n.party_id IS UNIQUE",
    "CREATE CONSTRAINT correction_event_unique IF NOT EXISTS FOR (n:CorrectionEvent) REQUIRE n.event_id IS UNIQUE",
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
]

ALL_STATEMENTS = CONSTRAINTS + VECTOR_INDEXES


def apply_schema(driver: neo4j.Driver) -> None:
    """Execute every DDL statement. Safe to call multiple times."""
    with driver.session() as session:
        for stmt in ALL_STATEMENTS:
            session.run(stmt)
            print(f"  ✓ {stmt.split('IF NOT EXISTS')[0].strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Neo4j KG schema constraints and vector indexes.")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing")
    args = parser.parse_args()

    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")

    if not all([uri, username, password]):
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set.")
        sys.exit(1)

    if args.dry_run:
        print(f"=== DRY RUN — {len(ALL_STATEMENTS)} statements would be applied ===")
        for stmt in ALL_STATEMENTS:
            print(f"  → {stmt.split(chr(10))[0].strip()}")
        return

    print(f"Applying {len(ALL_STATEMENTS)} schema statements to {uri} …")
    driver = neo4j.GraphDatabase.driver(uri, auth=(username, password))
    try:
        apply_schema(driver)
        print(f"\nDone. {len(CONSTRAINTS)} constraints + {len(VECTOR_INDEXES)} vector indexes applied.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2.3: Run the smoke-test — verify it passes**

```bash
python -m pytest tests/test_setup_kg_schema.py -v
```
Expected: PASS

- [ ] **Step 2.4: Commit**

```bash
git add scripts/setup_kg_schema.py tests/test_setup_kg_schema.py
git commit -m "feat(kg): add schema setup script with constraints and vector indexes"
```

---

## Task 3: `scripts/seed_kg_baseline.py` — Tier 1, 2, 4 Seed Data

**Files:**
- Create: `scripts/seed_kg_baseline.py`

> **Context:** All writes use MERGE on the node's ID property — fully idempotent. Embedding generation is called for SpecSection nodes (content_summary field) and PlaybookRule nodes (description field). The `AIEngine` singleton `engine` is imported from `ai_engine.engine`.

- [ ] **Step 3.1: Create `scripts/seed_kg_baseline.py`**

```python
"""
Seed the Neo4j Knowledge Graph with Tier 1 (Agent Playbooks),
Tier 2 (Workflow Process), and Tier 4 (Industry Knowledge) baseline data.

Usage:
    python scripts/seed_kg_baseline.py              # seed everything
    python scripts/seed_kg_baseline.py --dry-run    # preview counts only
    python scripts/seed_kg_baseline.py --tier 2     # seed only Tier 2
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import neo4j
from ai_engine.engine import engine as ai_engine

# ===========================================================================
# TIER 2 — Workflow Process
# ===========================================================================

DOCUMENT_TYPES = [
    {"type_id": "RFI",            "name": "Request for Information",              "phase": "construction", "numbering_prefix": "RFI-",     "response_deadline_days": 10},
    {"type_id": "SUBMITTAL",      "name": "Submittal",                            "phase": "construction", "numbering_prefix": "SUB-",     "response_deadline_days": 14},
    {"type_id": "SUB_REQ",        "name": "Substitution Request",                 "phase": "construction", "numbering_prefix": "SUB-REQ-", "response_deadline_days": 10},
    {"type_id": "PCO_COR",        "name": "Proposed Change Order / COR",          "phase": "construction", "numbering_prefix": "PCO-",     "response_deadline_days": 21},
    {"type_id": "BULLETIN",       "name": "Bulletin",                             "phase": "construction", "numbering_prefix": "BUL-",     "response_deadline_days": 0},
    {"type_id": "CHANGE_ORDER",   "name": "Change Order",                         "phase": "construction", "numbering_prefix": "CO-",      "response_deadline_days": 14},
    {"type_id": "PAY_APP",        "name": "Pay Application",                      "phase": "construction", "numbering_prefix": "PAY-",     "response_deadline_days": 7},
    {"type_id": "MEETING_MINUTES","name": "Meeting Minutes",                      "phase": "construction", "numbering_prefix": "MM-",      "response_deadline_days": 3},
    {"type_id": "PB_RFI",         "name": "Pre-Bid Request for Information",      "phase": "bid",          "numbering_prefix": "PB-RFI-",  "response_deadline_days": 5},
    {"type_id": "ADDENDUM",       "name": "Addendum",                             "phase": "bid",          "numbering_prefix": "ADD-",     "response_deadline_days": 0},
]

# Full 7-step RFI workflow
RFI_WORKFLOW_STEPS = [
    {"step_id": "RFI-WF-01", "name": "Receipt",           "description": "Email received and parsed by Gmail Integration. Attachments saved to Holding Folder.",  "responsible_party": "ca_agent",  "sequence": 1},
    {"step_id": "RFI-WF-02", "name": "Acknowledge",       "description": "Send acknowledgment to contractor within 24 hours confirming receipt of RFI.",           "responsible_party": "ca_agent",  "sequence": 2},
    {"step_id": "RFI-WF-03", "name": "Route to Architect","description": "Forward to responsible architect of record for technical review.",                        "responsible_party": "ca_staff",  "sequence": 3},
    {"step_id": "RFI-WF-04", "name": "Draft Response",    "description": "RFI Agent drafts a response referencing contract drawings and specifications.",           "responsible_party": "ca_agent",  "sequence": 4},
    {"step_id": "RFI-WF-05", "name": "CA Review",         "description": "CA staff reviews and approves or revises the drafted response before issue.",             "responsible_party": "ca_staff",  "sequence": 5},
    {"step_id": "RFI-WF-06", "name": "Issue Response",    "description": "Approved response sent to contractor via email; document filed in project Drive folder.", "responsible_party": "ca_agent",  "sequence": 6},
    {"step_id": "RFI-WF-07", "name": "Close",             "description": "RFI marked closed in system. Final document archived in 02 - Construction/RFIs/.",        "responsible_party": "ca_agent",  "sequence": 7},
]

# Single placeholder step for all other document types
OTHER_DOC_TYPE_STEP_TEMPLATE = {
    "name": "Human Processing",
    "description": "Document type handled manually by CA staff in Phase 0. Agent automation planned for Phase 1.",
    "responsible_party": "ca_staff",
    "sequence": 1,
}

# ===========================================================================
# TIER 4 — Industry Knowledge
# ===========================================================================

CSI_DIVISIONS = [
    {"csi_division": "01", "section_number": "01 00 00", "title": "General Requirements",        "content_summary": "Project management, administrative procedures, temporary facilities, quality requirements, and project closeout.", "keywords": ["general requirements", "administrative", "project management", "closeout", "quality"]},
    {"csi_division": "02", "section_number": "02 00 00", "title": "Existing Conditions",         "content_summary": "Subsurface investigation, hazardous material assessment, existing structure demolition, and utility identification.", "keywords": ["existing conditions", "subsurface", "demolition", "hazardous materials", "utilities"]},
    {"csi_division": "03", "section_number": "03 00 00", "title": "Concrete",                    "content_summary": "Cast-in-place concrete, precast concrete, grout, and concrete restoration. Includes mix design, reinforcement, and formwork.", "keywords": ["concrete", "reinforcement", "rebar", "formwork", "precast", "slab", "footing"]},
    {"csi_division": "04", "section_number": "04 00 00", "title": "Masonry",                     "content_summary": "Unit masonry, stone assemblies, and masonry restoration. Includes CMU, brick, mortar, and grout specifications.", "keywords": ["masonry", "CMU", "brick", "mortar", "block", "stone"]},
    {"csi_division": "05", "section_number": "05 00 00", "title": "Metals",                      "content_summary": "Structural steel, steel joists, metal decking, cold-formed metal framing, and miscellaneous metals.", "keywords": ["steel", "structural steel", "metal decking", "joists", "fabrication", "welding"]},
    {"csi_division": "06", "section_number": "06 00 00", "title": "Wood, Plastics, and Composites", "content_summary": "Rough carpentry, finish carpentry, architectural woodwork, structural panels, and composite materials.", "keywords": ["wood", "carpentry", "lumber", "plywood", "millwork", "cabinets"]},
    {"csi_division": "07", "section_number": "07 00 00", "title": "Thermal and Moisture Protection", "content_summary": "Waterproofing, dampproofing, insulation, roofing, flashing, sheet metal, and joint sealants.", "keywords": ["waterproofing", "roofing", "insulation", "flashing", "sealant", "vapor barrier"]},
    {"csi_division": "08", "section_number": "08 00 00", "title": "Openings",                    "content_summary": "Doors, frames, hardware, windows, curtain walls, glazing, and storefronts.", "keywords": ["doors", "windows", "hardware", "glazing", "curtain wall", "storefront", "frames"]},
    {"csi_division": "09", "section_number": "09 00 00", "title": "Finishes",                    "content_summary": "Plaster, gypsum board, tiling, flooring, acoustical ceilings, painting, and wall coverings.", "keywords": ["finishes", "drywall", "gypsum", "tile", "flooring", "paint", "ceiling", "acoustical"]},
    {"csi_division": "10", "section_number": "10 00 00", "title": "Specialties",                 "content_summary": "Visual display boards, compartments, lockers, fire protection specialties, and signage.", "keywords": ["specialties", "signage", "lockers", "toilet partitions", "fire extinguisher"]},
    {"csi_division": "11", "section_number": "11 00 00", "title": "Equipment",                   "content_summary": "Foodservice equipment, laboratory equipment, athletic equipment, and other owner-furnished items.", "keywords": ["equipment", "foodservice", "laboratory", "athletic"]},
    {"csi_division": "12", "section_number": "12 00 00", "title": "Furnishings",                 "content_summary": "Window treatments, furniture, and furnishing accessories.", "keywords": ["furnishings", "furniture", "window treatment", "blinds"]},
    {"csi_division": "13", "section_number": "13 00 00", "title": "Special Construction",        "content_summary": "Pre-engineered structures, swimming pools, aquariums, and special purpose rooms.", "keywords": ["special construction", "pre-engineered", "modular"]},
    {"csi_division": "14", "section_number": "14 00 00", "title": "Conveying Equipment",         "content_summary": "Elevators, escalators, moving walks, and conveying equipment.", "keywords": ["elevator", "escalator", "conveying", "lift"]},
    {"csi_division": "21", "section_number": "21 00 00", "title": "Fire Suppression",            "content_summary": "Fire suppression piping, sprinkler systems, and fire-extinguishing systems.", "keywords": ["fire suppression", "sprinkler", "fire protection"]},
    {"csi_division": "22", "section_number": "22 00 00", "title": "Plumbing",                    "content_summary": "Plumbing piping, plumbing equipment, plumbing fixtures, and domestic water supply.", "keywords": ["plumbing", "piping", "fixtures", "domestic water", "drain"]},
    {"csi_division": "23", "section_number": "23 00 00", "title": "HVAC",                        "content_summary": "Heating, ventilating, and air conditioning systems including ductwork, equipment, and controls.", "keywords": ["HVAC", "mechanical", "ductwork", "air handling", "chiller", "boiler"]},
    {"csi_division": "26", "section_number": "26 00 00", "title": "Electrical",                  "content_summary": "Medium and low voltage electrical distribution, lighting, and branch circuit wiring.", "keywords": ["electrical", "lighting", "wiring", "panel", "conduit", "power"]},
    {"csi_division": "27", "section_number": "27 00 00", "title": "Communications",              "content_summary": "Structured cabling, data networks, audio-visual systems, and communications infrastructure.", "keywords": ["communications", "data", "network", "AV", "cabling", "low voltage"]},
    {"csi_division": "28", "section_number": "28 00 00", "title": "Electronic Safety and Security", "content_summary": "Access control, video surveillance, intrusion detection, and fire alarm systems.", "keywords": ["security", "access control", "cameras", "fire alarm", "intrusion"]},
]

AIA_CLAUSES = [
    {
        "clause_id": "AIA-A201-3.2",
        "standard": "AIA-A201-2017",
        "clause_number": "3.2",
        "title": "Review of Contract Documents and Field Conditions by Contractor",
        "text": (
            "The Contractor shall carefully study and compare the Contract Documents with each other "
            "and with information furnished by the Owner pursuant to Section 2.3.3 and shall at once "
            "report to the Architect errors, inconsistencies or omissions discovered. The Contractor "
            "shall also carefully study and compare the Contract Documents with each other and shall "
            "promptly report to the Architect any errors, inconsistencies, or omissions in the Contract "
            "Documents discovered during this review. If the Contractor performs any construction "
            "activity knowing it involves a recognized error, inconsistency, or omission in the Contract "
            "Documents without such notice to the Architect, the Contractor shall assume appropriate "
            "responsibility for such performance and shall bear an appropriate amount of the attributable "
            "costs for correction."
        ),
    },
    {
        "clause_id": "AIA-A201-15.1",
        "standard": "AIA-A201-2017",
        "clause_number": "15.1",
        "title": "Claims",
        "text": (
            "A Claim is a demand or assertion by one of the parties seeking, as a matter of right, "
            "payment of money, a change in the Contract Time, or other relief with respect to the "
            "terms of the Contract. The term 'Claim' also includes other disputes and matters in "
            "question between the Owner and Contractor arising out of or relating to the Contract. "
            "The responsibility to substantiate Claims shall rest with the party making the Claim. "
            "Claims must be initiated by written notice to the other party and to the Initial "
            "Decision Maker within 21 days after occurrence of the event giving rise to such Claim "
            "or within 21 days after the claimant first recognizes the condition giving rise to the Claim."
        ),
    },
    {
        "clause_id": "AIA-A201-9.3",
        "standard": "AIA-A201-2017",
        "clause_number": "9.3",
        "title": "Applications for Payment",
        "text": (
            "At least ten days before the date established for each progress payment, the Contractor "
            "shall submit to the Architect an itemized Application for Payment prepared in accordance "
            "with the schedule of values, if required under Section 9.2, for completed portions of the "
            "Work. The application shall be notarized, if required, and supported by all data "
            "substantiating the Contractor's right to payment that the Owner or Architect require, "
            "such as copies of requisitions, and releases and waivers of liens from subcontractors "
            "and suppliers, and shall reflect retainage if provided for in the Contract Documents."
        ),
    },
]

# ===========================================================================
# TIER 1 — Agent Playbooks
# ===========================================================================

AGENTS = [
    {"agent_id": "AGENT-DISPATCH-001", "name": "Dispatcher Agent", "version": "1.0.0", "phase": "phase-0"},
    {"agent_id": "AGENT-RFI-001",      "name": "RFI Agent",        "version": "1.0.0", "phase": "phase-0"},
]

DISPATCHER_RULES = [
    {
        "rule_id": "DISPATCH-RULE-001",
        "description": "Auto-route task when all four classification dimensions meet the confidence threshold",
        "condition": "All of project_id, phase, document_type, urgency classification confidence >= 0.80",
        "action": "Assign task to specialist agent per document type routing table",
        "confidence_threshold": 0.80,
        "priority": 1,
    },
    {
        "rule_id": "DISPATCH-RULE-002",
        "description": "Escalate to human review when any classification dimension falls below threshold",
        "condition": "Any one of project_id, phase, document_type, or urgency confidence < 0.80",
        "action": "Set task status to ESCALATED_TO_HUMAN with best-guess classification and reasoning notes attached",
        "confidence_threshold": 0.80,
        "priority": 2,
    },
    {
        "rule_id": "DISPATCH-RULE-003",
        "description": "Route RFI construction documents to AGENT-RFI-001 in Phase 0",
        "condition": "document_type=RFI AND phase=construction AND all dimensions confidence >= 0.80",
        "action": "Assign to AGENT-RFI-001",
        "confidence_threshold": 0.80,
        "priority": 3,
    },
    {
        "rule_id": "DISPATCH-RULE-004",
        "description": "Escalate all non-RFI construction documents to human in Phase 0",
        "condition": "document_type NOT IN [RFI] AND phase=construction",
        "action": "Set task status to ESCALATED_TO_HUMAN; Phase 0 only handles RFI automatically",
        "confidence_threshold": 0.0,
        "priority": 4,
    },
    {
        "rule_id": "DISPATCH-RULE-005",
        "description": "Escalate when project cannot be identified from email",
        "condition": "project_id classified as UNKNOWN (confidence=0.0)",
        "action": "Set task status to ESCALATED_TO_HUMAN; project not found in registry",
        "confidence_threshold": 0.0,
        "priority": 5,
    },
]

RFI_RULES = [
    {
        "rule_id": "RFI-RULE-001",
        "description": "Extract structured RFI fields from email subject, body, and attachments",
        "condition": "Task assigned to AGENT-RFI-001 with status ASSIGNED_TO_AGENT",
        "action": "Run RFIExtractor on full email body (first 3000 chars) and attachment filenames",
        "confidence_threshold": 0.0,
        "priority": 1,
    },
    {
        "rule_id": "RFI-RULE-002",
        "description": "Draft RFI response referencing applicable contract documents and spec sections",
        "condition": "RFI extraction complete and question field is non-empty",
        "action": "Run RFIDrafter using extracted question, spec section references, and KG SpecSection lookup",
        "confidence_threshold": 0.0,
        "priority": 2,
    },
    {
        "rule_id": "RFI-RULE-003",
        "description": "Annotate draft when referenced spec section is not found in knowledge graph",
        "condition": "referenced_spec_sections contains a section number with no matching SpecSection node in KG",
        "action": "Include note in draft: 'Spec section X not found in KG — CA staff should verify manually'",
        "confidence_threshold": 0.0,
        "priority": 3,
    },
    {
        "rule_id": "RFI-RULE-004",
        "description": "Escalate if AI draft confidence is below threshold",
        "condition": "Draft response confidence score < 0.70 (e.g. question is ambiguous or references unknown drawings)",
        "action": "Attach low-confidence flag and escalation note; set task to ESCALATED_TO_HUMAN",
        "confidence_threshold": 0.70,
        "priority": 4,
    },
]

DISPATCHER_ESCALATION = {
    "criteria_id": "DISPATCH-ESC-001",
    "trigger": "Any classification dimension confidence < 0.80 or project_id = UNKNOWN",
    "escalation_type": "human_queue",
}

RFI_ESCALATION = {
    "criteria_id": "RFI-ESC-001",
    "trigger": "Draft response confidence < 0.70 or question field empty after extraction",
    "escalation_type": "human_queue",
}


# ===========================================================================
# Seeding functions
# ===========================================================================

def _merge_node(session, label: str, id_key: str, data: dict) -> None:
    props_set = ", ".join(f"n.{k} = ${k}" for k in data if k != id_key)
    session.run(
        f"MERGE (n:{label} {{{id_key}: ${id_key}}}) SET {props_set}",
        **data,
    )


def seed_tier2(driver: neo4j.Driver, embed: bool = True) -> dict:
    counts = {"document_types": 0, "workflow_steps": 0, "workflow_edges": 0}
    with driver.session() as session:
        # DocumentType nodes
        for dt in DOCUMENT_TYPES:
            _merge_node(session, "DocumentType", "type_id", dt)
            counts["document_types"] += 1

        # RFI full workflow
        prev_step_id = None
        for step in RFI_WORKFLOW_STEPS:
            _merge_node(session, "WorkflowStep", "step_id", step)
            session.run(
                "MATCH (dt:DocumentType {type_id: 'RFI'}) "
                "MATCH (ws:WorkflowStep {step_id: $step_id}) "
                "MERGE (dt)-[:FOLLOWS_WORKFLOW]->(ws)",
                step_id=step["step_id"],
            )
            if prev_step_id:
                session.run(
                    "MATCH (a:WorkflowStep {step_id: $a}) "
                    "MATCH (b:WorkflowStep {step_id: $b}) "
                    "MERGE (a)-[:NEXT_STEP]->(b)",
                    a=prev_step_id, b=step["step_id"],
                )
                counts["workflow_edges"] += 1
            prev_step_id = step["step_id"]
            counts["workflow_steps"] += 1

        # Placeholder single-step for all other doc types
        for dt in DOCUMENT_TYPES:
            if dt["type_id"] == "RFI":
                continue
            step_id = f"{dt['type_id']}-WF-01"
            step_data = {**OTHER_DOC_TYPE_STEP_TEMPLATE, "step_id": step_id}
            _merge_node(session, "WorkflowStep", "step_id", step_data)
            session.run(
                "MATCH (d:DocumentType {type_id: $type_id}) "
                "MATCH (ws:WorkflowStep {step_id: $step_id}) "
                "MERGE (d)-[:FOLLOWS_WORKFLOW]->(ws)",
                type_id=dt["type_id"], step_id=step_id,
            )
            counts["workflow_steps"] += 1

    return counts


def seed_tier4(driver: neo4j.Driver, embed: bool = True) -> dict:
    counts = {"spec_sections": 0, "contract_clauses": 0}
    with driver.session() as session:
        for div in CSI_DIVISIONS:
            data = {**div}
            if embed:
                text = f"{div['title']}: {div['content_summary']}"
                try:
                    emb = ai_engine.generate_embedding(text)
                    data["embedding"] = emb
                    data["embedding_model"] = "text-embedding"
                except Exception as e:
                    print(f"    ⚠ Embedding failed for {div['section_number']}: {e}")
            _merge_node(session, "SpecSection", "section_number", data)
            counts["spec_sections"] += 1

        for clause in AIA_CLAUSES:
            data = {**clause}
            if embed:
                try:
                    emb = ai_engine.generate_embedding(f"{clause['title']}: {clause['text'][:500]}")
                    data["embedding"] = emb
                    data["embedding_model"] = "text-embedding"
                except Exception as e:
                    print(f"    ⚠ Embedding failed for {clause['clause_id']}: {e}")
            _merge_node(session, "ContractClause", "clause_id", data)
            counts["contract_clauses"] += 1

    return counts


def seed_tier1(driver: neo4j.Driver, embed: bool = True) -> dict:
    counts = {"agents": 0, "rules": 0, "escalation_criteria": 0}
    with driver.session() as session:
        for agent in AGENTS:
            _merge_node(session, "Agent", "agent_id", agent)
            counts["agents"] += 1

        all_rules = [
            ("AGENT-DISPATCH-001", DISPATCHER_RULES),
            ("AGENT-RFI-001", RFI_RULES),
        ]
        for agent_id, rules in all_rules:
            for rule in rules:
                data = {**rule}
                if embed:
                    try:
                        emb = ai_engine.generate_embedding(rule["description"])
                        data["embedding"] = emb
                        data["embedding_model"] = "text-embedding"
                    except Exception as e:
                        print(f"    ⚠ Embedding failed for {rule['rule_id']}: {e}")
                _merge_node(session, "PlaybookRule", "rule_id", data)
                session.run(
                    "MATCH (a:Agent {agent_id: $agent_id}) "
                    "MATCH (r:PlaybookRule {rule_id: $rule_id}) "
                    "MERGE (a)-[:HAS_RULE]->(r)",
                    agent_id=agent_id, rule_id=rule["rule_id"],
                )
                counts["rules"] += 1

        for esc in [DISPATCHER_ESCALATION, RFI_ESCALATION]:
            _merge_node(session, "EscalationCriteria", "criteria_id", esc)
        session.run(
            "MATCH (a:Agent {agent_id: 'AGENT-DISPATCH-001'}) "
            "MATCH (e:EscalationCriteria {criteria_id: 'DISPATCH-ESC-001'}) "
            "MERGE (a)-[:ESCALATES_ON]->(e)"
        )
        session.run(
            "MATCH (a:Agent {agent_id: 'AGENT-RFI-001'}) "
            "MATCH (e:EscalationCriteria {criteria_id: 'RFI-ESC-001'}) "
            "MERGE (a)-[:ESCALATES_ON]->(e)"
        )
        counts["escalation_criteria"] = 2

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed KG baseline data.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tier", choices=["1", "2", "4"], help="Seed only one tier")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding generation (faster, for testing)")
    args = parser.parse_args()

    uri      = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")

    if not all([uri, username, password]):
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set.")
        sys.exit(1)

    embed = not args.no_embed

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Tier 2: {len(DOCUMENT_TYPES)} DocumentType + {len(RFI_WORKFLOW_STEPS) + len(DOCUMENT_TYPES) - 1} WorkflowStep nodes")
        print(f"  Tier 4: {len(CSI_DIVISIONS)} SpecSection + {len(AIA_CLAUSES)} ContractClause nodes")
        print(f"  Tier 1: {len(AGENTS)} Agent + {len(DISPATCHER_RULES) + len(RFI_RULES)} PlaybookRule + 2 EscalationCriteria nodes")
        return

    driver = neo4j.GraphDatabase.driver(uri, auth=(username, password))
    try:
        if not args.tier or args.tier == "2":
            print("Seeding Tier 2 (Workflow Process)…")
            c = seed_tier2(driver, embed=embed)
            print(f"  ✓ {c['document_types']} DocumentType, {c['workflow_steps']} WorkflowStep, {c['workflow_edges']} NEXT_STEP edges")

        if not args.tier or args.tier == "4":
            print("Seeding Tier 4 (Industry Knowledge)…")
            c = seed_tier4(driver, embed=embed)
            print(f"  ✓ {c['spec_sections']} SpecSection, {c['contract_clauses']} ContractClause")

        if not args.tier or args.tier == "1":
            print("Seeding Tier 1 (Agent Playbooks)…")
            c = seed_tier1(driver, embed=embed)
            print(f"  ✓ {c['agents']} Agent, {c['rules']} PlaybookRule, {c['escalation_criteria']} EscalationCriteria")

        print("\nDone. Verify at: https://console.neo4j.io")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3.2: Write a unit test for the seed functions**

Create `tests/test_seed_kg_baseline.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, call
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


def _make_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = False
    return driver, session


@patch('ai_engine.engine.engine.generate_embedding', return_value=[0.1] * 768)
def test_seed_tier2_creates_document_types(mock_embed):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "seed_kg_baseline",
        os.path.join(os.path.dirname(__file__), '..', 'scripts', 'seed_kg_baseline.py')
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    driver, session = _make_driver()
    counts = mod.seed_tier2(driver, embed=False)

    assert counts["document_types"] == 10
    assert counts["workflow_steps"] > 0
    assert session.run.call_count > 0


@patch('ai_engine.engine.engine.generate_embedding', return_value=[0.1] * 768)
def test_seed_tier4_creates_csi_and_aia(mock_embed):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "seed_kg_baseline",
        os.path.join(os.path.dirname(__file__), '..', 'scripts', 'seed_kg_baseline.py')
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    driver, session = _make_driver()
    counts = mod.seed_tier4(driver, embed=False)

    assert counts["spec_sections"] == len(mod.CSI_DIVISIONS)
    assert counts["contract_clauses"] == 3


@patch('ai_engine.engine.engine.generate_embedding', return_value=[0.1] * 768)
def test_seed_tier1_creates_agents_and_rules(mock_embed):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "seed_kg_baseline",
        os.path.join(os.path.dirname(__file__), '..', 'scripts', 'seed_kg_baseline.py')
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    driver, session = _make_driver()
    counts = mod.seed_tier1(driver, embed=False)

    assert counts["agents"] == 2
    assert counts["rules"] == len(mod.DISPATCHER_RULES) + len(mod.RFI_RULES)
    assert counts["escalation_criteria"] == 2
```

- [ ] **Step 3.3: Run tests — verify they pass**

```bash
python -m pytest tests/test_seed_kg_baseline.py -v
```
Expected: 3 PASS

- [ ] **Step 3.4: Commit**

```bash
git add scripts/seed_kg_baseline.py tests/test_seed_kg_baseline.py
git commit -m "feat(kg): add baseline seed script for Tier 1/2/4 data"
```

---

## Task 4: `src/knowledge_graph/ingestion.py` — Drive-to-KG Ingester

**Files:**
- Create: `src/knowledge_graph/ingestion.py`
- Create: `tests/test_kg_ingestion.py`

> **Context:** `DriveService` (already implemented) provides `list_folder_files(folder_id)`, `download_file(file_id)` → `(bytes, mime_type)`, and `get_folder_id(project_id, folder_path)`. Google Docs have `mimeType = 'application/vnd.google-apps.document'` and must be exported via `drive_service.service.files().export(fileId=..., mimeType='text/plain').execute()`. PDFs use `pypdf`. DOCX uses `python-docx`. Files in `04 - Agent Workspace/` are always skipped.

- [ ] **Step 4.1: Write failing tests first**

Create `tests/test_kg_ingestion.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_kg_client():
    client = MagicMock()
    client.document_exists.return_value = False
    return client


def _make_drive_service(files=None, folder_map=None):
    drive = MagicMock()
    drive.list_folder_files.return_value = files or []
    drive.get_folder_id.side_effect = lambda pid, path: (folder_map or {}).get(path)
    drive.download_file.return_value = (b"", "application/octet-stream")
    return drive


def _make_ai_engine():
    ai = MagicMock()
    ai.generate_response.return_value.content = (
        '{"doc_number": "RFI-001", "contractor_name": "Turner Construction", '
        '"date_submitted": "2026-01-15", "date_responded": null, '
        '"summary": "Contractor queries concrete mix design for footing F-1.", '
        '"spec_sections": ["03 30 00"], '
        '"parties": [{"name": "Turner Construction", "type": "contractor"}]}'
    )
    ai.generate_embedding.return_value = [0.1] * 768
    return ai


# ---------------------------------------------------------------------------
# infer_doc_type
# ---------------------------------------------------------------------------

def test_infer_doc_type_rfi():
    from knowledge_graph.ingestion import infer_doc_type
    assert infer_doc_type("02 - Construction/RFIs") == "RFI"


def test_infer_doc_type_submittal():
    from knowledge_graph.ingestion import infer_doc_type
    assert infer_doc_type("02 - Construction/Submittals") == "SUBMITTAL"


def test_infer_doc_type_unknown():
    from knowledge_graph.ingestion import infer_doc_type
    assert infer_doc_type("02 - Construction/Punchlist") == "UNKNOWN"


def test_infer_doc_type_bid_rfi():
    from knowledge_graph.ingestion import infer_doc_type
    assert infer_doc_type("01 - Bid Phase/PB-RFIs") == "PB_RFI"


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------

def test_extract_text_from_plain_text():
    from knowledge_graph.ingestion import extract_text
    content, metadata_only = extract_text(b"Hello world", "text/plain")
    assert "Hello world" in content
    assert metadata_only is False


def test_extract_text_unknown_type_returns_metadata_only():
    from knowledge_graph.ingestion import extract_text
    content, metadata_only = extract_text(b"\x00\x01\x02", "image/jpeg")
    assert metadata_only is True


def test_extract_text_pdf_too_short_returns_metadata_only():
    """A PDF that yields < 50 chars of text triggers metadata_only=True."""
    import io
    import pypdf
    from knowledge_graph.ingestion import extract_text

    # Build a minimal valid PDF with no extractable text
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    content, metadata_only = extract_text(pdf_bytes, "application/pdf")
    assert metadata_only is True


def test_extract_text_docx():
    """DOCX extraction returns text content and metadata_only=False."""
    import io
    from docx import Document as DocxDocument
    from knowledge_graph.ingestion import extract_text

    doc = DocxDocument()
    doc.add_paragraph("This is a test paragraph from a DOCX file.")
    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    content, metadata_only = extract_text(
        docx_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "test paragraph" in content
    assert metadata_only is False


# ---------------------------------------------------------------------------
# DriveToKGIngester.ingest_project
# ---------------------------------------------------------------------------

@patch('knowledge_graph.ingestion.KnowledgeGraphClient')
@patch('knowledge_graph.ingestion.DriveService')
@patch('knowledge_graph.ingestion.engine')
def test_ingest_project_skips_existing_doc(mock_engine, mock_drive_cls, mock_kg_cls):
    """If document_exists returns True the file is silently skipped."""
    from knowledge_graph.ingestion import DriveToKGIngester

    kg = _make_kg_client()
    kg.document_exists.return_value = True  # already in graph
    mock_kg_cls.return_value = kg

    drive = _make_drive_service(
        files=[{"id": "file-abc", "name": "RFI-001.pdf", "mimeType": "application/pdf"}],
        folder_map={"02 - Construction/RFIs": "folder-rfi-id"},
    )
    mock_drive_cls.return_value = drive

    ingester = DriveToKGIngester()
    result = ingester.ingest_project("11900", folder_map={"02 - Construction/RFIs": "folder-rfi-id"})

    kg.upsert_document.assert_not_called()
    assert result["skipped"] == 1


@patch('knowledge_graph.ingestion.KnowledgeGraphClient')
@patch('knowledge_graph.ingestion.DriveService')
@patch('knowledge_graph.ingestion.engine')
def test_ingest_project_writes_new_doc(mock_engine, mock_drive_cls, mock_kg_cls):
    """A new PDF file with extractable text is written to the graph."""
    import io, pypdf
    from knowledge_graph.ingestion import DriveToKGIngester

    # Build a PDF with actual text
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    # pypdf blank pages have no text; we'll patch extract_text instead
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    kg = _make_kg_client()
    mock_kg_cls.return_value = kg

    drive = _make_drive_service(
        files=[{"id": "file-xyz", "name": "RFI-001.pdf", "mimeType": "application/pdf"}],
        folder_map={"02 - Construction/RFIs": "folder-rfi-id"},
    )
    drive.download_file.return_value = (pdf_bytes, "application/pdf")
    mock_drive_cls.return_value = drive

    mock_engine.generate_response.return_value.content = (
        '{"doc_number": "RFI-001", "contractor_name": "ACME Corp", '
        '"date_submitted": "2026-01-10", "date_responded": null, '
        '"summary": "Query about rebar spacing in footing.", '
        '"spec_sections": ["03 30 00"], '
        '"parties": [{"name": "ACME Corp", "type": "contractor"}]}'
    )
    mock_engine.generate_embedding.return_value = [0.1] * 768

    with patch('knowledge_graph.ingestion.extract_text', return_value=("Some RFI text content here for testing.", False)):
        ingester = DriveToKGIngester()
        result = ingester.ingest_project("11900", folder_map={"02 - Construction/RFIs": "folder-rfi-id"})

    kg.upsert_document.assert_called_once()
    assert result["written"] == 1
    assert result["errors"] == 0


@patch('knowledge_graph.ingestion.KnowledgeGraphClient')
@patch('knowledge_graph.ingestion.DriveService')
@patch('knowledge_graph.ingestion.engine')
def test_ingest_project_handles_ai_parse_error(mock_engine, mock_drive_cls, mock_kg_cls):
    """If AI returns invalid JSON, document is still written as metadata_only."""
    from knowledge_graph.ingestion import DriveToKGIngester

    kg = _make_kg_client()
    mock_kg_cls.return_value = kg

    drive = _make_drive_service(
        files=[{"id": "file-err", "name": "RFI-002.pdf", "mimeType": "application/pdf"}],
        folder_map={"02 - Construction/RFIs": "folder-rfi-id"},
    )
    drive.download_file.return_value = (b"pdf bytes", "application/pdf")
    mock_drive_cls.return_value = drive

    mock_engine.generate_response.return_value.content = "NOT VALID JSON {{{"
    mock_engine.generate_embedding.return_value = [0.1] * 768

    with patch('knowledge_graph.ingestion.extract_text', return_value=("Some long enough text string here that is definitely longer than fifty chars.", False)):
        ingester = DriveToKGIngester()
        result = ingester.ingest_project("11900", folder_map={"02 - Construction/RFIs": "folder-rfi-id"})

    # Still written, but as metadata_only=True
    kg.upsert_document.assert_called_once()
    call_kwargs = kg.upsert_document.call_args
    doc_data = call_kwargs[0][0]
    assert doc_data["metadata_only"] is True
```

- [ ] **Step 4.2: Run to confirm failures**

```bash
python -m pytest tests/test_kg_ingestion.py -v 2>&1 | head -30
```
Expected: Multiple FAILs — `ModuleNotFoundError: No module named 'knowledge_graph.ingestion'`

- [ ] **Step 4.3: Create `src/knowledge_graph/ingestion.py`**

```python
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
import re
import uuid
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
            return text, len(text.strip()) < 50
        except Exception:
            return "", True

    if mime_type == "application/pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            parts = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
            text = "\n".join(parts)
            return text, len(text.strip()) < 50
        except Exception as e:
            logger.warning(f"PDF extraction failed: {e}")
            return "", True

    if mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text, len(text.strip()) < 50
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

    def __init__(self):
        self._kg = KnowledgeGraphClient()
        self._drive = DriveService()

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

        for folder_path, folder_id in folder_map.items():
            # Skip Agent Workspace
            if any(folder_path.startswith(skip) for skip in SKIP_PREFIXES):
                continue

            try:
                files = self._drive.list_folder_files(folder_id)
            except Exception as e:
                logger.error(f"[{project_id}] Failed to list {folder_path}: {e}")
                stats["errors"] += 1
                continue

            for file_meta in files:
                file_id   = file_meta["id"]
                filename  = file_meta["name"]
                mime_type = file_meta.get("mimeType", "application/octet-stream")

                # Idempotency: skip if already in graph
                if self._kg.document_exists(file_id):
                    logger.debug(f"[{project_id}] Skipping existing: {filename}")
                    stats["skipped"] += 1
                    continue

                result = self._process_file(
                    project_id=project_id,
                    file_id=file_id,
                    filename=filename,
                    mime_type=mime_type,
                    folder_path=folder_path,
                    dry_run=dry_run,
                )
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
        doc_id = f"{project_id}_{doc_type}_{doc_number or file_id[:8]}"

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

        if dry_run:
            print(f"  [DRY RUN] {filename} → {doc_type} | metadata_only={metadata_only}")
            return "metadata_only" if metadata_only else "written"

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
```

- [ ] **Step 4.4: Run ingestion tests — verify all pass**

```bash
python -m pytest tests/test_kg_ingestion.py -v
```
Expected: All tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/knowledge_graph/ingestion.py tests/test_kg_ingestion.py
git commit -m "feat(kg): add DriveToKGIngester for Drive-to-graph document ingestion"
```

---

## Task 5: `scripts/ingest_drive_to_kg.py` — CLI Runner

**Files:**
- Create: `scripts/ingest_drive_to_kg.py`

- [ ] **Step 5.1: Create `scripts/ingest_drive_to_kg.py`**

```python
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ai_engine.gcp import gcp_integration
from integrations.drive.service import DriveService, CANONICAL_FOLDERS
from knowledge_graph.client import KnowledgeGraphClient
from knowledge_graph.ingestion import DriveToKGIngester

PILOT_PROJECTS = [
    {"project_id": "11900", "name": "WHCCD - Instructional Center Ph. 1",                     "phase": "construction"},
    {"project_id": "12556", "name": "Golden Valley USD - Canyon Creek ES",                     "phase": "construction"},
    {"project_id": "12333", "name": "FUSD Sunnyside HS Lighting & Sound System",               "phase": "construction"},
    {"project_id": "13055", "name": "Golden Valley USD - Liberty HS Track & Stadium Expansion", "phase": "construction"},
    {"project_id": "13193", "name": "Orosi HS CTE",                                            "phase": "construction"},
]


def _build_folder_map(drive: DriveService, project_id: str) -> dict:
    """Load the folder_path → folder_id map from Firestore for a project."""
    folder_map = {}
    for phase_folder, subfolders in CANONICAL_FOLDERS.items():
        for sub in subfolders:
            path = f"{phase_folder}/{sub}"
            fid = drive.get_folder_id(project_id, path)
            if fid:
                folder_map[path] = fid
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
        # Pull root folder ID from Firestore
        root_folder_id = drive.get_folder_id(project_id, "") or ""
        # Fallback: try to retrieve from drive_folders root_folder_id
        if not root_folder_id:
            from ai_engine.gcp import gcp_integration
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

    folder_map = _build_folder_map(drive, project_id)
    if not folder_map:
        print(f"  ⚠ No folder registry found for project {project_id} — run seed_drive_folders.py first.")
        return {"written": 0, "skipped": 0, "errors": 1, "metadata_only": 0}

    print(f"  Found {len(folder_map)} subfolders in Drive registry")
    stats = ingester.ingest_project(project_id, folder_map=folder_map, dry_run=dry_run)

    status = "[DRY RUN] " if dry_run else ""
    print(
        f"  {status}✓ written={stats['written']}  "
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

    print(f"Ingesting {len(projects)} project(s) from Drive → Neo4j …")

    if args.dry_run:
        drive = DriveService()
        ingester = DriveToKGIngester()
        kg = KnowledgeGraphClient()
    else:
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
```

- [ ] **Step 5.2: Commit**

```bash
git add scripts/ingest_drive_to_kg.py
git commit -m "feat(kg): add Drive-to-KG ingestion CLI runner"
```

---

## Task 6: Full Test Suite Pass & Verification Queries

**Files:**
- No new files

- [ ] **Step 6.1: Run the full test suite**

```bash
python -m pytest tests/test_kg_client.py tests/test_setup_kg_schema.py tests/test_seed_kg_baseline.py tests/test_kg_ingestion.py -v
```
Expected: All tests PASS. Fix any failures before proceeding.

- [ ] **Step 6.2: Dry-run the schema setup against real Neo4j**

Ensure NEO4J_* env vars are set (from `.env.txt`), then:

```bash
python scripts/setup_kg_schema.py --dry-run
```
Expected output:
```
=== DRY RUN — 15 statements would be applied ===
  → CREATE CONSTRAINT agent_unique IF NOT EXISTS ...
  → CREATE CONSTRAINT playbook_rule_unique IF NOT EXISTS ...
  ...
  → CREATE VECTOR INDEX ca_document_embeddings IF NOT EXISTS ...
```

- [ ] **Step 6.3: Apply schema to real Neo4j**

```bash
python scripts/setup_kg_schema.py
```
Expected: 15 lines of `✓ CREATE CONSTRAINT/VECTOR INDEX …` — no errors.

- [ ] **Step 6.4: Dry-run the seed script**

```bash
python scripts/seed_kg_baseline.py --dry-run
```
Expected: Node count preview printed with no errors.

- [ ] **Step 6.5: Seed the KG (skip embeddings for first pass)**

```bash
python scripts/seed_kg_baseline.py --no-embed
```
Verify in Neo4j browser / console:
```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY cnt DESC
```
Expected labels present: `DocumentType`, `WorkflowStep`, `SpecSection`, `ContractClause`, `Agent`, `PlaybookRule`, `EscalationCriteria`

- [ ] **Step 6.6: Dry-run ingestion for project 11900**

```bash
python scripts/ingest_drive_to_kg.py --project 11900 --dry-run
```
Expected: File list printed with `[DRY RUN]` prefix, no writes.

- [ ] **Step 6.7: Run live ingestion for project 11900**

```bash
python scripts/ingest_drive_to_kg.py --project 11900
```
Then verify in Neo4j:
```cypher
MATCH (p:Project {project_id: '11900'})-[:HAS_DOCUMENT]->(d:CADocument)
RETURN d.doc_type, count(*) ORDER BY count(*) DESC
```

- [ ] **Step 6.8: Final commit**

```bash
git add .
git commit -m "chore(kg): verify schema, seed, and ingestion against live Neo4j"
```

---

## Verification Checklist

Run these Cypher queries in the Neo4j Aura console to confirm everything landed correctly:

```cypher
// 1. Node count by label
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY cnt DESC

// 2. RFI workflow chain
MATCH p=(dt:DocumentType {type_id: 'RFI'})-[:FOLLOWS_WORKFLOW]->(ws:WorkflowStep)
RETURN ws.sequence, ws.name ORDER BY ws.sequence

// 3. Dispatcher playbook rules
MATCH (:Agent {agent_id: 'AGENT-DISPATCH-001'})-[:HAS_RULE]->(r:PlaybookRule)
RETURN r.priority, r.description ORDER BY r.priority

// 4. Document distribution per project (after ingestion)
MATCH (p:Project)-[:HAS_DOCUMENT]->(d:CADocument)
RETURN p.project_id, d.doc_type, count(*) AS cnt ORDER BY p.project_id, cnt DESC

// 5. Semantic search (run after embeddings are generated)
// Replace $vec with a real 768-dim vector from engine.generate_embedding("concrete footing")
CALL db.index.vector.queryNodes('spec_section_embeddings', 3, $vec)
YIELD node, score
RETURN node.title, score ORDER BY score DESC
```
