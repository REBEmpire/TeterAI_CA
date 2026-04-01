"""
SpecValidator — TOC-to-content cross-validation for CSI specification books.

Cross-validates Table of Contents entries against actual page text to detect
page offsets and produce a validation report.
"""
import re
import logging

logger = logging.getLogger(__name__)

# Matches any sequence of digits that looks like a 6-digit CSI section number,
# possibly with spaces between the groups (e.g. "09 21 16", "09  21 16", "092116").
_CSI_FIND_RE = re.compile(r"(\d{2}\s?\d{2}\s?\d{2})")


def _normalize(section_number: str) -> str:
    """Strip all whitespace from a CSI section number for comparison."""
    return re.sub(r"\s+", "", section_number)


class SpecValidator:
    """
    Cross-validates TOC section entries against actual PDF page content.

    Typical workflow:
        1. ``detect_page_offset`` — find the integer offset between TOC page
           references and actual PDF page numbers.
        2. ``validate_sections`` — check each TOC entry against the page at
           (toc_page + offset).
        3. ``generate_report`` — summarise the validation results.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_sections(
        self,
        toc_sections: list[dict],
        pages: dict[int, str],
        page_offset: int = 0,
    ) -> list[dict]:
        """
        Cross-validate TOC sections against page content.

        Args:
            toc_sections: list of dicts with keys ``section_number``, ``title``,
                          ``page_number``.
            pages:        dict mapping page_number (int) → page text (str).
            page_offset:  integer to add to each TOC page_number when looking up
                          the actual page.  Use the value returned by
                          ``detect_page_offset``.

        Returns:
            list of dicts, one per TOC entry::

                {
                    "section_number": str,
                    "title":          str,
                    "toc_page":       int,
                    "actual_page":    int | None,   # None when page not in pages
                    "status":         "matched" | "mismatch" | "page_not_found",
                }
        """
        results = []
        for section in toc_sections:
            section_number = section["section_number"]
            title = section.get("title", "")
            toc_page = section["page_number"]
            actual_page = toc_page + page_offset

            if actual_page not in pages:
                results.append(
                    {
                        "section_number": section_number,
                        "title": title,
                        "toc_page": toc_page,
                        "actual_page": None,
                        "status": "page_not_found",
                    }
                )
                continue

            page_text = pages[actual_page]
            status = "mismatch"

            # Find all CSI-style numbers in the page text and compare after
            # normalising (stripping spaces) for both the candidate and the
            # TOC section number.
            target = _normalize(section_number)
            for match in _CSI_FIND_RE.finditer(page_text):
                candidate = _normalize(match.group(1))
                if candidate == target:
                    status = "matched"
                    break

            results.append(
                {
                    "section_number": section_number,
                    "title": title,
                    "toc_page": toc_page,
                    "actual_page": actual_page,
                    "status": status,
                }
            )

        return results

    def detect_page_offset(
        self,
        toc_sections: list[dict],
        pages: dict[int, str],
        search_range: int = 10,
    ) -> int:
        """
        Determine the integer page offset that maximises TOC–content matches.

        Tries every offset in ``[-search_range, +search_range]`` inclusive.
        For each offset, counts how many TOC sections find their section number
        in the page at ``(toc_page + offset)``.

        Args:
            toc_sections: list of dicts with ``section_number`` and ``page_number``.
            pages:        dict mapping page_number → page text.
            search_range: maximum absolute offset to try (default 10).

        Returns:
            The offset with the highest match count.  Returns 0 if no sections
            matched at any offset, or if the input lists are empty.
        """
        if not toc_sections:
            return 0

        best_offset = 0
        best_count = 0

        for offset in range(-search_range, search_range + 1):
            count = 0
            for section in toc_sections:
                section_number = section["section_number"]
                toc_page = section.get("page_number")
                if toc_page is None:
                    continue
                candidate_page = toc_page + offset
                if candidate_page not in pages:
                    continue
                target = _normalize(section_number)
                for match in _CSI_FIND_RE.finditer(pages[candidate_page]):
                    if _normalize(match.group(1)) == target:
                        count += 1
                        break
            if count > best_count:
                best_count = count
                best_offset = offset

        return best_offset

    def generate_report(self, validation_results: list[dict]) -> dict:
        """
        Summarise validation results into a report dict.

        Args:
            validation_results: list of result dicts from ``validate_sections``.

        Returns::

            {
                "total":      int,
                "matched":    int,
                "mismatched": int,
                "not_found":  int,
                "match_rate": float,   # matched / total, rounded to 3 decimals
            }

        ``match_rate`` is 0.0 when ``total`` is 0.
        """
        total = len(validation_results)
        matched = sum(1 for r in validation_results if r["status"] == "matched")
        mismatched = sum(1 for r in validation_results if r["status"] == "mismatch")
        not_found = sum(1 for r in validation_results if r["status"] == "page_not_found")
        match_rate = round(matched / total, 3) if total > 0 else 0.0

        return {
            "total": total,
            "matched": matched,
            "mismatched": mismatched,
            "not_found": not_found,
            "match_rate": match_rate,
        }
