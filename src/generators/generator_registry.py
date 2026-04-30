"""Registry mapping ReportType → BaseGenerator instance."""
from __future__ import annotations

from pathlib import Path

from src.generators.base_generator import BaseGenerator
from src.generators.generator_type_a import GeneratorTypeA
from src.generators.generator_type_b import GeneratorTypeB
from src.type_detector import ReportType

_REGISTRY: dict[str, BaseGenerator] = {
    ReportType.TYPE_A: GeneratorTypeA(),
    ReportType.TYPE_B: GeneratorTypeB(),
}


class GeneratorRegistry:
    @staticmethod
    def get(report_type: ReportType | str) -> BaseGenerator:
        gen = _REGISTRY.get(str(report_type))
        if gen is None:
            raise ValueError(
                f"No generator registered for report type {report_type!r}. "
                "Supported: " + ", ".join(_REGISTRY)
            )
        return gen
