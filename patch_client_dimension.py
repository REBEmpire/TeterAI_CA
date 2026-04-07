import re

with open('src/knowledge_graph/client.py', 'r') as f:
    content = f.read()

# Add dimension validation to _do inside upsert_document
upsert_match = re.search(r"        def _do\(session\):\n            doc_id = doc_data\.get\(\"doc_id\"\)", content)
if upsert_match:
    validation = """        def _do(session):
            embedding = doc_data.get("embedding")
            if embedding and len(embedding) != 768:
                logger.warning(f"Embedding dimension mismatch in upsert_document! Expected 768, got {len(embedding)}. This may fail to index.")

            doc_id = doc_data.get("doc_id")"""
    content = content[:upsert_match.start()] + validation + content[upsert_match.end():]

# Same for upsert_rfi
rfi_match = re.search(r"        def _do\(session\):\n            cypher = \"\"\"\n            MERGE \(r:RFI \{rfi_id: \$rfi_id\}\)", content)
if rfi_match:
    validation = """        def _do(session):
            embedding = rfi_data.get("embedding")
            if embedding and len(embedding) != 768:
                logger.warning(f"Embedding dimension mismatch in upsert_rfi! Expected 768, got {len(embedding)}.")

            cypher = \"\"\"
            MERGE (r:RFI {rfi_id: $rfi_id})"""
    content = content[:rfi_match.start()] + validation + content[rfi_match.end():]

with open('src/knowledge_graph/client.py', 'w') as f:
    f.write(content)
