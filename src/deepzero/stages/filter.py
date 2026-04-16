from __future__ import annotations

from typing import Any

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorResult,
    StageSpec,
    ProcessorEntry,
)


class MetadataFilter(MapProcessor):
    description = "generic metadata condition evaluator - checks field equality, min/max thresholds, dedup"

    def __init__(self, spec: StageSpec):
        super().__init__(spec)
        self._seen: set[str] = set()

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        config = self.config

        flat = self._flatten_history(entry)

        # field requirements
        require = config.get("require", {})
        for field_name, expected_value in require.items():
            actual = flat.get(field_name)
            if actual != expected_value:
                return ProcessorResult.filter(
                    f"{field_name}={actual}, required {expected_value}"
                )

        # min thresholds
        for key, value in config.items():
            if key.startswith("min_"):
                field_name = key[4:]
                actual = flat.get(field_name, 0)
                if isinstance(actual, (int, float)) and actual < value:
                    return ProcessorResult.filter(
                        f"{field_name}={actual} < min {value}"
                    )

        # max thresholds
        for key, value in config.items():
            if key.startswith("max_"):
                field_name = key[4:]
                actual = flat.get(field_name, 0)
                if isinstance(actual, (int, float)) and actual > value:
                    return ProcessorResult.filter(
                        f"{field_name}={actual} > max {value}"
                    )

        # dedup on a data field
        dedup_field = config.get("dedup_field", "")
        if dedup_field:
            dedup_value = flat.get(dedup_field, "")
            if dedup_value:
                if dedup_value in self._seen:
                    return ProcessorResult.filter(f"duplicate {dedup_field}")
                self._seen.add(dedup_value)

        return ProcessorResult.ok()

    def _flatten_history(self, entry: ProcessorEntry) -> dict[str, Any]:
        # merge all upstream processor data into one flat dict
        flat: dict[str, Any] = {}
        for output in entry.history.values():
            flat.update(output.data)
        return flat
