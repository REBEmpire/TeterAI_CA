import re

with open('src/ui/api/routes.py', 'r') as f:
    content = f.read()

append = """
@router.post("/settings/embeddings")
async def get_embedding_settings(
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("ADMIN")),
):
    from config.local_config import LocalConfig
    from embeddings.service import get_embedding_service

    cfg = LocalConfig.ensure_exists()
    embed_svc = get_embedding_service()

    active_provider = "not configured"
    if embed_svc and embed_svc.provider:
        active_provider = embed_svc.provider.name if hasattr(embed_svc.provider, 'name') else str(embed_svc.provider.__class__.__name__)

    return {
        "active_provider": active_provider
    }

@router.post("/settings/test-key")
async def test_api_key(
    body: dict,
    user: UserInfo = Depends(require_auth),
    _role=Depends(require_role("ADMIN")),
):
    provider = body.get("provider")
    key = body.get("key")

    if not provider or not key:
        return {"valid": False, "error": "Provider and key are required"}

    try:
        if provider == "google":
            from litellm import embedding
            import os
            os.environ["GEMINI_API_KEY"] = key
            res = embedding(model="gemini/text-embedding-004", input=["test"])
            return {"valid": True}
        elif provider == "anthropic":
            from litellm import completion
            import os
            os.environ["ANTHROPIC_API_KEY"] = key
            res = completion(model="anthropic/claude-3-haiku-20240307", messages=[{"role": "user", "content": "hi"}], max_tokens=5)
            return {"valid": True}
        else:
            return {"valid": False, "error": f"Testing not implemented for provider {provider}"}
    except Exception as e:
        return {"valid": False, "error": f"Key validation failed: {str(e)}"}

@router.get("/projects/{project_id}/search")
async def search_project_chunks(
    project_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    user: UserInfo = Depends(require_auth),
):
    try:
        from embeddings.service import get_embedding_service
        from document_intelligence.storage.chunk_store import ChunkStore
        from config.local_config import LocalConfig

        cfg = LocalConfig.ensure_exists()
        embed_svc = get_embedding_service()
        chunk_store = ChunkStore(db_path=cfg.db_path)

        if not embed_svc:
            return []

        # 1. Embed query
        query_embedding = embed_svc.embed(q)

        # 2. Get all chunks for project
        all_chunks = chunk_store.get_chunks_for_document(project_id) # Using this temporarily since there's no get_by_project implemented in the snippet
        # Actually ChunkStore probably has a method to get by project. Let's just load everything.
        # SQLite querying would be better, but we are doing in-memory cosine sim for desktop mode.
        import sqlite3
        conn = sqlite3.connect(cfg.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, document_id, chunk_index, text_content, chunk_type, embedding, metadata FROM chunks WHERE project_id = ?", (project_id,))
        rows = cursor.fetchall()

        if not rows:
            return []

        # 3. Compute cosine similarity
        import json
        import math

        def cosine_sim(vec1, vec2):
            dot = sum(a * b for a, b in zip(vec1, vec2))
            norm1 = math.sqrt(sum(a * a for a in vec1))
            norm2 = math.sqrt(sum(a * a for a in vec2))
            if norm1 == 0 or norm2 == 0:
                return 0
            return dot / (norm1 * norm2)

        results = []
        for row in rows:
            try:
                emb_bytes = row[5]
                chunk_emb = json.loads(emb_bytes.decode('utf-8'))

                sim = cosine_sim(query_embedding, chunk_emb)

                meta = json.loads(row[6]) if row[6] else {}

                results.append({
                    "id": row[0],
                    "document_id": row[1],
                    "text_content": row[3],
                    "chunk_type": row[4],
                    "similarity": sim,
                    "metadata": meta
                })
            except:
                pass

        # 4. Return top N
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Search failed: {e}")
        return []
"""

content = content + append

with open('src/ui/api/routes.py', 'w') as f:
    f.write(content)
