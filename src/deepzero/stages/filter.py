from __future__ import annotations

from typing import Any

from deepzero.engine.stage import MapTool, StageContext, StageResult, StageSpec


class MetadataFilter(MapTool):
    # generic metadata condition evaluator - checks field equality, min/max thresholds, dedup

    def __init__(self, spec: StageSpec):
        super().__init__(spec)
        self._seen: set[str] = set()

    def process(self, ctx: StageContext) -> StageResult:
        config = ctx.config

        # gather all upstream data into a flat view for condition checks
        flat = self._flatten_history(ctx)

        # field requirements
        require = config.get("require", {})
        for field_name, expected_value in require.items():
            actual = flat.get(field_name)
            if actual != expected_value:
                reason = f"filter: {field_name}={actual}, required {expected_value}"
                return StageResult(status="completed", verdict="skip", data={"reject_reason": reason})

        # min thresholds
        for key, value in config.items():
            if key.startswith("min_"):
                field_name = key[4:]
                actual = flat.get(field_name, 0)
                if isinstance(actual, (int, float)) and actual < value:
                    reason = f"filter: {field_name}={actual} < min {value}"
                    return StageResult(status="completed", verdict="skip", data={"reject_reason": reason})

        # max thresholds
        for key, value in config.items():
            if key.startswith("max_"):
                field_name = key[4:]
                actual = flat.get(field_name, 0)
                if isinstance(actual, (int, float)) and actual > value:
                    reason = f"filter: {field_name}={actual} > max {value}"
                    return StageResult(status="completed", verdict="skip", data={"reject_reason": reason})

        # dedup on a data field
        dedup_field = config.get("dedup_field", "")
        if dedup_field:
            dedup_value = flat.get(dedup_field, "")
            if dedup_value:
                if dedup_value in self._seen:
                    return StageResult(
                        status="completed",
                        verdict="skip",
                        data={"reject_reason": f"duplicate {dedup_field}"},
                    )
                self._seen.add(dedup_value)

        return StageResult(status="completed", verdict="continue")

    def _flatten_history(self, ctx: StageContext) -> dict[str, Any]:
        # merge all upstream stage data into one flat dict for backward-compatible lookups
        # later stages overwrite earlier ones if keys collide - this is intentional
        flat: dict[str, Any] = {}
        for output in ctx.history.values():
            flat.update(output.data)
        return flat
