"""
OCR Engine abstraction – Strategy Pattern.

OCREngine          – abstract interface (one method: extract_text)
TesseractOCREngine – concrete implementation using pytesseract + Tesseract-OCR

Design notes
------------
* PDFReader depends only on OCREngine, never on pytesseract directly.
* Swapping OCR backends (e.g. EasyOCR, Google Vision) requires only a new
  OCREngine subclass; nothing else in the pipeline changes.
* All Tesseract-specific configuration (executable discovery, TESSDATA_PREFIX,
  language fallback) is encapsulated in TesseractOCREngine.
"""
from __future__ import annotations

import logging
import os
import shutil
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Well-known Windows install locations for Tesseract-OCR
_TESSERACT_FALLBACKS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(
        r"C:\Users\%USERNAME%\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
    ),
]


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class OCREngine(ABC):
    """
    Strategy interface for OCR text extraction.

    Parameters passed to every call
    --------------------------------
    image : PIL.Image.Image
        The rasterised page image to extract text from.
    lang : str
        Language hint string in backend-specific format
        (e.g. ``'heb+eng'`` for Tesseract).

    Returns
    -------
    str
        Extracted text, stripped of leading/trailing whitespace.
    """

    @abstractmethod
    def extract_text(self, image, lang: str) -> str:
        """Extract text from *image* using the given *lang* hint."""


# ---------------------------------------------------------------------------
# Tesseract concrete implementation
# ---------------------------------------------------------------------------

class TesseractOCREngine(OCREngine):
    """
    OCR engine backed by Tesseract via pytesseract.

    Responsibilities
    ----------------
    * Locate the Tesseract executable (PATH → known Windows paths).
    * Set TESSDATA_PREFIX when the tessdata directory is found alongside exe.
    * Run OCR on a PIL image with graceful language fallback to 'eng' on error.
    """

    def __init__(self) -> None:
        self._configured = False

    # ------------------------------------------------------------------
    # OCREngine interface
    # ------------------------------------------------------------------

    def extract_text(self, image, lang: str) -> str:
        """Run Tesseract OCR on *image*; falls back to 'eng' on language error."""
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError(
                "pytesseract is not installed. Run: pip install pytesseract"
            ) from exc

        if not self._configured:
            self._configure(pytesseract)
            self._configured = True

        try:
            text = pytesseract.image_to_string(image, lang=lang, config='--psm 6')
            return text.strip()
        except pytesseract.TesseractNotFoundError as exc:
            raise RuntimeError(
                "Tesseract is not installed or not in PATH. "
                "Install from https://github.com/UB-Mannheim/tesseract/wiki"
            ) from exc
        except pytesseract.TesseractError as exc:
            # Requested language pack not available – retry with English only.
            logger.warning(
                "Tesseract error (%s) – retrying with lang='eng'.", exc
            )
            try:
                return pytesseract.image_to_string(image, lang="eng", config='--psm 6').strip()
            except pytesseract.TesseractError as exc2:
                logger.warning(
                    "OCR retry with 'eng' failed (%s) – returning empty text.", exc2
                )
                return ""

    def extract_words(self, image, lang: str, whitelist: str = "") -> list[tuple[int, str]]:
        """
        Run Tesseract on *image* and return every word with the height of its
        centre.  *whitelist* limits the characters Tesseract may read, e.g.
        digits and ':' for a time column.
        """
        import pytesseract

        if not self._configured:
            self._configure(pytesseract)
            self._configured = True

        config = "--psm 6" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
        data = pytesseract.image_to_data(
            image, lang=lang, config=config, output_type=pytesseract.Output.DICT
        )
        return [
            (top + height // 2, text)
            for top, height, text in zip(data["top"], data["height"], data["text"])
            if text.strip()
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _configure(self, pytesseract_module) -> None:
        """
        Point pytesseract at the Tesseract executable and set TESSDATA_PREFIX.

        Search order
        ------------
        1. ``tesseract`` on the system PATH.
        2. Known Windows installation directories (_TESSERACT_FALLBACKS).
        """
        on_path = shutil.which("tesseract")
        if on_path:
            pytesseract_module.pytesseract.tesseract_cmd = on_path
            logger.debug("Tesseract found on PATH: %s", on_path)
            return

        for candidate in _TESSERACT_FALLBACKS:
            if os.path.isfile(candidate):
                pytesseract_module.pytesseract.tesseract_cmd = candidate
                logger.debug("Tesseract located at: %s", candidate)
                tessdata_dir = os.path.join(os.path.dirname(candidate), "tessdata")
                if os.path.isdir(tessdata_dir) and "TESSDATA_PREFIX" not in os.environ:
                    os.environ["TESSDATA_PREFIX"] = tessdata_dir
                    logger.debug("TESSDATA_PREFIX set to: %s", tessdata_dir)
                return

        logger.warning(
            "Tesseract executable not found on PATH or in default locations. "
            "OCR may fail. Install from https://github.com/UB-Mannheim/tesseract/wiki"
        )
