import re

with open('src/knowledge_graph/client.py', 'r') as f:
    content = f.read()

keyword_search_func = """
    def keyword_search_graph(self, query: str, project_id: Optional[str] = None, top_k: int = 10) -> List[Dict[str, Any]]:
        \"\"\"
        Search the graph using Neo4j full-text indexes instead of vector embeddings.
        \"\"\"
        if not self._driver:
            return []

        def _do(session):
            cypher = \"\"\"
            CALL db.index.fulltext.queryNodes('ca_document_fulltext', $query) YIELD node, score
            \"\"\"
            if project_id:
                cypher += " MATCH (node)-[:BELONGS_TO]->(p:Project {project_id: $project_id})"
            else:
                cypher += " MATCH (node)-[:BELONGS_TO]->(p:Project)"

            cypher += \"\"\"
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
            \"\"\"

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

"""

if "def keyword_search_graph" not in content:
    content = content.replace("    def semantic_search_graph(", keyword_search_func + "    def semantic_search_graph(")

with open('src/knowledge_graph/client.py', 'w') as f:
    f.write(content)
