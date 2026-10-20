"""Abstract base class for all PDF generators."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.models import AttendanceReport


class BaseGenerator(ABC):
    @abstractmethod
    def generate(self, report: AttendanceReport, output_path: Path) -> Path:
        """
        Write a new document to *output_path* from *report*.

        Parameters
        ----------
        report : AttendanceReport
            Fully corrected report (output of the rules engine).
        output_path : Path
            Destination file. Parent directory must already exist.

        Returns
        -------
        Path
            The file actually written (a generator may change the suffix).
        """
