import re

with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

# 1. Update embedding service preference in ingestion (or ensure it's tracked)
# Ingestion already tracks embedding_model, but we need to track provider name
# Find line 420: "embedding_model": "text-embedding",
# Actually let's look at what's there
content = re.sub(r'"embedding_model":\s*"text-embedding",', '"embedding_model": self._embed_service.primary_provider,', content)

# 2. Add SpecSection linking
# Around line 442: self._kg.upsert_document(doc_data, project_id)
spec_link_code = """
        # Link to Spec Sections
        spec_sections = (ai_data or {}).get("spec_sections", [])
        if spec_sections and isinstance(spec_sections, list):
            for section_number in spec_sections:
                if isinstance(section_number, str) and len(section_number) > 3:
                    try:
                        self._kg._run_with_retry(lambda session: session.run(\"\"\"
                        MATCH (d:CADocument {doc_id: $doc_id})
                        MERGE (s:SpecSection {section_number: $section_number})
                        MERGE (d)-[:REFERENCES_SPEC]->(s)
                        \"\"\", doc_id=doc_id, section_number=section_number))
                    except Exception as e:
                        logger.warning(f"Failed to link document {doc_id} to spec section {section_number}: {e}")
"""

# Find upsert_document call
upsert_match = re.search(r"self\._kg\.upsert_document\(doc_data, project_id\)", content)
if upsert_match:
    # Insert after
    content = content[:upsert_match.end()] + spec_link_code + content[upsert_match.end():]

with open('src/knowledge_graph/ingestion.py', 'w') as f:
    f.write(content)
