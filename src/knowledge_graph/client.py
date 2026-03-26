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
        task_id: str,
        agent_id: str,
        correction_type: str,
        original_text: str,
        edited_text: str,
        reviewed_by: str = "",
        event_id: str = "",
    ) -> None:
        if not self._driver:
            return

        import uuid as _uuid
        query = """
        CREATE (c:CorrectionEvent {
            event_id: $event_id,
            agent_id: $agent_id,
            task_id: $task_id,
            original_text: $original_text,
            corrected_text: $corrected_text,
            correction_type: $correction_type,
            reviewed_by: $reviewed_by,
            timestamp: datetime()
        })
        WITH c
        MATCH (a:Agent {agent_id: $agent_id})-[:HAS_RULE]->(r:PlaybookRule)
        WHERE r.priority = 1
        CREATE (c)-[:UPDATES]->(r)
        """

        with self._driver.session() as session:
            session.run(query, {
                "event_id": event_id or str(_uuid.uuid4()),
                "agent_id": agent_id,
                "task_id": task_id,
                "original_text": original_text,
                "corrected_text": edited_text,
                "correction_type": correction_type,
                "reviewed_by": reviewed_by,
            })

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


kg_client = KnowledgeGraphClient()
