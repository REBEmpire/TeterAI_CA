import re

with open('src/ui/api/routes.py', 'r') as f:
    content = f.read()

# 1. Update kg_search to support mode param
kg_search_old = r"""@router\.get\("/knowledge-graph/search", tags=\["knowledge-graph"\]\)\ndef kg_search\(\n    q: str = Query\(\.\.\., description="Semantic search query"\),\n    project_id: Optional\[str\] = Query\(None, description="Optional project filter"\),\n    top_k: int = Query\(10, ge=1, le=50\),\n    current_user: Annotated\[UserInfo, Depends\(require_auth\)\] = None,\n\):\n    \"\"\"Semantic search across the knowledge graph using vector embeddings\.\"\"\"\n    from knowledge_graph\.client import kg_client\n    return kg_client\.semantic_search_graph\(\n        query=q,\n        project_id=project_id,\n        top_k=top_k\n    \)"""

kg_search_new = """@router.get("/knowledge-graph/search", tags=["knowledge-graph"])
def kg_search(
    q: str = Query(..., description="Search query"),
    mode: str = Query("semantic", description="Search mode: 'semantic' or 'keyword'"),
    project_id: Optional[str] = Query(None, description="Optional project filter"),
    top_k: int = Query(10, ge=1, le=50),
    current_user: Annotated[UserInfo, Depends(require_auth)] = None,
):
    \"\"\"Search across the knowledge graph.\"\"\"
    from knowledge_graph.client import kg_client

    if mode == "keyword":
        return kg_client.keyword_search_graph(
            query=q,
            project_id=project_id,
            top_k=top_k
        )
    else:
        return kg_client.semantic_search_graph(
            query=q,
            project_id=project_id,
            top_k=top_k
        )"""

content = re.sub(kg_search_old, kg_search_new, content)

# 2. Add summary_full and update truncation (truncation happens in knowledge_graph/client.py, but we'll check where it happens in API too)
# Actually, the requirement says "Expand API summary truncation - File: src/ui/api/routes.py - Current: Summary text truncated to 120 chars for graph nodes (line ~746), questions to 200 chars for search"
# Let's find where 120 is in routes.py
content = re.sub(r"\[:120\]", "[:300]", content)
content = re.sub(r"\[:200\]", "", content) # Remove 200 char truncation

with open('src/ui/api/routes.py', 'w') as f:
    f.write(content)
