"""
PdfExtractor — page-by-page PDF text extraction with OCR fallback.

Uses subprocess isolation for pypdf (matching the pattern in
src/knowledge_graph/ingestion.py) to prevent C-extension segfaults from
crashing the worker process.

OCR fallback (pytesseract + pdf2image) is attempted for pages where pypdf
extracts fewer than 50 characters.  If the OCR libraries are not installed the
fallback gracefully returns None and the page is marked "failed".
"""
import json
import logging
import os
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Threshold below which a page is considered "low quality" and OCR is attempted.
_MIN_CHARS = 50


class PdfExtractor:
    """
    Extracts text from PDF files page-by-page.

    All heavy lifting is done in child processes so that segfaults in pypdf's
    C extensions (or Tesseract's native library) cannot kill the caller.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_page_count(self, pdf_path: str) -> int:
        """
        Return the number of pages in the PDF at *pdf_path*.

        Returns 0 on any error (file missing, not a PDF, subprocess failure).
        """
        if not os.path.isfile(pdf_path):
            return 0

        script = (
            "import pypdf, sys, io\n"
            "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n"
            f"r = pypdf.PdfReader({repr(pdf_path)})\n"
            "print(len(r.pages))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if proc.returncode != 0:
                logger.warning(
                    "get_page_count subprocess failed (exit %d): %s",
                    proc.returncode,
                    proc.stderr[:200],
                )
                return 0
            return int(proc.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, Exception) as exc:
            logger.warning("get_page_count failed for %s: %s", pdf_path, exc)
            return 0

    def extract_pages(self, pdf_path: str) -> list[dict]:
        """
        Extract text from every page of the PDF.

        Returns a list of dicts (one per page):
            {
                "page_number":        int   (1-based),
                "text":               str,
                "extraction_method":  "pypdf" | "ocr" | "failed",
                "char_count":         int,
                "flagged":            bool  (True when char_count < 50),
            }

        Returns [] when the file does not exist or is not a valid PDF.
        """
        # --- Validate file existence ---
        if not os.path.isfile(pdf_path):
            logger.warning("extract_pages: file not found: %s", pdf_path)
            return []

        # --- Validate PDF magic bytes (%PDF) ---
        try:
            with open(pdf_path, "rb") as fh:
                header = fh.read(4)
        except OSError as exc:
            logger.warning("extract_pages: cannot read %s: %s", pdf_path, exc)
            return []

        if header != b"%PDF":
            logger.warning(
                "extract_pages: not a valid PDF (bad magic bytes): %s", pdf_path
            )
            return []

        # --- Extract all pages via pypdf subprocess ---
        page_texts = self._extract_all_pages_pypdf(pdf_path)
        if page_texts is None:
            logger.warning(
                "extract_pages: pypdf extraction returned None for %s", pdf_path
            )
            return []

        results: list[dict] = []
        for page_index, raw_text in enumerate(page_texts):
            text = raw_text or ""
            char_count = len(text)
            method: str

            if char_count >= _MIN_CHARS:
                method = "pypdf"
            else:
                # Attempt OCR fallback for low-yield pages.
                ocr_text = self._ocr_page(pdf_path, page_index)
                if ocr_text is not None and len(ocr_text) > char_count:
                    # OCR produced more text — prefer it.
                    text = ocr_text
                    method = "ocr"
                elif char_count > 0:
                    # pypdf got a small amount of text; keep it rather than nothing.
                    method = "pypdf"
                else:
                    method = "failed"

            results.append(
                {
                    "page_number": page_index + 1,
                    "text": text,
                    "extraction_method": method,
                    "char_count": len(text),
                    "flagged": len(text) < _MIN_CHARS,
                }
            )

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_all_pages_pypdf(self, pdf_path: str) -> Optional[list[str]]:
        """
        Run pypdf in a subprocess and return a list of per-page text strings.

        Returns None on any failure (subprocess error, timeout, JSON decode error).
        Timeout: 120 seconds.
        """
        script = (
            "import pypdf, io, sys, json\n"
            "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n"
            f"r = pypdf.PdfReader({repr(pdf_path)})\n"
            "pages = [p.extract_text() or '' for p in r.pages]\n"
            "print(json.dumps(pages))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            if proc.returncode != 0:
                logger.warning(
                    "_extract_all_pages_pypdf subprocess failed (exit %d): %s",
                    proc.returncode,
                    proc.stderr[:200],
                )
                return None
            return json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            logger.warning(
                "_extract_all_pages_pypdf timed out (120s) for %s", pdf_path
            )
            return None
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(
                "_extract_all_pages_pypdf failed for %s: %s", pdf_path, exc
            )
            return None

    def _ocr_page(self, pdf_path: str, page_index: int) -> Optional[str]:
        """
        OCR a single page (0-based *page_index*) using pytesseract + pdf2image.

        Returns None if:
          - pytesseract or pdf2image are not installed
          - the subprocess fails or times out
          - any other error occurs

        Timeout: 60 seconds.
        """
        script = (
            "import sys, io, json\n"
            "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n"
            "try:\n"
            "    import pytesseract\n"
            "    from pdf2image import convert_from_path\n"
            "except ImportError as e:\n"
            "    print(json.dumps({'error': 'import_error', 'detail': str(e)}))\n"
            "    sys.exit(0)\n"
            f"images = convert_from_path({repr(pdf_path)}, first_page={page_index + 1}, last_page={page_index + 1})\n"
            "if not images:\n"
            "    print(json.dumps({'error': 'no_image'}))\n"
            "    sys.exit(0)\n"
            "text = pytesseract.image_to_string(images[0])\n"
            "print(json.dumps({'text': text}))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if proc.returncode != 0:
                logger.warning(
                    "_ocr_page subprocess failed (exit %d) for page %d of %s: %s",
                    proc.returncode,
                    page_index + 1,
                    pdf_path,
                    proc.stderr[:200],
                )
                return None

            data = json.loads(proc.stdout)
            if "error" in data:
                if data["error"] == "import_error":
                    logger.debug(
                        "_ocr_page: OCR libraries not available (%s)", data.get("detail")
                    )
                else:
                    logger.warning(
                        "_ocr_page: OCR error for page %d of %s: %s",
                        page_index + 1,
                        pdf_path,
                        data.get("detail"),
                    )
                return None

            return data.get("text", "")

        except subprocess.TimeoutExpired:
            logger.warning(
                "_ocr_page timed out (60s) for page %d of %s",
                page_index + 1,
                pdf_path,
            )
            return None
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(
                "_ocr_page failed for page %d of %s: %s",
                page_index + 1,
                pdf_path,
                exc,
            )
            return None
