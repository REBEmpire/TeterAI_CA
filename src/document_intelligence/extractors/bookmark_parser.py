"""
BookmarkParser — PDF bookmark/outline extraction for spec books and drawing sets.

Uses pypdf directly (NOT subprocess) because outline parsing is lightweight,
read-only work and does not carry the same segfault risk as full text extraction.
"""
import logging
from typing import Optional

import pypdf
from pypdf.generic import Destination

logger = logging.getLogger(__name__)

# Known TOC bookmark title variants (case-insensitive comparison)
_TOC_TITLES = {"table of contents", "toc", "contents", "index"}

# Known sheet/drawing index title variants (case-insensitive comparison)
_SHEET_INDEX_TITLES = {
    "sheet index",
    "drawing index",
    "drawing list",
    "sheet list",
    "index of drawings",
}


class BookmarkParser:
    """
    Extracts and interprets PDF outline (bookmark) structures.

    Useful for navigating spec books (CSI division structure) and drawing sets
    (sheet indices, section tabs) without having to read every page.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_bookmarks(self, pdf_path: str) -> list[dict]:
        """
        Return a flat list of all bookmarks in the PDF.

        Each entry is::

            {"title": str, "page_number": int}   # page_number is 0-based

        Nested outlines are flattened recursively.  Returns ``[]`` if the file
        cannot be read, is not a valid PDF, or has no outline.
        """
        try:
            reader = pypdf.PdfReader(pdf_path)
        except Exception as exc:
            logger.warning("extract_bookmarks: cannot open %s: %s", pdf_path, exc)
            return []

        outline = reader.outline
        if not outline:
            return []

        result: list[dict] = []
        self._flatten_outline(reader, outline, result)
        return result

    def find_toc_bookmark(self, pdf_path: str) -> Optional[dict]:
        """
        Return the first bookmark whose title matches a known TOC title.

        Comparison is case-insensitive and strips surrounding whitespace.
        Returns ``None`` if no matching bookmark is found.
        """
        for bm in self.extract_bookmarks(pdf_path):
            if bm["title"].strip().lower() in _TOC_TITLES:
                return bm
        return None

    def find_sheet_index_bookmark(self, pdf_path: str) -> Optional[dict]:
        """
        Return the first bookmark whose title matches a known sheet index title.

        Comparison is case-insensitive and strips surrounding whitespace.
        Returns ``None`` if no matching bookmark is found.
        """
        for bm in self.extract_bookmarks(pdf_path):
            if bm["title"].strip().lower() in _SHEET_INDEX_TITLES:
                return bm
        return None

    def get_section_boundaries(self, pdf_path: str) -> list[dict]:
        """
        Infer section boundaries from PDF bookmarks.

        Returns a list of dicts::

            {
                "title":      str,
                "start_page": int,   # 0-based, inclusive
                "end_page":   int,   # 0-based, inclusive
            }

        The ``end_page`` of each section is one less than the ``start_page`` of
        the following section.  The final section ends on the last page of the
        document (``len(reader.pages) - 1``).

        Returns ``[]`` if the file has no bookmarks or cannot be opened.
        """
        bookmarks = self.extract_bookmarks(pdf_path)
        if not bookmarks:
            return []

        try:
            reader = pypdf.PdfReader(pdf_path)
            last_page = len(reader.pages) - 1
        except Exception as exc:
            logger.warning(
                "get_section_boundaries: cannot open %s: %s", pdf_path, exc
            )
            return []

        sections: list[dict] = []
        for i, bm in enumerate(bookmarks):
            if i + 1 < len(bookmarks):
                end_page = bookmarks[i + 1]["page_number"] - 1
            else:
                end_page = last_page

            sections.append(
                {
                    "title": bm["title"],
                    "start_page": bm["page_number"],
                    "end_page": end_page,
                }
            )

        return sections

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _flatten_outline(
        self,
        reader: pypdf.PdfReader,
        outline: list,
        result: list[dict],
    ) -> None:
        """
        Recursively walk *outline* and append flat bookmark dicts to *result*.

        pypdf represents nested outlines as nested lists: a ``Destination`` item
        may be followed by a plain ``list`` containing its children.
        """
        for item in outline:
            if isinstance(item, list):
                # Nested children — recurse
                self._flatten_outline(reader, item, result)
            elif isinstance(item, Destination):
                page_num = self._resolve_page_number(reader, item)
                result.append({"title": str(item.title), "page_number": page_num})
            else:
                # Unknown outline item type — skip gracefully
                logger.debug(
                    "_flatten_outline: skipping unknown outline item type %s",
                    type(item).__name__,
                )

    def _resolve_page_number(
        self, reader: pypdf.PdfReader, bookmark: Destination
    ) -> int:
        """
        Resolve a bookmark's destination to a 0-based page number.

        ``reader.get_destination_page_number`` handles both direct integer page
        references and indirect PDF object references.  Returns ``0`` on any
        failure.
        """
        try:
            page_num = reader.get_destination_page_number(bookmark)
            if page_num is None:
                return 0
            return int(page_num)
        except Exception as exc:
            logger.debug(
                "_resolve_page_number: failed for bookmark %r: %s",
                getattr(bookmark, "title", "?"),
                exc,
            )
            return 0
