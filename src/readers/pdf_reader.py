"""
PDF reader implementation.

Rendering
---------
PyMuPDF (fitz) rasterises each page to a PIL image at the requested DPI.
No text is extracted directly from the PDF, avoiding garbled Hebrew font issues.

OCR
---
Text extraction is delegated to an injected OCREngine (Strategy Pattern /
Dependency Injection).  PDFReader has no knowledge of *which* OCR backend is
used; it only calls ``ocr_engine.extract_text(image, lang)``.

Default engine: TesseractOCREngine (pytesseract + Tesseract-OCR).
To swap backends, pass a different OCREngine subclass to __init__.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF -- used only for rendering, not text extraction

from .base_reader import BaseReader
from .ocr_engine import OCREngine, TesseractOCREngine

logger = logging.getLogger(__name__)


class PDFReader(BaseReader):
    """
    Reads a PDF file and returns OCR-ed text content.

    Parameters
    ----------
    dpi : int
        Resolution for rasterising pages (default 300).  Higher values give
        better OCR accuracy at the cost of speed.
    lang : str
        Language hint forwarded to the OCR engine (default ``'heb+eng'``).
    ocr_engine : OCREngine | None
        The OCR backend to use.  Defaults to ``TesseractOCREngine()``.
        Pass any other ``OCREngine`` subclass to switch backends without
        touching this class.
    """

    supported_extensions: set[str] = {".pdf"}

    def __init__(
        self,
        dpi: int = 300,
        lang: str = "heb+eng",
        ocr_engine: OCREngine | None = None,
    ) -> None:
        self.dpi = dpi
        self.lang = lang
        self._ocr_engine: OCREngine = ocr_engine if ocr_engine is not None else TesseractOCREngine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self, file_path: str | Path) -> str:
        """
        OCR all pages of *file_path* and return the text as a single string.
        Pages are separated by the form-feed character ``\\f``.
        """
        path = Path(file_path)
        self._assert_exists(path)
        self._assert_supported(path)

        logger.info("Reading PDF: %s", path)

        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "Pillow is not installed. Run: pip install Pillow"
            ) from exc

        doc = fitz.open(str(path))
        page_texts: list[str] = []
        zoom = self.dpi / 72.0  # 72 pt/inch is PyMuPDF baseline

        for page_index, page in enumerate(doc):
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = self._ocr_engine.extract_text(img, self.lang)
            logger.debug("Page %d: OCR produced %d chars.", page_index + 1, len(text))
            page_texts.append(text)

        doc.close()
        full_text = "\f".join(page_texts)
        logger.info(
            "Extracted %d characters from %d page(s).",
            len(full_text),
            len(page_texts),
        )
        return full_text
