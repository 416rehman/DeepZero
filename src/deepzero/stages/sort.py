from __future__ import annotations

from dataclasses import dataclass

from deepzero.engine.stage import ProcessorContext, ProcessorEntry, ReduceProcessor


class Sort(ReduceProcessor):
    description = "sorts active samples by an upstream data field - preserves all samples, changes processing order"

    @dataclass
    class Config:
        by: str = ""
        order: str = "desc"

    def validate(self, ctx: ProcessorContext) -> list[str]:
        if not self.config.by:
            return ["sort processor requires 'by' configured in format 'stage_name.data_key'"]
        if len(self.config.by.split(".", 1)) != 2:
            return [f"'by' must be 'processor_name.key', got '{self.config.by}'"]
        return []

    def process(self, ctx: ProcessorContext, samples: list[ProcessorEntry]) -> list[str]:
        parts = self.config.by.split(".", 1)
        stage_name, data_key = parts

        def _get_val(s: ProcessorEntry) -> float:
            output = s.history.get(stage_name)
            if output is None:
                return 0.0
            val = output.data.get(data_key, 0)
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        reverse = self.config.order == "desc"
        scored = sorted(samples, key=_get_val, reverse=reverse)
        self.log.info(
            "sorted %d samples by %s (%s)",
            len(scored),
            self.config.by,
            self.config.order,
        )
        return [s.sample_id for s in scored]
