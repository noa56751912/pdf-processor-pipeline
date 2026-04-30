"""
Abstract base class for all file readers.

Design pattern: Strategy / Abstract Base Class
- Every concrete reader implements `read()` and returns plain text.
- New file types (DOCX, image, CSV …) only require a new subclass; nothing
  else in the pipeline changes.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseReader(ABC):
    """
    Common interface for reading any supported file into a plain UTF-8 string.
    """

    # Subclasses declare which file extensions they handle, e.g. {'.pdf'}
    supported_extensions: set[str] = set()

    @abstractmethod
    def read(self, file_path: str | Path) -> str:
        """
        Read the file at *file_path* and return its full textual content.

        Parameters
        ----------
        file_path : str | Path
            Absolute or relative path to the source file.

        Returns
        -------
        str
            The extracted text, with pages separated by a form-feed character
            (``\\f``) so callers can still split by page when needed.

        Raises
        ------
        FileNotFoundError
            If *file_path* does not exist.
        ValueError
            If the file extension is not supported by this reader.
        RuntimeError
            If extraction fails for any other reason.
        """

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    def _assert_supported(self, file_path: Path) -> None:
        """Raise ValueError if the file extension is not in supported_extensions."""
        ext = file_path.suffix.lower()
        if self.supported_extensions and ext not in self.supported_extensions:
            raise ValueError(
                f"{self.__class__.__name__} does not support '{ext}' files. "
                f"Supported: {self.supported_extensions}"
            )

    def _assert_exists(self, file_path: Path) -> None:
        """Raise FileNotFoundError if the file does not exist."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
