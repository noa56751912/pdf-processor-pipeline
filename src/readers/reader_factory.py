"""
Reader factory.

Design pattern: Factory Method
- Maps file extensions to concrete BaseReader subclasses.
- To support a new file type: create the reader class and call
  ``ReaderFactory.register()`` – no other code needs to change.

Usage
-----
    from src.readers.reader_factory import ReaderFactory

    text = ReaderFactory.get_reader("report.pdf").read("report.pdf")
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base_reader import BaseReader
from .pdf_reader import PDFReader

logger = logging.getLogger(__name__)


class ReaderFactory:
    """
    Central registry that maps file extensions to reader instances.

    The registry is populated with built-in readers at module load time.
    Third-party code (or tests) can extend it with ``register()``.
    """

    # extension (lowercase, with dot) → reader instance
    _registry: dict[str, BaseReader] = {}

    # ------------------------------------------------------------------
    # Built-in registrations
    # ------------------------------------------------------------------

    @classmethod
    def _bootstrap(cls) -> None:
        """Register all built-in readers once."""
        if cls._registry:
            return  # already bootstrapped

        cls.register(PDFReader())

        # Future built-in readers can be added here, e.g.:
        # cls.register(DocxReader())
        # cls.register(PlainTextReader())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def register(cls, reader: BaseReader) -> None:
        """
        Add *reader* to the registry for every extension it declares.

        Parameters
        ----------
        reader : BaseReader
            A concrete reader instance.  Its ``supported_extensions`` set
            determines which file extensions it will handle.
        """
        if not reader.supported_extensions:
            logger.warning(
                "%s declares no supported_extensions; skipping registration.",
                reader.__class__.__name__,
            )
            return

        for ext in reader.supported_extensions:
            key = ext.lower()
            if key in cls._registry:
                logger.warning(
                    "Overwriting existing reader for '%s' with %s.",
                    key,
                    reader.__class__.__name__,
                )
            cls._registry[key] = reader
            logger.debug("Registered %s for '%s'.", reader.__class__.__name__, key)

    @classmethod
    def get_reader(cls, file_path: str | Path) -> BaseReader:
        """
        Return the appropriate reader for *file_path*.

        Parameters
        ----------
        file_path : str | Path
            The source file.  Only the extension is inspected.

        Returns
        -------
        BaseReader
            The registered reader for the file's extension.

        Raises
        ------
        ValueError
            If no reader is registered for the given extension.
        """
        cls._bootstrap()
        ext = Path(file_path).suffix.lower()
        reader = cls._registry.get(ext)
        if reader is None:
            supported = sorted(cls._registry.keys())
            raise ValueError(
                f"No reader registered for '{ext}'. "
                f"Supported extensions: {supported}"
            )
        return reader

    @classmethod
    def read(cls, file_path: str | Path) -> str:
        """
        Convenience shortcut: resolve the reader and immediately call read().

        Equivalent to ``ReaderFactory.get_reader(path).read(path)``.
        """
        path = Path(file_path)
        return cls.get_reader(path).read(path)

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """Return a sorted list of all registered extensions."""
        cls._bootstrap()
        return sorted(cls._registry.keys())
