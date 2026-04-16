from __future__ import annotations

from dataclasses import dataclass

from deepzero.engine.stage import ProcessorContext, ProcessorEntry, ReduceProcessor


class TopKSelector(ReduceProcessor):
    description = "sorts active samples by an upstream metric and keeps only the top k"

    @dataclass
    class Config:
        metric_path: str = ""
        keep_top: int = 10
        sort_order: str = "desc"

    def validate(self, ctx: ProcessorContext) -> list[str]:
        if not self.config.metric_path:
            return [
                "top_k processor requires 'metric_path' configured in format 'stage_name.data_key'"
            ]
        if len(self.config.metric_path.split(".", 1)) != 2:
            return [f"metric_path must be 'processor_name.key', got '{self.config.metric_path}'"]
        return []

    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        parts = self.config.metric_path.split(".", 1)
        stage_name, data_key = parts

        def _get_metric(s: ProcessorEntry) -> float:
            output = s.history.get(stage_name)
            if output is None:
                return 0.0
            val = output.data.get(data_key, 0)
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        reverse = self.config.sort_order == "desc"
        scored = sorted(entries, key=_get_metric, reverse=reverse)

        kept = scored[: self.config.keep_top]
        dropped = len(scored) - len(kept)
        if dropped > 0:
            self.log.info(
                "top_k: kept %d, dropped %d (metric: %s, order: %s)",
                len(kept),
                dropped,
                self.config.metric_path,
                self.config.sort_order,
            )

        return [s.sample_id for s in kept]
