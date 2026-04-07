import re

with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

# Fix the syntax error in ingestion.py
# The try block I added doesn't have an except block in the regex patching correctly?
# Wait, I added it via string replacement. Let's look at it.

"""
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

# Let's just output the relevant lines to see the error
