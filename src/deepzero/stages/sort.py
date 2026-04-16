from __future__ import annotations

from dataclasses import dataclass

from deepzero.engine.stage import ReduceProcessor, ProcessorEntry, ProcessorContext


class Sort(ReduceProcessor):
    description = "sorts active samples by an upstream data field - preserves all samples, changes processing order"

    @dataclass
    class Config:
        by: str = ""
        order: str = "desc"

    def process(
        self, ctx: ProcessorContext, samples: list[ProcessorEntry]
    ) -> list[str]:
        if not self.config.by:
            self.log.warning("no 'by' field configured, preserving current order")
            return [s.sample_id for s in samples]

        parts = self.config.by.split(".", 1)
        if len(parts) != 2:
            self.log.warning(
                "'by' must be 'processor_name.key', got '%s'", self.config.by
            )
            return [s.sample_id for s in samples]

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
