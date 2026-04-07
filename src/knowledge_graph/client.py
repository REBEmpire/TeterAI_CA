"""
KnowledgeGraphClient — all Neo4j Aura queries for TeterAI_CA.

Connection Resilience
---------------------
Long-running processes (ingestion, batch analysis) can hold idle Neo4j connections
that the Windows TCP stack kills after a timeout (error 10053 / ConnectionAbortedError).
All write and analytics methods use the ``_run_with_retry`` + ``_reconnect`` + ``_session``
pattern to recover transparently.

  _run_with_retry(fn)   Calls fn() up to _MAX_RETRIES times on connection errors.
  _reconnect()          Closes and reopens the Neo4j driver.
  _session()            Returns a fresh session, reconnecting the driver if needed.

``max_connection_lifetime=300`` rotates connections every 5 minutes to stay ahead of
any network-layer idle timeouts.

Vector Indexes (768-dim Vertex AI text-embedding-004)
-----------------------------------------------------
  ca_document_embeddings   on CADocument.embedding  — all ingested CA documents
  rfi_embeddings           on RFI.embedding         — RFI question/response text
  spec_section_embeddings  on SpecSection.embedding — CSI spec section summaries

Key Node Types
--------------
  Project         {project_id, project_number, name, phase, drive_root_folder_id}
  CADocument      {doc_id, drive_file_id, filename, doc_type, doc_number, phase,
                   date_submitted, date_responded, summary, embedding, metadata_only}
  Party           {party_id, name, type}
  RFI             {rfi_id, rfi_number, question, response_text, embedding, ...}
  SpecSection     {section_number, title, content_summary, embedding, ...}

Key Relationships
-----------------
  (Project)-[:HAS_DOCUMENT]->(CADocument)
  (CADocument)-[:SUBMITTED_BY]->(Party)
  (Project)-[:HAS_RFI]->(RFI)
  (RFI)-[:REFERENCES_SPEC]->(SpecSection)

Singleton
---------
``kg_client = KnowledgeGraphClient()`` at module bottom — import this directly.
"""
import os
import logging
import time
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from ai_engine.engine import engine

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 2  # seconds


class KnowledgeGraphClient:
    def __init__(self):
        self._uri = os.environ.get("NEO4J_URI")
        self._auth = (
            os.environ.get("NEO4J_USERNAME", ""),
            os.environ.get("NEO4J_PASSWORD", ""),
        )

        if not self._uri or not self._auth[0] or not self._auth[1]:
            logger.warning("Neo4j credentials not fully provided in environment variables.")
            self._driver = None
        else:
            self._driver = self._make_driver()

    def _make_driver(self):
        """Create a fresh Neo4j driver instance."""
        try:
            return GraphDatabase.driver(
                self._uri,
                auth=self._auth,
                connection_timeout=30,
                max_connection_lifetime=300,  # rotate connections every 5 min
            )
        except Exception as e:
            logger.error(f"Failed to initialize Neo4j driver: {e}")
            return None

    def _reconnect(self):
        """Close the current driver and open a fresh one."""
        try:
            if self._driver:
                self._driver.close()
        except Exception:
            pass
        self._driver = self._make_driver()

    def _session(self):
        """Return a new session, reconnecting if the driver is dead."""
        if not self._driver:
            self._reconnect()
        return self._driver.session()

    def _run_with_retry(self, fn, *args, **kwargs):
        """
        Call fn() which uses self._driver.  Retry up to _MAX_RETRIES times on
        ServiceUnavailable / SessionExpired / ConnectionAbortedError.
        """
        last_exc = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except (ServiceUnavailable, SessionExpired, OSError, ConnectionAbortedError) as exc:
                last_exc = exc
                logger.warning(
                    f"Neo4j connection error (attempt {attempt}/{_MAX_RETRIES}): {exc}. Reconnecting..."
                )
                time.sleep(_RETRY_DELAY * attempt)
                self._reconnect()
        raise last_exc

    def is_connected(self) -> bool:
        """Return True if the driver exists and can reach the Neo4j server."""
        if not self._driver:
            return False
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def close(self):
        if self._driver:
            self._driver.close()

    def get_agent_playbook(self, agent_id: str) -> List[Dict[str, Any]]:
        if not self._driver:
            return []

        query = """
        MATCH (a:Agent {agent_id: $agent_id})-[:HAS_RULE]->(r:PlaybookRule)
        RETURN r.rule_id AS rule_id,
               r.description AS description,
               r.condition AS condition,
               r.action AS action,
               r.confidence_threshold AS confidence_threshold,
               r.priority AS priority
        ORDER BY r.priority ASC
        """

        with self._driver.session() as session:
            result = session.run(query, agent_id=agent_id)
            return [record.data() for record in result]

    def search_spec_sections(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self._driver:
            return []

        try:
            # Generate vector for the query
            query_vector = engine.generate_embedding(query)
        except Exception as e:
            logger.error(f"Failed to generate embedding for query: {e}")
            return []

        threshold = float(os.environ.get("KG_EMBEDDING_SIMILARITY_THRESHOLD", 0.75))

        cypher = """
        CALL db.index.vector.queryNodes('spec_section_embeddings', $top_k, $query_vector)
        YIELD node, score
        WHERE score > $threshold
        RETURN node.csi_division AS csi_division,
               node.section_number AS section_number,
               node.title AS title,
               node.content_summary AS content_summary,
               score
        ORDER BY score DESC
        """

        with self._driver.session() as session:
            result = session.run(cypher, top_k=top_k, query_vector=query_vector, threshold=threshold)
            return [record.data() for record in result]

    def search_project_documents(
        self,
        query: str,
        project_id: Optional[str] = None,
        doc_types: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Vector-search ingested CADocument nodes by semantic similarity.

        Used as a fallback when SpecSection nodes are sparse or absent — lets
        agents draw on the full library of 500+ ingested project documents
        (submittals, past RFIs, bulletins, specs, change orders, etc.) without
        requiring the Document Intelligence chunker to have run first.

        Args:
            query:      Free-text query (the RFI question, submittal subject, etc.)
            project_id: If set, restrict results to this project only.
            doc_types:  Optional list of doc_type values to filter (e.g. ['RFI', 'SUBMITTAL']).
                        None means all types.
            top_k:      Maximum results to return after similarity filtering.
        """
        if not self._driver:
            return []

        try:
            query_vector = engine.generate_embedding(query)
        except Exception as e:
            logger.error(f"search_project_documents: embedding failed: {e}")
            return []

        # Use a slightly lower threshold than spec sections so we get broader context
        threshold = float(os.environ.get("KG_EMBEDDING_SIMILARITY_THRESHOLD", 0.70))
        fetch_k = top_k * 3  # over-fetch to allow for post-filters

        # Build optional WHERE clause fragments
        type_filter = "AND d.doc_type IN $doc_types" if doc_types else ""
        project_filter = "AND p.project_id = $project_id" if project_id else ""

        cypher = f"""
        CALL db.index.vector.queryNodes('ca_document_embeddings', $fetch_k, $query_vector)
        YIELD node AS d, score
        WHERE score > $threshold {type_filter}
        MATCH (p:Project)-[:HAS_DOCUMENT]->(d)
        WHERE 1=1 {project_filter}
        RETURN d.doc_id         AS doc_id,
               d.filename       AS filename,
               d.doc_type       AS doc_type,
               d.doc_number     AS doc_number,
               d.summary        AS summary,
               d.date_submitted AS date_submitted,
               p.project_id     AS project_id,
               p.project_number AS project_number,
               p.name           AS project_name,
               score
        ORDER BY score DESC
        LIMIT $top_k
        """

        with self._driver.session() as session:
            result = session.run(
                cypher,
                fetch_k=fetch_k,
                query_vector=query_vector,
                threshold=threshold,
                doc_types=doc_types or [],
                project_id=project_id or "",
                top_k=top_k,
            )
            return [record.data() for record in result]

    def get_document_workflow(self, doc_type: str) -> List[Dict[str, Any]]:
        if not self._driver:
            return []

        # A simpler query that just gets all steps associated with doc_type if sequences are reliable
        simple_query = """
        MATCH (d:DocumentType {type_id: $doc_type})-[:FOLLOWS_WORKFLOW]->(first:WorkflowStep)
        MATCH p = (first)-[:NEXT_STEP*0..]->(step:WorkflowStep)
        WITH DISTINCT step
        RETURN step.step_id AS step_id,
               step.name AS name,
               step.description AS description,
               step.responsible_party AS responsible_party,
               step.sequence AS sequence
        ORDER BY step.sequence ASC
        """

        with self._driver.session() as session:
            result = session.run(simple_query, doc_type=doc_type)
            return [record.data() for record in result]

    def get_contract_clause(self, clause_id: str) -> Optional[Dict[str, Any]]:
        if not self._driver:
            return None

        query = """
        MATCH (c:ContractClause {clause_id: $clause_id})
        RETURN c.clause_id AS clause_id,
               c.standard AS standard,
               c.clause_number AS clause_number,
               c.title AS title,
               c.text AS text
        """

        with self._driver.session() as session:
            result = session.run(query, clause_id=clause_id)
            record = result.single()
            if record:
                return record.data()
            return None

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

    def setup_rfi_schema(self) -> None:
        """Creates Project and RFI constraints and vector index. Idempotent."""
        if not self._driver:
            return

        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Project) REQUIRE p.project_id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (r:RFI) REQUIRE r.rfi_id IS UNIQUE")
            session.run("""
            CREATE VECTOR INDEX rfi_embeddings IF NOT EXISTS
            FOR (n:RFI) ON (n.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: 768,
                `vector.similarity_function`: 'cosine'
            }}
            """)
            session.run("CALL db.awaitIndexes(120)")

    def search_rfis(self, query: str, top_k: int = 5, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Semantic search across ingested RFI questions. Optionally filter by project_id."""
        if not self._driver:
            return []

        try:
            query_vector = engine.generate_embedding(query)
        except Exception as e:
            logger.error(f"Failed to generate embedding for RFI search: {e}")
            return []

        threshold = float(os.environ.get("KG_EMBEDDING_SIMILARITY_THRESHOLD", 0.75))

        cypher = """
        CALL db.index.vector.queryNodes('rfi_embeddings', $top_k, $query_vector)
        YIELD node, score
        WHERE score > $threshold
          AND ($project_id IS NULL OR node.project_id = $project_id)
        RETURN node.rfi_id AS rfi_id,
               node.project_id AS project_id,
               node.rfi_number AS rfi_number,
               node.contractor_name AS contractor_name,
               node.question AS question,
               node.response_text AS response_text,
               node.status AS status,
               node.date_submitted AS date_submitted,
               score
        ORDER BY score DESC
        """

        with self._driver.session() as session:
            result = session.run(
                cypher,
                top_k=top_k,
                query_vector=query_vector,
                threshold=threshold,
                project_id=project_id
            )
            return [record.data() for record in result]

    def get_project_rfis(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all ingested RFIs for a project, ordered by RFI number."""
        if not self._driver:
            return []

        cypher = """
        MATCH (p:Project {project_id: $project_id})-[:HAS_RFI]->(r:RFI)
        RETURN r.rfi_id AS rfi_id,
               r.rfi_number AS rfi_number,
               r.contractor_name AS contractor_name,
               r.question AS question,
               r.response_text AS response_text,
               r.status AS status,
               r.date_submitted AS date_submitted,
               r.referenced_spec_sections AS referenced_spec_sections,
               r.source_file_name AS source_file_name
        ORDER BY r.rfi_number ASC
        """

        with self._driver.session() as session:
            result = session.run(cypher, project_id=project_id)
            return [record.data() for record in result]

    def find_rfi_patterns(self) -> Dict[str, Any]:
        """
        Finds cross-project RFI patterns:
        - Spec sections referenced in RFIs across multiple projects
        - Per-project RFI counts
        - Total ingested RFI count
        """
        if not self._driver:
            return {}

        with self._driver.session() as session:
            # Spec sections cited in RFIs from more than one project
            cross_project_specs = session.run("""
            MATCH (r:RFI)-[:REFERENCES_SPEC]->(s:SpecSection)
            WITH s.section_number AS section,
                 s.title AS title,
                 collect(DISTINCT r.project_id) AS projects,
                 count(r) AS rfi_count
            WHERE size(projects) > 1
            RETURN section, title, projects, rfi_count
            ORDER BY rfi_count DESC
            """)

            # Per-project RFI counts
            project_counts = session.run("""
            MATCH (p:Project)-[:HAS_RFI]->(r:RFI)
            RETURN p.project_id AS project_id,
                   p.project_name AS project_name,
                   count(r) AS rfi_count
            ORDER BY rfi_count DESC
            """)

            # All spec section citation counts (single + multi project)
            all_spec_citations = session.run("""
            MATCH (r:RFI)-[:REFERENCES_SPEC]->(s:SpecSection)
            RETURN s.section_number AS section,
                   s.title AS title,
                   collect(DISTINCT r.project_id) AS projects,
                   count(r) AS rfi_count
            ORDER BY rfi_count DESC
            LIMIT 20
            """)

            total_rfis = session.run("MATCH (r:RFI) RETURN count(r) AS c").single()["c"]

            return {
                "total_rfis": total_rfis,
                "project_counts": [record.data() for record in project_counts],
                "cross_project_spec_patterns": [record.data() for record in cross_project_specs],
                "top_spec_citations": [record.data() for record in all_spec_citations],
            }


    # ------------------------------------------------------------------
    # Phase D: Design Flaw Pattern Graph
    # ------------------------------------------------------------------

    def get_rfi_pattern_graph(
        self,
        project_id: str,
        spec_division: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return a nodes+edges payload suitable for the KnowledgeGraphView frontend.

        Fetches SpecSection, RFI, DESIGN_FLAW and CORRECTIVE_ACTION nodes for
        *project_id*, along with REFERENCES_SPEC, REVEALS and SUGGESTS edges.

        Optional filters:
          spec_division  – e.g. "08" filters SpecSection nodes whose section_number
                           starts with that prefix.
          date_from/to   – ISO date strings; filter RFI nodes by created_at.
        """
        if not self._driver:
            return {"nodes": [], "edges": []}

        # Build optional WHERE clauses
        division_filter = "AND s.section_number STARTS WITH $division " if spec_division else ""
        date_from_filter = "AND r.created_at >= $date_from " if date_from else ""
        date_to_filter = "AND r.created_at <= $date_to " if date_to else ""

        params: Dict[str, Any] = {"project_id": project_id}
        if spec_division:
            params["division"] = spec_division
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        cypher = f"""
        // --- SpecSection nodes ---
        MATCH (s:SpecSection {{project_id: $project_id}})
        WHERE true {division_filter}
        WITH collect({{
            id: 'ss_' + s.section_number,
            type: 'SPEC_SECTION',
            label: s.section_number,
            properties: {{section_number: s.section_number, title: coalesce(s.title, s.section_number)}}
        }}) AS spec_nodes

        // --- RFI nodes ---
        OPTIONAL MATCH (r:RFI {{project_id: $project_id}})
        WHERE true {date_from_filter}{date_to_filter}
        WITH spec_nodes, collect({{
            id: 'rfi_' + r.rfi_id,
            type: 'RFI',
            label: coalesce(r.rfi_number, r.rfi_id),
            properties: {{
                rfi_id: r.rfi_id,
                question: coalesce(r.question, ''),
                status: coalesce(r.status, '')
            }}
        }}) AS rfi_nodes

        // --- DESIGN_FLAW nodes ---
        OPTIONAL MATCH (f:DESIGN_FLAW {{project_id: $project_id}})
        WITH spec_nodes, rfi_nodes, collect({{
            id: 'df_' + f.flaw_id,
            type: 'DESIGN_FLAW',
            label: f.category,
            properties: {{
                flaw_id: f.flaw_id,
                category: f.category,
                description: coalesce(f.description, '')
            }}
        }}) AS flaw_nodes

        // --- CORRECTIVE_ACTION nodes ---
        OPTIONAL MATCH (a:CORRECTIVE_ACTION {{project_id: $project_id}})
        WITH spec_nodes, rfi_nodes, flaw_nodes, collect({{
            id: 'ca_' + a.action_id,
            type: 'CORRECTIVE_ACTION',
            label: left(a.action, 60),
            properties: {{action_id: a.action_id, action: a.action}}
        }}) AS action_nodes

        RETURN spec_nodes, rfi_nodes, flaw_nodes, action_nodes
        """

        edge_cypher = f"""
        MATCH (r:RFI {{project_id: $project_id}})-[rel]->(target)
        WHERE true {date_from_filter}{date_to_filter}
        RETURN
            CASE
                WHEN r.rfi_id IS NOT NULL THEN 'rfi_' + r.rfi_id
                ELSE 'rfi_' + id(r)
            END AS source,
            CASE
                WHEN target:SpecSection THEN 'ss_' + target.section_number
                WHEN target:DESIGN_FLAW THEN 'df_' + target.flaw_id
                ELSE 'ca_' + target.action_id
            END AS target_id,
            type(rel) AS rel_type

        UNION ALL

        MATCH (f:DESIGN_FLAW {{project_id: $project_id}})-[rel2]->(a:CORRECTIVE_ACTION)
        RETURN
            'df_' + f.flaw_id AS source,
            'ca_' + a.action_id AS target_id,
            type(rel2) AS rel_type
        """

        nodes: list = []
        edges: list = []

        try:
            with self._driver.session() as session:
                result = session.run(cypher, **params)
                record = result.single()
                if record:
                    for group in ("spec_nodes", "rfi_nodes", "flaw_nodes", "action_nodes"):
                        raw = record.get(group) or []
                        for item in raw:
                            if item and item.get("id"):
                                nodes.append(dict(item))

                edge_result = session.run(edge_cypher, **params)
                for row in edge_result:
                    src = row.get("source")
                    tgt = row.get("target_id")
                    rel = row.get("rel_type", "RELATED")
                    if src and tgt:
                        edges.append({"source": src, "target": tgt, "type": rel})

        except Exception as e:
            logger.error(f"get_rfi_pattern_graph failed: {e}")
            return {"nodes": [], "edges": []}

        return {"nodes": nodes, "edges": edges}


    # ------------------------------------------------------------------
    # Universal schema setup (all doc types)
    # ------------------------------------------------------------------

    def setup_universal_schema(self) -> None:
        """
        Create constraints and indexes for all document-type nodes.
        Idempotent — safe to call on every startup or via admin endpoint.
        """
        if not self._driver:
            return

        statements = [
            # Party (shared across all types)
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Party) REQUIRE (p.name, p.party_type) IS NODE KEY",
            # Submittal
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Submittal) REQUIRE s.task_id IS UNIQUE",
            # ScheduleReview
            "CREATE CONSTRAINT IF NOT EXISTS FOR (sr:ScheduleReview) REQUIRE sr.task_id IS UNIQUE",
            # PayApp
            "CREATE CONSTRAINT IF NOT EXISTS FOR (pa:PayApp) REQUIRE pa.task_id IS UNIQUE",
            # CostAnalysis
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ca:CostAnalysis) REQUIRE ca.task_id IS UNIQUE",
        ]

        with self._driver.session() as session:
            for stmt in statements:
                try:
                    session.run(stmt)
                except Exception as e:
                    logger.warning(f"setup_universal_schema: statement skipped — {e}")
            try:
                session.run("CALL db.awaitIndexes(60)")
            except Exception:
                pass

        logger.info("setup_universal_schema: complete.")

    # ------------------------------------------------------------------
    # Full project graph (all doc types)
    # ------------------------------------------------------------------

    def get_full_project_graph(
        self,
        project_id: str,
        doc_type_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return a nodes+edges payload for the KnowledgeGraphView 'Full Project' mode.

        The KG stores all CA documents as CADocument nodes connected via
        (Project)-[:HAS_DOCUMENT]->(CADocument) with a doc_type property.

        doc_type_filter: frontend pill value — one of:
            "rfi", "submittal", "schedule_review", "pay_app", "cost_analysis"
            If None / empty, all types are returned (capped at 300 docs).
        """
        if not self._driver:
            return {"nodes": [], "edges": []}

        # Map frontend filter values to actual doc_type values stored in Neo4j
        DOC_TYPE_MAP: Dict[str, list] = {
            "rfi":             ["RFI", "PB_RFI"],
            "submittal":       ["SUBMITTAL"],
            "schedule_review": ["SITE_VISIT", "BULLETIN"],
            "pay_app":         ["PAY_APP"],
            "cost_analysis":   ["PCO_COR"],
        }

        doc_types: Optional[list] = (
            DOC_TYPE_MAP.get(doc_type_filter)
            if doc_type_filter and doc_type_filter in DOC_TYPE_MAP
            else None
        )

        nodes: list = []
        edges: list = []

        try:
            with self._driver.session() as session:

                # --- Document nodes (CADocument via HAS_DOCUMENT) ---
                if doc_types:
                    doc_result = session.run(
                        """
                        MATCH (proj:Project {project_id: $project_id})
                              -[:HAS_DOCUMENT]->(d:CADocument)
                        WHERE d.doc_type IN $doc_types
                        RETURN d.doc_id        AS doc_id,
                               d.doc_number    AS doc_number,
                               d.doc_type      AS doc_type,
                               d.filename      AS filename,
                               d.date_submitted AS date_submitted,
                               d.summary       AS summary,
                               d.phase         AS phase
                        """,
                        project_id=project_id,
                        doc_types=doc_types,
                    )
                else:
                    # All types — cap at 300 to keep the graph renderable
                    doc_result = session.run(
                        """
                        MATCH (proj:Project {project_id: $project_id})
                              -[:HAS_DOCUMENT]->(d:CADocument)
                        RETURN d.doc_id        AS doc_id,
                               d.doc_number    AS doc_number,
                               d.doc_type      AS doc_type,
                               d.filename      AS filename,
                               d.date_submitted AS date_submitted,
                               d.summary       AS summary,
                               d.phase         AS phase
                        LIMIT 300
                        """,
                        project_id=project_id,
                    )

                for row in doc_result:
                    doc_id  = row.get("doc_id")
                    if not doc_id:
                        continue
                    doc_type = (row.get("doc_type") or "UNKNOWN").upper()
                    label    = row.get("doc_number") or row.get("filename") or doc_id
                    nodes.append({
                        "id":   f"doc_{doc_id}",
                        "type": doc_type,
                        "label": label,
                        "properties": {
                            "doc_id":        doc_id,
                            "doc_type":      doc_type,
                            "filename":      row.get("filename") or "",
                            "date_submitted": row.get("date_submitted") or "",
                            "phase":         row.get("phase") or "",
                            "summary":       (row.get("summary") or "")[:300],
                            "summary_full":  row.get("summary") or "",
                        },
                    })

                # --- Party nodes (connected through CADocuments in our node set) ---
                if doc_types:
                    party_result = session.run(
                        """
                        MATCH (proj:Project {project_id: $project_id})
                              -[:HAS_DOCUMENT]->(d:CADocument)-[:SUBMITTED_BY]->(p:Party)
                        WHERE d.doc_type IN $doc_types
                        RETURN DISTINCT p.name AS name, p.type AS party_type
                        """,
                        project_id=project_id,
                        doc_types=doc_types,
                    )
                else:
                    party_result = session.run(
                        """
                        MATCH (proj:Project {project_id: $project_id})
                              -[:HAS_DOCUMENT]->(d:CADocument)-[:SUBMITTED_BY]->(p:Party)
                        RETURN DISTINCT p.name AS name, p.type AS party_type
                        """,
                        project_id=project_id,
                    )

                for row in party_result:
                    name = row.get("name", "")
                    if name:
                        nodes.append({
                            "id":   f"party_{name.replace(' ', '_')}",
                            "type": "PARTY",
                            "label": name,
                            "properties": {
                                "name":       name,
                                "party_type": row.get("party_type") or "",
                            },
                        })

                # --- SpecSection nodes (have project_id directly) ---
                spec_result = session.run(
                    """
                    MATCH (s:SpecSection {project_id: $project_id})
                    RETURN s.section_number AS section_number,
                           coalesce(s.title, s.section_number) AS title
                    """,
                    project_id=project_id,
                )
                for row in spec_result:
                    sn = row.get("section_number")
                    if sn:
                        nodes.append({
                            "id":   f"ss_{sn}",
                            "type": "SPEC_SECTION",
                            "label": sn,
                            "properties": {
                                "section_number": sn,
                                "title": row.get("title") or sn,
                            },
                        })

                # --- Edges ---
                node_ids = {n["id"] for n in nodes}

                # SUBMITTED_BY edges: doc → party
                if doc_types:
                    sub_result = session.run(
                        """
                        MATCH (proj:Project {project_id: $project_id})
                              -[:HAS_DOCUMENT]->(d:CADocument)-[:SUBMITTED_BY]->(p:Party)
                        WHERE d.doc_type IN $doc_types
                        RETURN d.doc_id AS doc_id, p.name AS party_name
                        """,
                        project_id=project_id,
                        doc_types=doc_types,
                    )
                else:
                    sub_result = session.run(
                        """
                        MATCH (proj:Project {project_id: $project_id})
                              -[:HAS_DOCUMENT]->(d:CADocument)-[:SUBMITTED_BY]->(p:Party)
                        RETURN d.doc_id AS doc_id, p.name AS party_name
                        LIMIT 500
                        """,
                        project_id=project_id,
                    )

                for row in sub_result:
                    src = f"doc_{row.get('doc_id')}"
                    tgt = f"party_{(row.get('party_name') or '').replace(' ', '_')}"
                    if src in node_ids and tgt in node_ids:
                        edges.append({"source": src, "target": tgt, "type": "SUBMITTED_BY"})

                # REFERENCES_SPEC edges: doc → spec section (if they exist)
                if doc_types:
                    ref_result = session.run(
                        """
                        MATCH (proj:Project {project_id: $project_id})
                              -[:HAS_DOCUMENT]->(d:CADocument)-[:REFERENCES_SPEC]->(s:SpecSection)
                        WHERE d.doc_type IN $doc_types
                        RETURN d.doc_id AS doc_id, s.section_number AS section_number
                        """,
                        project_id=project_id,
                        doc_types=doc_types,
                    )
                else:
                    ref_result = session.run(
                        """
                        MATCH (proj:Project {project_id: $project_id})
                              -[:HAS_DOCUMENT]->(d:CADocument)-[:REFERENCES_SPEC]->(s:SpecSection)
                        RETURN d.doc_id AS doc_id, s.section_number AS section_number
                        LIMIT 500
                        """,
                        project_id=project_id,
                    )

                for row in ref_result:
                    src = f"doc_{row.get('doc_id')}"
                    tgt = f"ss_{row.get('section_number')}"
                    if src in node_ids and tgt in node_ids:
                        edges.append({"source": src, "target": tgt, "type": "REFERENCES_SPEC"})

        except Exception as e:
            logger.error(f"get_full_project_graph failed: {e}")
            return {"nodes": [], "edges": []}

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Semantic search across graph
    # ------------------------------------------------------------------


    def keyword_search_graph(self, query: str, project_id: Optional[str] = None, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        Search the graph using Neo4j full-text indexes instead of vector embeddings.
        """
        if not self._driver:
            return []

        def _do(session):
            cypher = """
            CALL db.index.fulltext.queryNodes('ca_document_fulltext', $query) YIELD node, score
            """
            if project_id:
                cypher += " MATCH (node)-[:BELONGS_TO]->(p:Project {project_id: $project_id})"
            else:
                cypher += " MATCH (node)-[:BELONGS_TO]->(p:Project)"

            cypher += """
            RETURN node.doc_id AS doc_id,
                   node.filename AS filename,
                   node.doc_type AS doc_type,
                   node.doc_number AS doc_number,
                   node.summary AS summary,
                   node.date_submitted AS date_submitted,
                   p.project_id AS project_id,
                   p.name AS project_name,
                   score
            ORDER BY score DESC
            LIMIT $top_k
            """

            results = session.run(cypher, query=query, project_id=project_id, top_k=top_k)
            return [
                {
                    "node_id":    r.get("doc_id"),
                    "node_type":  r.get("doc_type"),
                    "label":      r.get("filename") or f"Doc {r.get('doc_number')}",
                    "score":      r.get("score"),
                    "properties": {
                        "project_id": r.get("project_id") or "",
                        "project_name": r.get("project_name") or "",
                        "doc_number": r.get("doc_number") or "",
                        "date_submitted": r.get("date_submitted") or "",
                        "summary": r.get("summary") or "",
                        "summary_full": r.get("summary") or ""
                    }
                }
                for r in results
            ]

        return self._run_with_retry(_do)

    def semantic_search_graph(
        self,
        query: str,
        project_id: Optional[str] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search across RFI embeddings.  Returns a list of matching
        nodes with score, type, label, and key properties.
        """
        if not self._driver:
            return []

        try:
            query_vector = engine.generate_embedding(query)
        except Exception as e:
            logger.error(f"semantic_search_graph: embedding failed — {e}")
            return []

        threshold = float(os.environ.get("KG_EMBEDDING_SIMILARITY_THRESHOLD", 0.70))

        cypher = """
        CALL db.index.vector.queryNodes('rfi_embeddings', $top_k, $query_vector)
        YIELD node, score
        WHERE score > $threshold
          AND ($project_id IS NULL OR node.project_id = $project_id)
        RETURN
            node.rfi_id        AS node_id,
            'RFI'              AS node_type,
            coalesce(node.rfi_number, node.rfi_id) AS label,
            node.question      AS question,
            node.status        AS status,
            node.project_id    AS project_id,
            score
        ORDER BY score DESC
        LIMIT $top_k
        """

        with self._driver.session() as session:
            result = session.run(
                cypher,
                top_k=top_k,
                query_vector=query_vector,
                threshold=threshold,
                project_id=project_id,
            )
            return [
                {
                    "node_id":   r.get("node_id"),
                    "node_type": r.get("node_type"),
                    "label":     r.get("label"),
                    "score":     r.get("score"),
                    "properties": {
                        "question":   r.get("question") or "",
                        "status":     r.get("status", ""),
                        "project_id": r.get("project_id", ""),
                    },
                }
                for r in result
            ]

    # ------------------------------------------------------------------
    # Project graph statistics
    # ------------------------------------------------------------------

    def get_project_graph_stats(self, project_id: str) -> Dict[str, Any]:
        """
        Return counts and summaries for a project's graph data.
        """
        if not self._driver:
            return {}

        stats: Dict[str, Any] = {
            "rfi_count":            0,
            "submittal_count":      0,
            "schedule_review_count": 0,
            "payapp_count":         0,
            "cost_analysis_count":  0,
            "unique_parties":       0,
            "unique_spec_sections": 0,
            "top_design_flaws":     [],
        }

        try:
            with self._driver.session() as session:
                # Count CADocuments by doc_type (all connected via HAS_DOCUMENT)
                counts_result = session.run(
                    """
                    MATCH (proj:Project {project_id: $p})-[:HAS_DOCUMENT]->(d:CADocument)
                    RETURN d.doc_type AS doc_type, count(d) AS c
                    """,
                    p=project_id,
                )
                rfi_types      = {"RFI", "PB_RFI"}
                submittal_types = {"SUBMITTAL"}
                schedule_types  = {"SITE_VISIT", "BULLETIN"}
                payapp_types    = {"PAY_APP"}
                cost_types      = {"PCO_COR"}
                for row in counts_result:
                    dt = (row["doc_type"] or "").upper()
                    c  = row["c"]
                    if dt in rfi_types:
                        stats["rfi_count"] += c
                    elif dt in submittal_types:
                        stats["submittal_count"] += c
                    elif dt in schedule_types:
                        stats["schedule_review_count"] += c
                    elif dt in payapp_types:
                        stats["payapp_count"] += c
                    elif dt in cost_types:
                        stats["cost_analysis_count"] += c

                # Unique parties via HAS_DOCUMENT path
                party_rec = session.run(
                    """
                    MATCH (proj:Project {project_id: $p})
                          -[:HAS_DOCUMENT]->(d:CADocument)-[:SUBMITTED_BY]->(party:Party)
                    RETURN count(DISTINCT party.name) AS c
                    """,
                    p=project_id,
                ).single()
                if party_rec:
                    stats["unique_parties"] = party_rec["c"]

                # Unique spec sections (have project_id directly)
                spec_rec = session.run(
                    "MATCH (s:SpecSection {project_id: $p}) RETURN count(s) AS c",
                    p=project_id,
                ).single()
                if spec_rec:
                    stats["unique_spec_sections"] = spec_rec["c"]

        except Exception as e:
            logger.error(f"get_project_graph_stats failed: {e}")

        return stats

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

        def _do():
            with self._session() as session:
                result = session.run(
                    "MATCH (d:CADocument {drive_file_id: $drive_file_id}) RETURN count(d) AS cnt",
                    drive_file_id=drive_file_id,
                )
                record = result.single()
                return (record["cnt"] > 0) if record else False

        return self._run_with_retry(_do)

    def document_is_metadata_only(self, drive_file_id: str) -> bool:
        """Return True if the CADocument exists AND was stored as metadata_only=True.

        Used by the ingester to decide whether to re-process a previously-failed
        extraction (e.g. after fixing a text extraction bug).
        """
        if not self._driver:
            return False

        def _do():
            with self._session() as session:
                result = session.run(
                    "MATCH (d:CADocument {drive_file_id: $drive_file_id}) "
                    "RETURN d.metadata_only AS mo",
                    drive_file_id=drive_file_id,
                )
                record = result.single()
                return bool(record["mo"]) if record else False

        return self._run_with_retry(_do)

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

        def _do():
            with self._session() as session:
                # Call 1: upsert the document node
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
                    """,
                    **doc_data,
                )
                # Call 2: link to project
                session.run(
                    """
                    MATCH (d:CADocument {drive_file_id: $drive_file_id})
                    MATCH (p:Project {project_id: $project_id})
                    MERGE (p)-[:HAS_DOCUMENT]->(d)
                    """,
                    drive_file_id=doc_data["drive_file_id"],
                    project_id=project_id,
                )

        self._run_with_retry(_do)

    def upsert_party(self, party_data: dict) -> None:
        """MERGE a Party node. Keys: party_id, name, type."""
        if not self._driver:
            return

        def _do():
            with self._session() as session:
                session.run(
                    """
                    MERGE (party:Party {party_id: $party_id})
                    SET party.name = $name,
                        party.type = $type
                    """,
                    **party_data,
                )

        self._run_with_retry(_do)

    def link_document_to_party(self, drive_file_id: str, party_id: str) -> None:
        """Create (:CADocument)-[:SUBMITTED_BY]->(:Party) relationship."""
        if not self._driver:
            return

        def _do():
            with self._session() as session:
                session.run(
                    """
                    MATCH (d:CADocument {drive_file_id: $drive_file_id})
                    MATCH (party:Party {party_id: $party_id})
                    MERGE (d)-[:SUBMITTED_BY]->(party)
                    """,
                    drive_file_id=drive_file_id,
                    party_id=party_id,
                )

        self._run_with_retry(_do)

    def get_project_documents(
        self, project_id: str, doc_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
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

    # -----------------------------------------------------------------------
    # Project Intelligence Dashboard methods
    # -----------------------------------------------------------------------

    def get_project_intelligence(self, project_id: str) -> Dict[str, Any]:
        """
        Aggregate KPIs for a single project: doc counts by type, response rate,
        metadata_only ratio, party count, and date range.
        """
        if not self._driver:
            return {}

        def _do():
            with self._session() as session:
                row = session.run(
                    """
                    MATCH (p:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(d:CADocument)
                    WITH
                      count(d) AS total_docs,
                      count(d.date_responded) AS responded_docs,
                      sum(CASE WHEN d.metadata_only = true THEN 1 ELSE 0 END) AS metadata_only_count,
                      min(d.date_submitted) AS earliest_date,
                      max(d.date_submitted) AS latest_date
                    RETURN total_docs, responded_docs, metadata_only_count,
                           earliest_date, latest_date
                    """,
                    project_id=project_id,
                ).single()
                if not row:
                    return {}

                type_counts = {
                    r["doc_type"]: r["cnt"]
                    for r in session.run(
                        """
                        MATCH (p:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(d:CADocument)
                        RETURN d.doc_type AS doc_type, count(d) AS cnt
                        ORDER BY cnt DESC
                        """,
                        project_id=project_id,
                    )
                }

                party_count = session.run(
                    """
                    MATCH (p:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(d:CADocument)
                          -[:SUBMITTED_BY]->(party:Party)
                    RETURN count(DISTINCT party) AS cnt
                    """,
                    project_id=project_id,
                ).single()["cnt"] or 0

                total = row["total_docs"] or 0
                responded = row["responded_docs"] or 0
                meta = row["metadata_only_count"] or 0
                return {
                    "project_id": project_id,
                    "total_docs": total,
                    "responded_docs": responded,
                    "response_rate": round(responded / total, 3) if total > 0 else 0.0,
                    "metadata_only_count": meta,
                    "metadata_only_ratio": round(meta / total, 3) if total > 0 else 0.0,
                    "party_count": party_count,
                    "earliest_date": row["earliest_date"],
                    "latest_date": row["latest_date"],
                    "doc_counts_by_type": type_counts,
                }

        return self._run_with_retry(_do)

    def get_party_network(self, project_id: str) -> Dict[str, Any]:
        """
        Return Party nodes + per-party submission counts by doc_type,
        ordered by total submissions descending.
        """
        if not self._driver:
            return {"parties": []}

        def _do():
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (p:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(d:CADocument)
                          -[:SUBMITTED_BY]->(party:Party)
                    WITH party, d.doc_type AS doc_type, count(d) AS cnt
                    WITH party,
                         collect({doc_type: doc_type, count: cnt}) AS submissions,
                         sum(cnt) AS total_submissions
                    RETURN party.party_id AS party_id,
                           party.name     AS name,
                           party.type     AS type,
                           submissions,
                           total_submissions
                    ORDER BY total_submissions DESC
                    """,
                    project_id=project_id,
                )
                return {"parties": [r.data() for r in result]}

        return self._run_with_retry(_do)

    def get_document_timeline(self, project_id: str) -> Dict[str, Any]:
        """
        Return document submission counts grouped by YYYY-MM month for a
        timeline chart.
        """
        if not self._driver:
            return {"months": []}

        def _do():
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (p:Project {project_id: $project_id})-[:HAS_DOCUMENT]->(d:CADocument)
                    WHERE d.date_submitted IS NOT NULL AND d.date_submitted <> ''
                    WITH substring(d.date_submitted, 0, 7) AS month,
                         d.doc_type AS doc_type,
                         count(d) AS cnt
                    ORDER BY month ASC, cnt DESC
                    RETURN month, doc_type, cnt
                    """,
                    project_id=project_id,
                )
                from collections import defaultdict
                months: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
                for r in result:
                    months[r["month"]][r["doc_type"]] += r["cnt"]
                return {
                    "months": [
                        {"month": m, "counts": dict(counts)}
                        for m, counts in sorted(months.items())
                    ]
                }

        return self._run_with_retry(_do)

    def get_cross_project_summary(self) -> Dict[str, Any]:
        """
        Return aggregate intelligence for all projects side-by-side.
        """
        if not self._driver:
            return {"projects": []}

        def _do():
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (p:Project)-[:HAS_DOCUMENT]->(d:CADocument)
                    WITH p,
                         count(d) AS total_docs,
                         count(d.date_responded) AS responded_docs,
                         sum(CASE WHEN d.metadata_only = true THEN 1 ELSE 0 END) AS metadata_only_count
                    OPTIONAL MATCH (p)-[:HAS_DOCUMENT]->(d2:CADocument)-[:SUBMITTED_BY]->(party:Party)
                    WITH p, total_docs, responded_docs, metadata_only_count,
                         count(DISTINCT party) AS party_count
                    RETURN p.project_id   AS project_id,
                           p.name         AS name,
                           p.project_number AS project_number,
                           total_docs,
                           responded_docs,
                           metadata_only_count,
                           party_count
                    ORDER BY total_docs DESC
                    """
                )
                projects = []
                for r in result:
                    data = r.data()
                    total = data.get("total_docs") or 0
                    responded = data.get("responded_docs") or 0
                    data["response_rate"] = round(responded / total, 3) if total > 0 else 0.0
                    projects.append(data)
                return {"projects": projects}

        return self._run_with_retry(_do)


    # -----------------------------------------------------------------------
    # Pre-Bid Lessons Learned methods
    # -----------------------------------------------------------------------

    def get_prebid_lessons(
        self,
        query_text: str,
        source_project_ids: List[str],
        doc_types: Optional[List[str]] = None,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Semantic similarity search across historical CADocuments (RFIs, Change Orders, etc.)
        from the specified source projects.  Returns the most relevant documents that could
        flag design issues before bid.

        Args:
            query_text:         Free-text description of a design concern or topic.
            source_project_ids: Project IDs of completed projects to mine for lessons.
            doc_types:          Restrict to specific doc types (e.g. ['RFI', 'CO']).
                                If None, defaults to common CA problem-indicator types.
            top_k:              Max candidates to retrieve from the vector index.
        """
        if not self._driver:
            return []

        if doc_types is None:
            doc_types = ["RFI", "CO", "CHANGE_ORDER", "Change Order", "COR", "POTENTIAL_CO"]

        try:
            query_vector = engine.generate_embedding(query_text)
        except Exception as e:
            logger.error(f"Embedding generation failed for prebid search: {e}")
            return []

        threshold = float(os.environ.get("KG_EMBEDDING_SIMILARITY_THRESHOLD", "0.65"))

        cypher = """
        CALL db.index.vector.queryNodes('ca_document_embeddings', $fetch_k, $query_vector)
        YIELD node AS d, score
        WHERE score > $threshold
          AND d.doc_type IN $doc_types
        MATCH (p:Project)-[:HAS_DOCUMENT]->(d)
        WHERE p.project_id IN $source_project_ids
        RETURN d.doc_id       AS doc_id,
               d.filename     AS filename,
               d.doc_type     AS doc_type,
               d.doc_number   AS doc_number,
               d.summary      AS summary,
               d.date_submitted AS date_submitted,
               p.project_id  AS project_id,
               p.name        AS project_name,
               p.project_number AS project_number,
               score
        ORDER BY score DESC
        LIMIT $top_k
        """

        with self._driver.session() as session:
            result = session.run(
                cypher,
                fetch_k=top_k * 4,   # over-fetch so post-filters still return enough
                query_vector=query_vector,
                threshold=threshold,
                doc_types=doc_types,
                source_project_ids=source_project_ids,
                top_k=top_k,
            )
            return [r.data() for r in result]

    def get_hotspot_topics(
        self,
        source_project_ids: List[str],
        top_n: int = 20,
    ) -> Dict[str, Any]:
        """
        Return the most frequently occurring RFI / Change Order topics from the
        specified historical projects, grouped by doc_type and by inferred spec
        references (if available).

        Returns a dict with:
          - doc_type_counts:  {doc_type: count}
          - top_docs:         [{doc_id, filename, doc_type, project_name, summary, date_submitted}]
                               ordered by response frequency (docs with date_responded first, newest first)
        """
        if not self._driver:
            return {"doc_type_counts": {}, "top_docs": []}

        def _do():
            with self._session() as session:
                # Per-doc-type counts across source projects
                counts_result = session.run(
                    """
                    MATCH (p:Project)-[:HAS_DOCUMENT]->(d:CADocument)
                    WHERE p.project_id IN $source_project_ids
                      AND d.doc_type IN ['RFI', 'CO', 'CHANGE_ORDER', 'Change Order',
                                         'COR', 'POTENTIAL_CO']
                    RETURN d.doc_type AS doc_type, count(d) AS cnt
                    ORDER BY cnt DESC
                    """,
                    source_project_ids=source_project_ids,
                )
                doc_type_counts = {r["doc_type"]: r["cnt"] for r in counts_result}

                # Top representative docs: those that received a response (real issues)
                top_result = session.run(
                    """
                    MATCH (p:Project)-[:HAS_DOCUMENT]->(d:CADocument)
                    WHERE p.project_id IN $source_project_ids
                      AND d.doc_type IN ['RFI', 'CO', 'CHANGE_ORDER', 'Change Order',
                                         'COR', 'POTENTIAL_CO']
                      AND d.summary IS NOT NULL
                      AND d.summary <> ''
                    RETURN d.doc_id       AS doc_id,
                           d.filename    AS filename,
                           d.doc_type    AS doc_type,
                           d.doc_number  AS doc_number,
                           d.summary     AS summary,
                           d.date_submitted AS date_submitted,
                           d.date_responded AS date_responded,
                           p.name        AS project_name,
                           p.project_number AS project_number
                    ORDER BY
                      CASE WHEN d.date_responded IS NOT NULL
                               AND d.date_responded <> '' THEN 0 ELSE 1 END,
                      d.date_submitted DESC
                    LIMIT $top_n
                    """,
                    source_project_ids=source_project_ids,
                    top_n=top_n,
                )

                return {
                    "doc_type_counts": doc_type_counts,
                    "top_docs": [r.data() for r in top_result],
                }

        return self._run_with_retry(_do)

    # ------------------------------------------------------------------
    # Document Intelligence — SpecSection / DrawingSheet enrichment
    # ------------------------------------------------------------------

    def upsert_spec_section(self, section_data: dict, project_id: str) -> None:
        if not self._driver:
            return
        def _do():
            with self._session() as session:
                session.run(
                    """
                    MERGE (s:SpecSection {section_number: $section_number, project_id: $project_id})
                    SET s.title           = $title,
                        s.source_doc_id   = $source_doc_id,
                        s.page_range      = $page_range,
                        s.content_summary = $content_summary,
                        s.embedding       = $embedding,
                        s.embedding_model = $embedding_model,
                        s.chunk_id        = $chunk_id
                    """,
                    **section_data,
                )
                if section_data.get("source_doc_id"):
                    session.run(
                        """
                        MATCH (d:CADocument {doc_id: $doc_id})
                        MATCH (s:SpecSection {section_number: $section_number, project_id: $project_id})
                        MERGE (d)-[:HAS_SECTION]->(s)
                        """,
                        doc_id=section_data["source_doc_id"],
                        section_number=section_data["section_number"],
                        project_id=project_id,
                    )
        self._run_with_retry(_do)

    def upsert_drawing_sheet(self, sheet_data: dict, project_id: str) -> None:
        if not self._driver:
            return
        def _do():
            with self._session() as session:
                session.run(
                    """
                    MERGE (ds:DrawingSheet {sheet_number: $sheet_number, project_id: $project_id})
                    SET ds.title           = $title,
                        ds.discipline      = $discipline,
                        ds.source_doc_id   = $source_doc_id,
                        ds.content_summary = $content_summary,
                        ds.embedding       = $embedding,
                        ds.embedding_model = $embedding_model,
                        ds.chunk_id        = $chunk_id
                    """,
                    **sheet_data,
                )
                if sheet_data.get("source_doc_id"):
                    session.run(
                        """
                        MATCH (d:CADocument {doc_id: $doc_id})
                        MATCH (ds:DrawingSheet {sheet_number: $sheet_number, project_id: $project_id})
                        MERGE (d)-[:HAS_SHEET]->(ds)
                        """,
                        doc_id=sheet_data["source_doc_id"],
                        sheet_number=sheet_data["sheet_number"],
                        project_id=project_id,
                    )
        self._run_with_retry(_do)

    def create_cross_reference(self, from_label: str, from_key: str, from_value: str,
                                rel_type: str, to_label: str, to_key: str,
                                to_value: str, project_id: str) -> None:
        if not self._driver:
            return
        def _do():
            with self._session() as session:
                session.run(
                    f"""
                    MATCH (a:{from_label} {{{from_key}: $from_val, project_id: $project_id}})
                    MATCH (b:{to_label} {{{to_key}: $to_val, project_id: $project_id}})
                    MERGE (a)-[:{rel_type}]->(b)
                    """,
                    from_val=from_value,
                    to_val=to_value,
                    project_id=project_id,
                )
        self._run_with_retry(_do)


kg_client = KnowledgeGraphClient()
