import re

with open('tests/test_kg_ingestion.py', 'r') as f:
    content = f.read()

# Fix test: document_is_metadata_only was probably added by someone else recently
# We just need the test to mock it so it returns False.
content = content.replace("kg.document_exists.return_value = True  # already in graph", "kg.document_exists.return_value = True  # already in graph\n    kg.document_is_metadata_only.return_value = False")

with open('tests/test_kg_ingestion.py', 'w') as f:
    f.write(content)
