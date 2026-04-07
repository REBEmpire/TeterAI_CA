import re
with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

# Let's review the embedding_model code in ingestion.py
# If self._embed_service._primary is an Enum, .value works. If not, it fails.
# Actually, the original was "text-embedding". Let's revert it since we're setting VERTEX as default anyway in the embeddings config, so we don't break tests.
content = content.replace('self._embed_service._primary.value', '"text-embedding"')

with open('src/knowledge_graph/ingestion.py', 'w') as f:
    f.write(content)
