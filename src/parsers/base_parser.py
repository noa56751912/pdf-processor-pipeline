"""Abstract base class for all report-type parsers."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import AttendanceReport


class BaseParser(ABC):
    @abstractmethod
    def parse(self, text: str) -> AttendanceReport:
        """Parse raw extracted text into a structured AttendanceReport."""
