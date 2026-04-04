with open('src/embeddings/ingest_embedder.py', 'r') as f:
    content = f.read()

content = content.replace("from document_intelligence.extractors.pdf_extractor import extract_text_from_pdf", "from document_intelligence.extractors.pdf_extractor import PdfExtractor")

replacement = """        if len(all_text) < 100 and attachment_local_paths:
            for path in attachment_local_paths:
                if path.lower().endswith('.pdf'):
                    extractor = PdfExtractor()
                    pages = extractor.extract_pages(path)
                    for page in pages:
                        if page.get("text"):
                            all_text += "\n" + page.get("text")"""

target = """        if len(all_text) < 100 and attachment_local_paths:
            for path in attachment_local_paths:
                if path.lower().endswith('.pdf'):
                    extracted = extract_text_from_pdf(path)
                    all_text += "\n" + extracted"""

content = content.replace(target, replacement)

with open('src/embeddings/ingest_embedder.py', 'w') as f:
    f.write(content)
