import os
import logging
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase

from ai_engine.engine import engine

logger = logging.getLogger(__name__)

class KnowledgeGraphClient:
    def __init__(self):
        uri = os.environ.get("NEO4J_URI")
        user = os.environ.get("NEO4J_USERNAME")
        password = os.environ.get("NEO4J_PASSWORD")

        if not uri or not user or not password:
            logger.warning("Neo4j credentials not fully provided in environment variables.")
            self._driver = None
        else:
            try:
                self._driver = GraphDatabase.driver(
                    uri,
                    auth=(user, password),
                    connection_timeout=5,
                    max_connection_lifetime=3600,
                )
            except Exception as e:
                logger.error(f"Failed to initialize Neo4j driver: {e}")
                self._driver = None

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

    def get_document_workflow(self, doc_type: str) -> List[Dict[str, Any]]:
        if not self._driver:
            return []

        query = """
        MATCH (d:DocumentType {type_id: $doc_type})-[:FOLLOWS_WORKFLOW]->(start:WorkflowStep)

        // Find the full path by following NEXT_STEP relationships
        // The *0.. signifies 0 or more hops
        MATCH path = (start)-[:NEXT_STEP*0..]->(step:WorkflowStep)

        // Ensure this path goes all the way to the end (a node with no NEXT_STEP)
        WHERE NOT (step)-[:NEXT_STEP]->()

        // Extract the nodes from the longest path
        WITH nodes(path) AS workflow_steps

        UNWIND workflow_steps AS step
        RETURN step.step_id AS step_id,
               step.name AS name,
               step.description AS description,
               step.responsible_party AS responsible_party,
               step.sequence AS sequence
        ORDER BY step.sequence ASC
        """

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

        Includes all node types: RFI, Submittal, ScheduleReview, PayApp,
        CostAnalysis, Party, SpecSection, DESIGN_FLAW, CORRECTIVE_ACTION.

        doc_type_filter: optional string — one of:
            "rfi", "submittal", "schedule_review", "pay_app", "cost_analysis"
            If None, all types are returned.
        """
        if not self._driver:
            return {"nodes": [], "edges": []}

        params: Dict[str, Any] = {"project_id": project_id}
        nodes: list = []
        edges: list = []

        # Determine which labels to query
        all_labels = {
            "rfi":             ("RFI",            "rfi_id"),
            "submittal":       ("Submittal",       "task_id"),
            "schedule_review": ("ScheduleReview",  "task_id"),
            "pay_app":         ("PayApp",          "task_id"),
            "cost_analysis":   ("CostAnalysis",    "task_id"),
        }

        active = (
            {doc_type_filter: all_labels[doc_type_filter]}
            if doc_type_filter and doc_type_filter in all_labels
            else all_labels
        )

        try:
            with self._driver.session() as session:

                # --- Document nodes (type-filtered) ---
                for dtype, (label, id_prop) in active.items():
                    result = session.run(
                        f"""
                        MATCH (d:{label} {{project_id: $project_id}})
                        RETURN d.{id_prop} AS node_id,
                               coalesce(d.doc_number, d.rfi_number, d.submittal_number,
                                        d.app_number, d.change_order_num, d.{id_prop}) AS label,
                               d.status_outcome AS status_outcome,
                               d.key_finding AS key_finding,
                               d.task_id AS task_id,
                               d.project_id AS project_id
                        """,
                        project_id=project_id,
                    )
                    for row in result:
                        nid = row.get("node_id") or row.get("task_id")
                        if not nid:
                            continue
                        nodes.append({
                            "id": f"{dtype[:3]}_{nid}",
                            "type": label.upper() if label == "RFI" else label,
                            "label": row.get("label") or nid,
                            "properties": {
                                "task_id":       row.get("task_id", ""),
                                "status_outcome": row.get("status_outcome", ""),
                                "key_finding":   (row.get("key_finding") or "")[:120],
                                "project_id":    row.get("project_id", ""),
                            },
                        })

                # --- Party nodes (always shown unless filtered to a non-Party type) ---
                party_result = session.run(
                    """
                    MATCH (d {project_id: $project_id})-[:SUBMITTED_BY]->(p:Party)
                    RETURN DISTINCT p.name AS name, p.party_type AS party_type
                    """,
                    project_id=project_id,
                )
                party_names_seen: set = set()
                for row in party_result:
                    name = row.get("name", "")
                    if name and name not in party_names_seen:
                        party_names_seen.add(name)
                        nodes.append({
                            "id": f"party_{name.replace(' ', '_')}",
                            "type": "PARTY",
                            "label": name,
                            "properties": {
                                "name":       name,
                                "party_type": row.get("party_type", ""),
                            },
                        })

                # --- SpecSection nodes ---
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
                            "id": f"ss_{sn}",
                            "type": "SPEC_SECTION",
                            "label": sn,
                            "properties": {
                                "section_number": sn,
                                "title": row.get("title", sn),
                            },
                        })

                # --- DESIGN_FLAW + CORRECTIVE_ACTION nodes (RFI-specific) ---
                if doc_type_filter in (None, "rfi"):
                    flaw_result = session.run(
                        "MATCH (f:DESIGN_FLAW {project_id: $project_id}) "
                        "RETURN f.flaw_id AS flaw_id, f.category AS category, "
                        "f.description AS description",
                        project_id=project_id,
                    )
                    for row in flaw_result:
                        fid = row.get("flaw_id")
                        if fid:
                            nodes.append({
                                "id": f"df_{fid}",
                                "type": "DESIGN_FLAW",
                                "label": row.get("category", "Flaw"),
                                "properties": {
                                    "flaw_id":     fid,
                                    "category":    row.get("category", ""),
                                    "description": (row.get("description") or "")[:120],
                                },
                            })

                    action_result = session.run(
                        "MATCH (a:CORRECTIVE_ACTION {project_id: $project_id}) "
                        "RETURN a.action_id AS action_id, a.action AS action",
                        project_id=project_id,
                    )
                    for row in action_result:
                        aid = row.get("action_id")
                        if aid:
                            nodes.append({
                                "id": f"ca_{aid}",
                                "type": "CORRECTIVE_ACTION",
                                "label": (row.get("action") or "Action")[:40],
                                "properties": {
                                    "action_id": aid,
                                    "action":    row.get("action", ""),
                                },
                            })

                # --- Edges ---
                # Build a set of node IDs for fast membership check
                node_ids = {n["id"] for n in nodes}

                edge_queries = [
                    # SUBMITTED_BY
                    """
                    MATCH (d {project_id: $project_id})-[:SUBMITTED_BY]->(p:Party)
                    RETURN id(d) AS src_int_id, d.task_id AS src_task_id,
                           d.rfi_id AS src_rfi_id,
                           labels(d) AS src_labels,
                           p.name AS party_name, 'SUBMITTED_BY' AS rel_type
                    """,
                    # REFERENCES_SPEC
                    """
                    MATCH (d {project_id: $project_id})-[:REFERENCES_SPEC]->(s:SpecSection)
                    RETURN id(d) AS src_int_id, d.task_id AS src_task_id,
                           d.rfi_id AS src_rfi_id,
                           labels(d) AS src_labels,
                           s.section_number AS spec_number, 'REFERENCES_SPEC' AS rel_type
                    """,
                    # REVEALS (RFI → DESIGN_FLAW)
                    """
                    MATCH (r:RFI {project_id: $project_id})-[:REVEALS]->(f:DESIGN_FLAW)
                    RETURN r.rfi_id AS rfi_id, f.flaw_id AS flaw_id, 'REVEALS' AS rel_type
                    """,
                    # SUGGESTS (DESIGN_FLAW → CORRECTIVE_ACTION)
                    """
                    MATCH (f:DESIGN_FLAW {project_id: $project_id})-[:SUGGESTS]->(a:CORRECTIVE_ACTION)
                    RETURN f.flaw_id AS flaw_id, a.action_id AS action_id, 'SUGGESTS' AS rel_type
                    """,
                ]

                def _label_to_dtype(labels_list: list) -> str:
                    for lbl in (labels_list or []):
                        ll = lbl.lower()
                        if ll == "rfi":
                            return "rfi"
                        if ll == "submittal":
                            return "sub"
                        if ll == "schedulereview":
                            return "sch"
                        if ll == "payapp":
                            return "pay"
                        if ll == "costanalysis":
                            return "cos"
                    return "doc"

                for eq in edge_queries:
                    try:
                        eresult = session.run(eq, project_id=project_id)
                        for row in eresult:
                            rel = row.get("rel_type", "RELATED")

                            if rel == "REVEALS":
                                src = f"rfi_{row.get('rfi_id')}"
                                tgt = f"df_{row.get('flaw_id')}"
                            elif rel == "SUGGESTS":
                                src = f"df_{row.get('flaw_id')}"
                                tgt = f"ca_{row.get('action_id')}"
                            elif rel in ("SUBMITTED_BY", "REFERENCES_SPEC"):
                                task_id_val = row.get("src_task_id") or row.get("src_rfi_id")
                                prefix = _label_to_dtype(list(row.get("src_labels") or []))
                                # For RFI the prefix is "rfi"
                                if prefix == "rfi":
                                    src = f"rfi_{task_id_val}"
                                else:
                                    src = f"{prefix}_{task_id_val}"
                                if rel == "SUBMITTED_BY":
                                    party_name = row.get("party_name", "")
                                    tgt = f"party_{party_name.replace(' ', '_')}"
                                else:
                                    tgt = f"ss_{row.get('spec_number')}"
                            else:
                                continue

                            if src in node_ids and tgt in node_ids:
                                edges.append({"source": src, "target": tgt, "type": rel})
                    except Exception as eq_err:
                        logger.debug(f"get_full_project_graph edge query failed: {eq_err}")

        except Exception as e:
            logger.error(f"get_full_project_graph failed: {e}")
            return {"nodes": [], "edges": []}

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Semantic search across graph
    # ------------------------------------------------------------------

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
                        "question":   (r.get("question") or "")[:200],
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

        count_queries = [
            ("rfi_count",             "MATCH (r:RFI {project_id: $p}) RETURN count(r) AS c"),
            ("submittal_count",       "MATCH (s:Submittal {project_id: $p}) RETURN count(s) AS c"),
            ("schedule_review_count", "MATCH (sr:ScheduleReview {project_id: $p}) RETURN count(sr) AS c"),
            ("payapp_count",          "MATCH (pa:PayApp {project_id: $p}) RETURN count(pa) AS c"),
            ("cost_analysis_count",   "MATCH (ca:CostAnalysis {project_id: $p}) RETURN count(ca) AS c"),
            ("unique_spec_sections",  "MATCH (s:SpecSection {project_id: $p}) RETURN count(s) AS c"),
        ]

        try:
            with self._driver.session() as session:
                for key, cypher in count_queries:
                    rec = session.run(cypher, p=project_id).single()
                    if rec:
                        stats[key] = rec["c"]

                # Unique parties (name distinct, across all doc types for this project)
                party_rec = session.run(
                    """
                    MATCH (d {project_id: $p})-[:SUBMITTED_BY]->(party:Party)
                    RETURN count(DISTINCT party.name) AS c
                    """,
                    p=project_id,
                ).single()
                if party_rec:
                    stats["unique_parties"] = party_rec["c"]

                # Top design flaws
                flaws = session.run(
                    """
                    MATCH (r:RFI {project_id: $p})-[:REVEALS]->(f:DESIGN_FLAW)
                    RETURN f.category AS category, count(r) AS count
                    ORDER BY count DESC
                    LIMIT 5
                    """,
                    p=project_id,
                )
                stats["top_design_flaws"] = [
                    {"category": row["category"], "count": row["count"]}
                    for row in flaws
                ]

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

    def search_project_documents(
        self,
        query: str,
        project_id: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
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


kg_client = KnowledgeGraphClient()
