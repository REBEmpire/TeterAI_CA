import re

with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

spec_code = """
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

content = content.replace('            self._kg.upsert_document(doc_data, project_id)', '            self._kg.upsert_document(doc_data, project_id)\n' + spec_code)

with open('src/knowledge_graph/ingestion.py', 'w') as f:
    f.write(content)
