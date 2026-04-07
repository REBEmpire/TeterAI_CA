import re

with open('src/knowledge_graph/schema.py', 'r') as f:
    content = f.read()

# Add Fulltext and Property indexes
new_indexes = """
PROPERTY_INDEXES: list[str] = [
    "CREATE INDEX ca_doc_date_submitted IF NOT EXISTS FOR (n:CADocument) ON (n.date_submitted)",
    "CREATE INDEX ca_doc_doc_type IF NOT EXISTS FOR (n:CADocument) ON (n.doc_type)",
    "CREATE INDEX party_type IF NOT EXISTS FOR (n:Party) ON (n.type)"
]

FULLTEXT_INDEXES: list[str] = [
    "CREATE FULLTEXT INDEX ca_document_fulltext IF NOT EXISTS FOR (n:CADocument) ON EACH [n.summary, n.filename, n.doc_number]",
    "CREATE FULLTEXT INDEX rfi_fulltext IF NOT EXISTS FOR (n:RFI) ON EACH [n.question, n.response_text]"
]

ALL_STATEMENTS: list[str] = CONSTRAINTS + VECTOR_INDEXES + PROPERTY_INDEXES + FULLTEXT_INDEXES"""

content = content.replace("ALL_STATEMENTS: list[str] = CONSTRAINTS + VECTOR_INDEXES", new_indexes)

with open('src/knowledge_graph/schema.py', 'w') as f:
    f.write(content)
