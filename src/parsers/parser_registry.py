"""Registry mapping ReportType → BaseParser instance."""
from __future__ import annotations

from src.parsers.base_parser import BaseParser
from src.parsers.parser_type_a import ParserTypeA
from src.parsers.parser_type_b import ParserTypeB
from src.type_detector import ReportType

_REGISTRY: dict[str, BaseParser] = {
    ReportType.TYPE_A: ParserTypeA(),
    ReportType.TYPE_B: ParserTypeB(),
}


class ParserRegistry:
    @staticmethod
    def get(report_type: ReportType | str) -> BaseParser:
        parser = _REGISTRY.get(str(report_type))
        if parser is None:
            raise ValueError(
                f"No parser registered for report type {report_type!r}. "
                "Supported: " + ", ".join(_REGISTRY)
            )
        return parser
