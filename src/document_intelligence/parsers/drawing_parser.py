"""
DrawingParser — sheet index detection, title block parsing, and discipline
inference for construction drawing sets.

Handles:
  - Inferring the discipline (Architectural, Structural, etc.) from a sheet number
  - Parsing lines of text that represent a sheet index into structured dicts
  - Detecting a title block's sheet number from free-form page text
  - Splitting a flat list of extracted pages into per-sheet buckets
"""
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Module-level compiled regexes
# ---------------------------------------------------------------------------

# Matches a sheet index line like:
#   "A1.0    TITLE"       (space-separated)
#   "A1.0 - TITLE"        (dash-separated)
#   "FP1.0   FIRE NOTES"  (two-letter prefix)
#
# Captures:
#   group(1)  — sheet number  (e.g. "A1.0", "FP2.3")
#   group(2)  — title         (stripped)
_SHEET_LINE_RE = re.compile(
    r"^([A-Z]{1,2}\d+(?:\.\d+)?)\s+(?:-\s+)?(.+)$"
)

# Matches a title block reference to a sheet number:
#   "Sheet: A2.3"   — explicit "Sheet:" label
#   "A2.3"          — bare sheet number at end of (or on its own) line
#
# Captures group(1) — sheet number
_TITLE_BLOCK_SHEET_RE = re.compile(
    r"(?:Sheet:\s*)?([A-Z]{1,2}\d+(?:\.\d+)?)\s*$",
    re.MULTILINE,
)

# Validates that a candidate sheet number has at least one letter prefix
# followed by at least one digit — prevents matching things like "PLAN" or "2.0"
_VALID_SHEET_RE = re.compile(r"^[A-Z]{1,2}\d")


class DrawingParser:
    """Parse drawing set documents: sheet index, title blocks, and discipline."""

    # ------------------------------------------------------------------
    # Constants
    # ------------------------------------------------------------------

    # Maps sheet number prefixes → discipline names.
    # Two-letter prefixes are checked before single-letter ones.
    _DISCIPLINE_MAP: dict[str, str] = {
        # Two-letter (checked first)
        "FP": "Fire Protection",
        "FS": "Fire Suppression",
        # Single-letter
        "A": "Architectural",
        "S": "Structural",
        "M": "Mechanical",
        "E": "Electrical",
        "P": "Plumbing",
        "L": "Landscape",
        "C": "Civil",
        "T": "Telecommunications",
        "G": "General",
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def infer_discipline(self, sheet_number: str) -> str:
        """
        Infer the discipline for *sheet_number* by matching its letter prefix.

        Two-letter prefixes (FP, FS) are evaluated before single-letter ones so
        that e.g. "FP1.0" maps to "Fire Protection" rather than "Unknown".

        Returns "Unknown" when no prefix matches.
        """
        # Two-letter prefixes first
        two = sheet_number[:2]
        if two in self._DISCIPLINE_MAP:
            return self._DISCIPLINE_MAP[two]

        # Single-letter prefix
        one = sheet_number[:1]
        if one in self._DISCIPLINE_MAP:
            return self._DISCIPLINE_MAP[one]

        return "Unknown"

    def parse_sheet_index_lines(self, lines: list[str]) -> list[dict]:
        """
        Parse a list of text lines into sheet index entries.

        Each line is matched against ``_SHEET_LINE_RE``.  Lines that don't match,
        or whose sheet number does not look real (letter prefix + digit), are
        silently skipped.

        Returns a list of dicts with keys:
            sheet_number  (str)
            title         (str)
            discipline    (str)
        """
        results: list[dict] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            m = _SHEET_LINE_RE.match(line)
            if not m:
                continue

            sheet_number = m.group(1)
            title = m.group(2).strip()

            # Validate: sheet number must start with letter(s) then a digit
            if not _VALID_SHEET_RE.match(sheet_number):
                continue

            results.append(
                {
                    "sheet_number": sheet_number,
                    "title": title,
                    "discipline": self.infer_discipline(sheet_number),
                }
            )

        return results

    def detect_title_block(self, page_text: str) -> Optional[dict]:
        """
        Scan *page_text* for a sheet number in a title block.

        Looks for patterns like:
          - "Sheet: A2.3"
          - A bare sheet number at the end of a line (e.g. "A2.3")

        Returns a dict ``{sheet_number, discipline}`` for the first match found,
        or ``None`` if no valid sheet number is detected.
        """
        if not page_text:
            return None

        for m in _TITLE_BLOCK_SHEET_RE.finditer(page_text):
            candidate = m.group(1)
            if _VALID_SHEET_RE.match(candidate):
                return {
                    "sheet_number": candidate,
                    "discipline": self.infer_discipline(candidate),
                }

        return None

    def split_pages_by_sheets(
        self,
        pages: list[dict],
        sheet_index: list[dict],
    ) -> list[dict]:
        """
        Assign each page to a sheet by detecting title blocks.

        *pages* is expected to be a list of page dicts as returned by
        ``PdfExtractor.extract_pages`` (keys: ``page_number``, ``text``, …).

        *sheet_index* is a list of dicts as returned by
        ``parse_sheet_index_lines`` (keys: ``sheet_number``, ``title``,
        ``discipline``).

        Algorithm:
          1. For each page, call ``detect_title_block`` on its text.
          2. Record the first page number at which each sheet number appears.
          3. Collect content (concatenated text) for consecutive pages that
             belong to the same sheet (from its start page up to — but not
             including — the next detected sheet's start page).
          4. Sheets listed in *sheet_index* but not found in any page get
             ``content=""``, ``page_start=None``, ``page_end=None``.

        Returns a list of dicts (one per sheet in *sheet_index*) with keys:
            sheet_number  (str)
            title         (str)
            discipline    (str)
            content       (str)
            page_start    (int | None)
            page_end      (int | None)
        """
        if not sheet_index:
            return []

        # --- Step 1: scan every page for a title block sheet number ---
        # page_assignment maps page_number (1-based int) → sheet_number detected
        page_assignment: dict[int, str] = {}
        # sheet_start maps sheet_number → first page_number where it appears
        sheet_start: dict[str, int] = {}

        for page in pages:
            pnum: int = page["page_number"]
            text: str = page.get("text", "")
            detected = self.detect_title_block(text)
            if detected:
                sn = detected["sheet_number"]
                page_assignment[pnum] = sn
                if sn not in sheet_start:
                    sheet_start[sn] = pnum

        # Build an ordered list of (page_number, sheet_number) transitions
        # so we can determine page ranges.
        transitions = sorted(
            (pnum, sn) for pnum, sn in page_assignment.items()
        )

        # --- Step 2: build start/end ranges for each detected sheet ---
        # sheet_ranges: sheet_number → (start_page, end_page)
        #
        # A sheet's range is: from its first detected page up to (but not
        # including) the page where the NEXT *different* sheet starts.
        # Intermediate pages without a detected sheet number are absorbed into
        # the preceding sheet's range.
        sheet_ranges: dict[str, tuple[int, int]] = {}
        all_page_numbers = sorted(p["page_number"] for p in pages)
        max_page = all_page_numbers[-1] if all_page_numbers else 0

        for idx, (start_pnum, sn) in enumerate(transitions):
            # Find the start of the next *different* sheet (skip repeated
            # detections of the same sheet number within consecutive pages).
            end_pnum = max_page
            for future_pnum, future_sn in transitions[idx + 1:]:
                if future_sn != sn:
                    end_pnum = future_pnum - 1
                    break

            # Only record the first time we see each sheet
            if sn not in sheet_ranges:
                sheet_ranges[sn] = (start_pnum, end_pnum)

        # --- Step 3: build a page_number → text map for quick lookup ---
        page_text_map: dict[int, str] = {
            p["page_number"]: p.get("text", "") for p in pages
        }

        # --- Step 4: assemble output ---
        results: list[dict] = []
        for entry in sheet_index:
            sn = entry["sheet_number"]

            if sn in sheet_ranges:
                start_p, end_p = sheet_ranges[sn]
                content_parts = [
                    page_text_map.get(pnum, "")
                    for pnum in range(start_p, end_p + 1)
                ]
                content = "\n".join(part for part in content_parts if part)
                results.append(
                    {
                        "sheet_number": sn,
                        "title": entry["title"],
                        "discipline": entry["discipline"],
                        "content": content,
                        "page_start": start_p,
                        "page_end": end_p,
                    }
                )
            else:
                results.append(
                    {
                        "sheet_number": sn,
                        "title": entry["title"],
                        "discipline": entry["discipline"],
                        "content": "",
                        "page_start": None,
                        "page_end": None,
                    }
                )

        return results
