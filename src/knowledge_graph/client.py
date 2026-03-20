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
            self._driver = GraphDatabase.driver(uri, auth=(user, password))

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

kg_client = KnowledgeGraphClient()
