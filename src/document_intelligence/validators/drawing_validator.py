"""
DrawingValidator — reconciles sheet index entries against detected sheets.

Compares the list of sheet numbers declared in the drawing index against
the sheet numbers actually detected in the document pages, categorising
each sheet as matched, index_only, or document_only.
"""
from __future__ import annotations

from typing import Any


class DrawingValidator:
    """Reconciles a drawing sheet index against detected sheet numbers."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile(
        self,
        index_sheets: list[dict[str, Any]],
        detected_sheet_numbers: list[str],
    ) -> dict[str, list[str]]:
        """Reconcile index entries against detected sheets.

        Args:
            index_sheets: List of dicts, each containing at minimum a
                ``sheet_number`` key (e.g. ``[{"sheet_number": "A1.0", ...}]``).
            detected_sheet_numbers: Sheet numbers found in the document pages.

        Returns:
            Dict with three sorted lists:
            - ``matched``       — in both index and detected
            - ``index_only``    — in index but not detected
            - ``document_only`` — detected but not in index
        """
        index_set = {s["sheet_number"] for s in index_sheets}
        detected_set = set(detected_sheet_numbers)

        matched = sorted(index_set & detected_set)
        index_only = sorted(index_set - detected_set)
        document_only = sorted(detected_set - index_set)

        return {
            "matched": matched,
            "index_only": index_only,
            "document_only": document_only,
        }

    def get_verification_status(
        self,
        sheet_number: str,
        reconciliation: dict[str, list[str]],
    ) -> str:
        """Return which reconciliation category a sheet falls into.

        Args:
            sheet_number: The sheet number to look up.
            reconciliation: The dict returned by :meth:`reconcile`.

        Returns:
            One of ``"matched"``, ``"index_only"``, ``"document_only"``,
            or ``""`` if the sheet is not present in any category.
        """
        for category in ("matched", "index_only", "document_only"):
            if sheet_number in reconciliation.get(category, []):
                return category
        return ""

    def generate_report(
        self,
        reconciliation: dict[str, list[str]],
    ) -> dict[str, Any]:
        """Summarise reconciliation results as counts and a match rate.

        Args:
            reconciliation: The dict returned by :meth:`reconcile`.

        Returns:
            Dict with keys:
            - ``total``         — sum of all three category lengths
            - ``matched``       — count of matched sheets
            - ``index_only``    — count of index-only sheets
            - ``document_only`` — count of document-only sheets
            - ``match_rate``    — matched / total, rounded to 3 decimal places
                                  (0.0 when total is 0)
        """
        matched_count = len(reconciliation.get("matched", []))
        index_only_count = len(reconciliation.get("index_only", []))
        document_only_count = len(reconciliation.get("document_only", []))
        total = matched_count + index_only_count + document_only_count

        match_rate = round(matched_count / total, 3) if total > 0 else 0.0

        return {
            "total": total,
            "matched": matched_count,
            "index_only": index_only_count,
            "document_only": document_only_count,
            "match_rate": match_rate,
        }
