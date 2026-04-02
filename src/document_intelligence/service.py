# src/document_intelligence/service.py
"""
Document Intelligence Service — pipeline orchestrator.

Coordinates the full processing pipeline:
  1. Register document in SQLite
  2. Extract text page-by-page (pypdf + OCR fallback)
  3. Detect structure (TOC for specs, sheet index for drawings)
  4. Validate structure (cross-reference TOC/index with actual content)
  5. Create chunks in SQLite
  6. Enrich Knowledge Graph with SpecSection/DrawingSheet nodes
  7. Finalize document status
"""
import json
import logging
import re
from typing import Optional

from ai_engine.engine import engine
from ai_engine.models import AIRequest, CapabilityClass

from document_intelligence.extractors.pdf_extractor import PdfExtractor
from document_intelligence.extractors.bookmark_parser import BookmarkParser
from document_intelligence.parsers.spec_parser import SpecParser
from document_intelligence.parsers.drawing_parser import DrawingParser
from document_intelligence.validators.spec_validator import SpecValidator
from document_intelligence.validators.drawing_validator import DrawingValidator
from document_intelligence.storage.chunk_store import ChunkStore

logger = logging.getLogger(__name__)

# Keywords to classify document type from filename
_SPEC_KEYWORDS = {"spec", "specification", "project manual", "technical spec"}
_DRAWING_KEYWORDS = {"drawing", "plan", "sheet", "dwg", "architectural", "structural"}

# Cross-reference patterns in text
_DRAWING_REF_RE = re.compile(r"(?:See |Refer to |Per )?(?:Drawing |Sheet |Dwg\.?\s*)([A-Z]{1,2}\d+(?:\.\d+)?)", re.IGNORECASE)
_SPEC_REF_RE = re.compile(r"(?:See |Refer to |Per )?(?:Section |Spec\.?\s*)(\d{2}\s?\d{2}\s?\d{2})", re.IGNORECASE)


class DocumentIntelligenceService:
    """Orchestrate document processing pipeline."""

    def __init__(
        self,
        chunk_store: ChunkStore,
        kg_client=None,
    ):
        self._store = chunk_store
        self._kg = kg_client
        self._extractor = PdfExtractor()
        self._bookmark_parser = BookmarkParser()
        self._spec_parser = SpecParser()
        self._drawing_parser = DrawingParser()
        self._spec_validator = SpecValidator()
        self._drawing_validator = DrawingValidator()

    def classify_document(self, filename: str) -> Optional[str]:
        """Classify a document as spec_book or drawing_set from its filename."""
        lower = filename.lower()
        for kw in _SPEC_KEYWORDS:
            if kw in lower:
                return "spec_book"
        for kw in _DRAWING_KEYWORDS:
            if kw in lower:
                return "drawing_set"
        return None

    def process_document(
        self,
        project_id: str,
        pdf_path: str,
        file_name: str,
        doc_type: str,
        neo4j_doc_id: str,
    ) -> dict:
        """
        Process a single PDF document through the full pipeline.

        Args:
            project_id:   Project ID (e.g. "11900")
            pdf_path:     Local path to the PDF file
            file_name:    Original filename
            doc_type:     "spec_book" or "drawing_set"
            neo4j_doc_id: Corresponding CADocument.doc_id in Neo4j

        Returns:
            {document_id, status, chunks_created, errors}
        """
        # Skip if already indexed
        if self._store.is_document_indexed(neo4j_doc_id):
            logger.info(f"Skipping already-indexed document: {file_name}")
            return {"document_id": None, "status": "skipped", "chunks_created": 0, "errors": []}

        errors = []

        # Step 1: Register document
        total_pages = self._extractor.get_page_count(pdf_path)
        import os
        file_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0

        doc_id = self._store.register_document(
            project_id=project_id,
            file_path=pdf_path,
            file_name=file_name,
            doc_type=doc_type,
            total_pages=total_pages,
            file_size_bytes=file_size,
            neo4j_doc_id=neo4j_doc_id,
        )

        # Step 2: Extract pages
        pages = self._extractor.extract_pages(pdf_path)
        if not pages:
            self._store.finalize_document(doc_id, status="failed")
            return {"document_id": doc_id, "status": "failed", "chunks_created": 0,
                    "errors": ["No pages extracted"]}

        # Log extraction results
        for page in pages:
            self._store.log_page_extraction(
                document_id=doc_id,
                page_number=page["page_number"],
                extraction_method=page["extraction_method"],
                char_count=page["char_count"],
                flagged=page["flagged"],
            )

        # Step 3-5: Process by type
        if doc_type == "spec_book":
            chunks_created = self._process_spec_book(doc_id, project_id, pdf_path, pages, neo4j_doc_id, errors)
        elif doc_type == "drawing_set":
            chunks_created = self._process_drawing_set(doc_id, project_id, pdf_path, pages, neo4j_doc_id, errors)
        else:
            self._store.finalize_document(doc_id, status="failed")
            return {"document_id": doc_id, "status": "failed", "chunks_created": 0,
                    "errors": [f"Unknown doc_type: {doc_type}"]}

        # Step 7: Finalize
        status = "indexed" if chunks_created > 0 else "failed"
        self._store.finalize_document(doc_id, status=status)

        return {
            "document_id": doc_id,
            "status": status,
            "chunks_created": chunks_created,
            "errors": errors,
        }

    def _process_spec_book(
        self, doc_id: str, project_id: str, pdf_path: str,
        pages: list[dict], neo4j_doc_id: str, errors: list,
    ) -> int:
        """Process a spec book: detect TOC, validate, chunk, enrich KG."""
        chunks_created = 0

        # Try bookmark-first TOC detection
        toc_bookmark = self._bookmark_parser.find_toc_bookmark(pdf_path)
        toc_pages_text = []

        if toc_bookmark:
            boundaries = self._bookmark_parser.get_section_boundaries(pdf_path)
            # Get text from TOC pages
            toc_start = toc_bookmark["page_number"]
            for page in pages:
                pg = page["page_number"] - 1  # 0-based
                if pg >= toc_start:
                    toc_pages_text.append(page["text"])
                    # Stop at next major section
                    if pg > toc_start + 20:
                        break

        if not toc_pages_text:
            # Fallback: scan first 30 pages for TOC-like content
            for page in pages[:30]:
                toc_pages_text.append(page["text"])

        # Parse TOC lines
        all_lines = []
        for text in toc_pages_text:
            all_lines.extend(text.split("\n"))
        toc_sections = self._spec_parser.parse_toc_lines(all_lines)

        if not toc_sections:
            # Pattern-matching fallback: scan all pages for section headers
            toc_sections = self._scan_body_headers(pages)

        if not toc_sections:
            errors.append("No spec sections detected via TOC or pattern matching")
            return 0

        # Validate & detect page offset
        page_text_map = {p["page_number"]: p["text"] for p in pages}
        page_offset = self._spec_validator.detect_page_offset(toc_sections, page_text_map)
        validation_results = self._spec_validator.validate_sections(
            toc_sections, page_text_map, page_offset
        )
        validation_report = self._spec_validator.generate_report(validation_results)

        # Split pages into section chunks
        section_chunks = self._spec_parser.split_pages_by_sections(
            pages, toc_sections, page_offset
        )

        # Quality check: TOC page numbers may be section-relative (not absolute PDF
        # pages). Detect two failure modes and fall back to body-text header scanning:
        #   1. Low valid-span ratio — many sections map to the same TOC page (e.g.
        #      multiple entries at page 7), producing chunks with page_end < page_start.
        #   2. Sparse coverage — too few sections for the document length (average
        #      section > 20 pages), or one section dominates >80% of the document.
        valid_count = sum(1 for c in section_chunks if c["page_start"] <= c["page_end"])
        total_doc_pages = len(pages)
        largest_span = max(
            (c["page_end"] - c["page_start"] + 1 for c in section_chunks if c["page_start"] <= c["page_end"]),
            default=0,
        )
        too_sparse = (
            total_doc_pages > 50
            and len(section_chunks) < total_doc_pages / 20  # avg >20 pages/section
        )
        dominant_section = largest_span > total_doc_pages * 0.8

        if section_chunks and (
            valid_count < len(section_chunks) * 0.5
            or too_sparse
            or dominant_section
        ):
            logger.info(
                "TOC page mapping quality low (%d/%d valid spans) — trying body-text header scan",
                valid_count, len(section_chunks),
            )
            body_sections = self._scan_body_headers(pages)
            if body_sections:
                body_chunks = self._spec_parser.split_pages_by_sections(pages, body_sections, 0)
                body_valid = sum(1 for c in body_chunks if c["page_start"] <= c["page_end"])
                if body_valid > valid_count:
                    logger.info(
                        "Body-text detection better: %d valid spans (was %d)",
                        body_valid, valid_count,
                    )
                    toc_sections = body_sections
                    page_offset = 0
                    section_chunks = body_chunks
                    validation_results = self._spec_validator.validate_sections(
                        toc_sections, page_text_map, 0
                    )
                    validation_report = self._spec_validator.generate_report(validation_results)

        # Create chunks and enrich KG
        for chunk_data in section_chunks:
            # Generate summary
            summary = self._generate_summary(chunk_data["content"][:3000], chunk_data["title"])
            # Generate embedding
            embedding = self._generate_embedding(summary)

            # Find verification status
            v_status = "matched"
            for vr in validation_results:
                if vr["section_number"] == chunk_data["section_number"]:
                    v_status = vr["status"]
                    break

            chunk_id = self._store.add_chunk(
                document_id=doc_id,
                project_id=project_id,
                chunk_type="spec_section",
                identifier=chunk_data["section_number"],
                title=chunk_data["title"],
                content=chunk_data["content"],
                content_summary=summary,
                page_start=chunk_data["page_start"],
                page_end=chunk_data["page_end"],
                division=chunk_data["division"],
                verification_status=v_status,
            )
            chunks_created += 1

            # Enrich KG
            if self._kg:
                self._kg.upsert_spec_section({
                    "section_number": chunk_data["section_number"],
                    "title": chunk_data["title"],
                    "project_id": project_id,
                    "source_doc_id": neo4j_doc_id,
                    "page_range": f"pages {chunk_data['page_start']}-{chunk_data['page_end']}",
                    "content_summary": summary,
                    "embedding": embedding,
                    "embedding_model": "text-embedding",
                    "chunk_id": chunk_id,
                }, project_id)

        # Parse cross-references
        if self._kg:
            self._create_cross_references(section_chunks, project_id)

        return chunks_created

    def _process_drawing_set(
        self, doc_id: str, project_id: str, pdf_path: str,
        pages: list[dict], neo4j_doc_id: str, errors: list,
    ) -> int:
        """Process a drawing set: detect sheet index, validate, chunk, enrich KG."""
        chunks_created = 0

        # Try bookmark-first sheet index detection
        index_bookmark = self._bookmark_parser.find_sheet_index_bookmark(pdf_path)
        index_text_lines = []

        if index_bookmark:
            idx_page = index_bookmark["page_number"]
            for page in pages:
                pg = page["page_number"] - 1
                if pg >= idx_page and pg <= idx_page + 5:
                    index_text_lines.extend(page["text"].split("\n"))
        else:
            # Scan first 10 pages
            for page in pages[:10]:
                index_text_lines.extend(page["text"].split("\n"))

        sheet_index = self._drawing_parser.parse_sheet_index_lines(index_text_lines)

        # Detect title blocks on every page
        detected_sheets = []
        for page in pages:
            tb = self._drawing_parser.detect_title_block(page["text"])
            if tb:
                detected_sheets.append(tb["sheet_number"])

        # Validate
        if sheet_index:
            reconciliation = self._drawing_validator.reconcile(sheet_index, detected_sheets)
            recon_report = self._drawing_validator.generate_report(reconciliation)
        else:
            # No index found — use detected sheets directly
            reconciliation = {"matched": [], "index_only": [], "document_only": detected_sheets}
            recon_report = self._drawing_validator.generate_report(reconciliation)
            # Build sheet_index from detected sheets
            sheet_index = [
                {"sheet_number": sn, "title": "", "discipline": self._drawing_parser.infer_discipline(sn)}
                for sn in detected_sheets
            ]

        self._store.finalize_document(
            doc_id,
            status="processing",
            reconciliation_summary=json.dumps(recon_report),
        )

        # Split pages by sheets
        sheet_chunks = self._drawing_parser.split_pages_by_sheets(pages, sheet_index)

        for chunk_data in sheet_chunks:
            summary = self._generate_summary(
                chunk_data["content"][:3000] if chunk_data["content"] else "",
                f"Drawing Sheet {chunk_data['sheet_number']}: {chunk_data['title']}",
            )
            embedding = self._generate_embedding(summary)
            v_status = self._drawing_validator.get_verification_status(
                chunk_data["sheet_number"], reconciliation
            )

            chunk_id = self._store.add_chunk(
                document_id=doc_id,
                project_id=project_id,
                chunk_type="drawing_sheet",
                identifier=chunk_data["sheet_number"],
                title=chunk_data["title"],
                content=chunk_data.get("content", ""),
                content_summary=summary,
                page_start=chunk_data.get("page_start"),
                page_end=chunk_data.get("page_end"),
                discipline=chunk_data["discipline"],
                verification_status=v_status,
            )
            chunks_created += 1

            if self._kg:
                self._kg.upsert_drawing_sheet({
                    "sheet_number": chunk_data["sheet_number"],
                    "title": chunk_data["title"],
                    "discipline": chunk_data["discipline"],
                    "project_id": project_id,
                    "source_doc_id": neo4j_doc_id,
                    "content_summary": summary,
                    "embedding": embedding,
                    "embedding_model": "text-embedding",
                    "chunk_id": chunk_id,
                }, project_id)

        return chunks_created

    def _generate_summary(self, content: str, title: str) -> str:
        """Generate a 2-3 sentence summary via AI."""
        if not content.strip():
            return f"{title} (no extractable text)"
        try:
            request = AIRequest(
                capability_class=CapabilityClass.EXTRACT,
                system_prompt=(
                    "Summarize the following construction document section in 2-3 sentences. "
                    "Focus on what it specifies, requires, or shows."
                ),
                user_prompt=f"TITLE: {title}\n\nCONTENT:\n{content}",
                temperature=0.0,
                calling_agent="doc_intelligence",
                task_id=f"summary-{title[:20]}",
            )
            response = engine.generate_response(request)
            return response.content.strip()
        except Exception as e:
            logger.warning(f"Summary generation failed for {title}: {e}")
            return f"{title}"

    def _scan_body_headers(self, pages: list[dict]) -> list[dict]:
        """
        Scan all pages for 'SECTION XX XX XX - TITLE' body headers.

        Returns sections sorted by page_number with division added, keeping
        only the first occurrence of each section_number (avoids duplicates
        from repeated headers or cross-references).
        """
        seen: set[str] = set()
        body_sections: list[dict] = []
        for page in pages:
            for h in self._spec_parser.detect_section_headers(page["text"]):
                sn = h["section_number"]
                if sn not in seen:
                    seen.add(sn)
                    h["page_number"] = page["page_number"]
                    h["division"] = self._spec_parser.infer_division(sn)
                    body_sections.append(h)
        return body_sections

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for content summary."""
        try:
            return engine.generate_embedding(text)
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return []

    def _create_cross_references(
        self, chunks: list[dict], project_id: str
    ) -> None:
        """Parse cross-references from chunk content and create KG relationships."""
        for chunk in chunks:
            content = chunk.get("content", "")
            section_num = chunk.get("section_number", "")

            # Find drawing references
            for match in _DRAWING_REF_RE.finditer(content):
                sheet_ref = match.group(1).upper()
                self._kg.create_cross_reference(
                    from_label="SpecSection",
                    from_key="section_number",
                    from_value=section_num,
                    rel_type="REFERENCES_DRAWING",
                    to_label="DrawingSheet",
                    to_key="sheet_number",
                    to_value=sheet_ref,
                    project_id=project_id,
                )

            # Find spec references (from one section to another)
            for match in _SPEC_REF_RE.finditer(content):
                ref_num = self._spec_parser._normalize_section_number(match.group(1))
                if ref_num != section_num:
                    self._kg.create_cross_reference(
                        from_label="SpecSection",
                        from_key="section_number",
                        from_value=section_num,
                        rel_type="REFERENCES_SPEC",
                        to_label="SpecSection",
                        to_key="section_number",
                        to_value=ref_num,
                        project_id=project_id,
                    )
