"""
SpecParser — TOC detection, section splitting, and CSI pattern matching.

Parses construction specification books (CSI MasterFormat) to:
  - Identify Table of Contents entries and extract section metadata
  - Detect SECTION headers in body text
  - Split a page-list into per-section content chunks using TOC page references
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SpecParser:
    """
    Parses CSI-formatted specification documents.

    CSI MasterFormat section numbers follow the pattern XX XX XX (three
    two-digit groups separated by spaces), e.g. "09 21 16".
    """

    # ------------------------------------------------------------------
    # Compiled regex patterns
    # ------------------------------------------------------------------

    # Matches TOC lines in two forms:
    #   "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412"
    #   "09 21 16 GYPSUM BOARD ASSEMBLIES 412"
    # Groups: (section_raw, title_part, dots_and_page, page_number)
    # section_raw may be "09 21 16" or compact "092116"
    _CSI_SECTION_RE = re.compile(
        r"""
        ^\s*
        (?:SECTION\s+)?                          # optional "SECTION " prefix (any case)
        (?P<section_raw>                          # the section number
            \d{2}\s\d{2}\s\d{2}                  #   spaced:   09 21 16
            |\d{6}                                #   compact:  092116
        )
        \s*
        (?:-\s*)?                                 # optional dash separator
        (?P<title>[A-Z][A-Z0-9 ,\-/&()]+?)       # title (re.IGNORECASE makes this match mixed/lower case)
        \s*
        (?:\.{2,}\s*)?                            # optional dot-leader
        (?P<page>\d+)?                            # optional page number
        \s*$
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # Matches "SECTION XX XX XX - TITLE" at start of line in body text
    _SECTION_HEADER_RE = re.compile(
        r"""
        ^SECTION\s+
        (?P<section_raw>\d{2}\s\d{2}\s\d{2}|\d{6})
        \s*-\s*
        (?P<title>[A-Z][A-Z0-9 ,\-/&()]+?)
        \s*$
        """,
        re.VERBOSE | re.MULTILINE | re.IGNORECASE,
    )

    # Matches bare "09 21 16 TITLE 412" (no SECTION prefix)
    _BARE_CSI_RE = re.compile(
        r"""
        ^(?P<section_raw>\d{2}\s\d{2}\s\d{2}|\d{6})
        \s+
        (?P<title>[A-Z][A-Z0-9 ,\-/&()]+?)
        \s+(?P<page>\d+)\s*$
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_toc_lines(self, lines: list[str]) -> list[dict]:
        """
        Parse TOC-style lines into section metadata dicts.

        Each returned dict has:
            section_number (str)  — normalised "XX XX XX"
            title          (str)  — section title, stripped
            page_number    (int|None) — page reference, or None if absent
            division       (str)  — two-digit CSI division, e.g. "09"

        Non-matching lines are silently skipped.
        """
        results = []
        for line in lines:
            entry = self._parse_toc_line(line)
            if entry is not None:
                results.append(entry)
        return results

    def detect_section_headers(self, text: str) -> list[dict]:
        """
        Scan body text for 'SECTION XX XX XX - TITLE' headers at line starts.

        Returns a list of dicts with keys:
            section_number (str)
            title          (str)
        """
        results = []
        for m in self._SECTION_HEADER_RE.finditer(text):
            section_number = self._normalize_section_number(m.group("section_raw"))
            title = m.group("title").strip()
            results.append({"section_number": section_number, "title": title})
        return results

    def infer_division(self, section_number: str) -> str:
        """
        Extract the two-digit CSI division from a normalised section number.

        >>> parser.infer_division("09 21 16")
        '09'
        """
        return section_number[:2]

    def split_pages_by_sections(
        self,
        pages: list[dict],
        toc_sections: list[dict],
        page_offset: int = 0,
    ) -> list[dict]:
        """
        Split a list of page dicts into per-section content chunks.

        Args:
            pages         — list of {"page_number": int, "text": str, ...}
            toc_sections  — output of parse_toc_lines()
            page_offset   — subtract this from each TOC page_number to get the
                            index into the supplied pages list
                            (use when the pages list starts at a physical page
                            other than the TOC's page 1)

        Returns a list of dicts:
            section_number  (str)
            title           (str)
            division        (str)
            content         (str)   — concatenated text of all pages in range
            page_start      (int)   — first page_number in this section
            page_end        (int)   — last page_number in this section

        Sections whose TOC page reference falls outside the supplied pages
        range are skipped.
        """
        if not toc_sections or not pages:
            return []

        # Build a mapping from page_number → text for O(1) lookup.
        page_map: dict[int, str] = {p["page_number"]: p.get("text", "") for p in pages}
        all_page_nums = sorted(page_map.keys())
        if not all_page_nums:
            return []

        min_page = all_page_nums[0]
        max_page = all_page_nums[-1]

        # Resolve effective (list-local) start pages for each TOC section.
        resolved: list[tuple[int, dict]] = []
        for sec in toc_sections:
            raw_page = sec.get("page_number")
            if raw_page is None:
                continue
            effective = raw_page - page_offset
            if effective < min_page or effective > max_page:
                continue
            resolved.append((effective, sec))

        if not resolved:
            return []

        # Sort by effective start page (TOC should already be ordered, but be safe).
        resolved.sort(key=lambda t: t[0])

        chunks = []
        for i, (start_page, sec) in enumerate(resolved):
            # End page is one before the next section's start, or the last page.
            if i + 1 < len(resolved):
                end_page = resolved[i + 1][0] - 1
            else:
                end_page = max_page

            # Collect and concatenate page text for this range.
            content_parts = []
            for pnum in all_page_nums:
                if start_page <= pnum <= end_page:
                    content_parts.append(page_map[pnum])
            content = "\n".join(content_parts)

            chunks.append(
                {
                    "section_number": sec["section_number"],
                    "title": sec["title"],
                    "division": sec["division"],
                    "content": content,
                    "page_start": start_page,
                    "page_end": end_page,
                }
            )

        return chunks

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_toc_line(self, line: str) -> Optional[dict]:
        """
        Attempt to parse a single TOC line.  Returns a metadata dict or None.
        """
        # Try the general pattern first (handles both "SECTION ..." and bare forms).
        m = self._CSI_SECTION_RE.match(line)
        if m:
            section_raw = m.group("section_raw")
            title = m.group("title").strip() if m.group("title") else ""
            page_str = m.group("page")

            # Guard: ensure the title looks like real uppercase words (not just digits).
            if not title or not any(c.isalpha() for c in title):
                return None

            section_number = self._normalize_section_number(section_raw)
            page_number = int(page_str) if page_str else None
            division = self.infer_division(section_number)
            return {
                "section_number": section_number,
                "title": title,
                "page_number": page_number,
                "division": division,
            }

        return None

    def _normalize_section_number(self, raw: str) -> str:
        """
        Normalise a CSI section number to the canonical "XX XX XX" format.

        Accepts:
            "092116"     → "09 21 16"
            "09 21 16"   → "09 21 16"
            "09  21  16" → "09 21 16"  (extra whitespace collapsed)
        """
        # Strip all whitespace and check for compact 6-digit form.
        compact = re.sub(r"\s+", "", raw)
        if re.fullmatch(r"\d{6}", compact):
            return f"{compact[0:2]} {compact[2:4]} {compact[4:6]}"
        # Already spaced — normalise internal whitespace.
        parts = raw.split()
        if len(parts) == 3:
            return " ".join(parts)
        # Fallback: return as-is (shouldn't reach here for valid input).
        return raw.strip()
