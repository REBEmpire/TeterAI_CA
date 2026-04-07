import re

with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

# Fix embedding_model to use a property or string
# EmbeddingService might not expose primary_provider as a simple property, let's just use self._embed_service._primary.value
content = content.replace('self._embed_service.primary_provider', 'self._embed_service._primary.value')

with open('src/knowledge_graph/ingestion.py', 'w') as f:
    f.write(content)
