import re

with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

# I see it now.
# Earlier I replaced `try: self._kg.upsert_document... except ...`
# The problem is the line numbers. Wait, the syntax error says `SyntaxError: expected 'except' or 'finally' block` around `spec_sections =`.
# This means there is an unmatched `try:` BEFORE `spec_sections = ...`.
# Let's completely restore that block to its working state and then just add my SpecSection code safely.

content = re.sub(r"        # --- Write to Neo4j ---.*?        # Link to Spec Sections",
"""        # --- Write to Neo4j ---
        try:
            self._kg.upsert_document(doc_data, project_id)
        except Exception as e:
            logger.error(f"Failed to upsert document {doc_id}: {e}")
            raise e

        # Link to Spec Sections""",
content, flags=re.DOTALL)

with open('src/knowledge_graph/ingestion.py', 'w') as f:
    f.write(content)
