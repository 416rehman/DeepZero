from __future__ import annotations

import threading
from typing import Any

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
    StageSpec,
)


class MetadataFilter(MapProcessor):
    cache_global_keys = ()
    description = (
        "generic metadata condition evaluator - checks field equality, min/max thresholds, dedup"
    )

    def __init__(self, spec: StageSpec):
        super().__init__(spec)
        # dedup is the one thing here that remembers other samples, and a Map
        # processor runs across a thread pool. Testing membership and adding are
        # two separate steps, so without this lock two threads holding the same
        # value can both find it absent and both pass, which is silently the
        # opposite of what dedup_field was asked to do.
        self._seen: set[str] = set()
        self._seen_lock = threading.Lock()

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        config = self.config

        flat = self._flatten_history(entry)

        # field requirements. `require:` written with nothing under it parses as
        # null rather than as an empty mapping, and a config left half-edited
        # should require nothing rather than fail every sample it is given.
        require = config.get("require") or {}
        for field_name, expected_value in require.items():
            actual = flat.get(field_name)
            if actual != expected_value:
                return ProcessorResult.filter(f"{field_name}={actual}, required {expected_value}")

        # min thresholds
        for key, value in config.items():
            if key.startswith("min_"):
                field_name = key[4:]
                actual = flat.get(field_name, 0)
                if isinstance(actual, (int, float)) and actual < value:
                    return ProcessorResult.filter(f"{field_name}={actual} < min {value}")

        # max thresholds
        for key, value in config.items():
            if key.startswith("max_"):
                field_name = key[4:]
                actual = flat.get(field_name, 0)
                if isinstance(actual, (int, float)) and actual > value:
                    return ProcessorResult.filter(f"{field_name}={actual} > max {value}")

        # dedup on a data field
        dedup_field = config.get("dedup_field", "")
        if dedup_field:
            dedup_value = flat.get(dedup_field, "")
            if dedup_value:
                with self._seen_lock:
                    first = dedup_value not in self._seen
                    self._seen.add(dedup_value)
                if not first:
                    return ProcessorResult.filter(f"duplicate {dedup_field}")

        return ProcessorResult.ok()

    def _flatten_history(self, entry: ProcessorEntry) -> dict[str, Any]:
        # merge all upstream processor data into one flat dict
        flat: dict[str, Any] = {}
        for output in entry.history.values():
            flat.update(output.data)
        return flat
