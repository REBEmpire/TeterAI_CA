import re

with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

# Fix the try block missing an except
content = content.replace("""        try:
            self._kg.upsert_document(doc_data, project_id)
        # Link to Spec Sections""", """        try:
            self._kg.upsert_document(doc_data, project_id)
        except Exception as e:
            logger.error(f"Failed to upsert document {doc_id}: {e}")
            raise e

        # Link to Spec Sections""")

with open('src/knowledge_graph/ingestion.py', 'w') as f:
    f.write(content)
