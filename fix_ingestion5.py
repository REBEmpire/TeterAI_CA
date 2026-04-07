import re

with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

# Oh, the original code had a try-except around the entire # Parties block!
# Let's fix the indentation or just remove the try-except if it's broken.
# Look at line 441. It has `try: self._kg.upsert_document...`. Then I added `except Exception...` and closed it. But line 472 is an orphaned `except Exception as e:`.
# Ah! The original code was:
# try:
#     self._kg.upsert_document(...)
#     # Parties
#     ...
# except Exception as e:
#     logger.error(f"Failed to upsert...")

content = content.replace("""        try:
            self._kg.upsert_document(doc_data, project_id)
        except Exception as e:
            logger.error(f"Failed to upsert document {doc_id}: {e}")
            raise e

        # Link to Spec Sections""", """        try:
            self._kg.upsert_document(doc_data, project_id)

            # Link to Spec Sections""")

with open('src/knowledge_graph/ingestion.py', 'w') as f:
    f.write(content)
