from __future__ import annotations

from dataclasses import dataclass

from deepzero.engine.stage import ProcessorContext, ProcessorEntry, ReduceProcessor
from deepzero.stages.sort import bad_direction, descending, metric_reader


class TopKSelector(ReduceProcessor):
    cache_global_keys = ()
    description = "sorts active samples by an upstream metric and keeps only the top k"

    @dataclass
    class Config:
        metric_path: str = ""
        # 0 or less keeps every sample, still ordered by the metric, so a stage
        # can rank work without discarding any of it
        keep_top: int = 10
        sort_order: str = "desc"

    def validate(self, ctx: ProcessorContext) -> list[str]:
        if not self.config.metric_path:
            return [
                "top_k processor requires 'metric_path' configured in format 'stage_name.data_key'"
            ]
        if len(self.config.metric_path.split(".", 1)) != 2:
            return [f"metric_path must be 'processor_name.key', got '{self.config.metric_path}'"]
        return bad_direction("sort_order", self.config.sort_order)

    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        scored = sorted(
            entries,
            key=metric_reader(self.config.metric_path),
            reverse=descending(self.config.sort_order),
        )

        keep_top = self.config.keep_top
        kept = scored if keep_top <= 0 else scored[:keep_top]
        dropped = len(scored) - len(kept)
        if dropped > 0:
            self.log.info(
                "kept %d, dropped %d (metric: %s, order: %s)",
                len(kept),
                dropped,
                self.config.metric_path,
                self.config.sort_order,
            )
        else:
            self.log.info(
                "ranked %d samples by %s (%s), keeping all",
                len(kept),
                self.config.metric_path,
                self.config.sort_order,
            )

        return [s.sample_id for s in kept]
