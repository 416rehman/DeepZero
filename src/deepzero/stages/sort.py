from __future__ import annotations

from dataclasses import dataclass

from deepzero.engine.stage import ProcessorContext, ProcessorEntry, ReduceProcessor

# the words a pipeline may use for a sort direction. Every reducer that orders
# samples reads them from here, so `desc` cannot mean one thing in one stage and
# something else in the next.
_DESCENDING = ("desc", "descending")
_ASCENDING = ("asc", "ascending")


def descending(order: str) -> bool:
    """whether `order` asks for largest first. Case and spelling are forgiving."""
    return order.strip().lower() in _DESCENDING


def bad_direction(field: str, order: str) -> list[str]:
    """report an order this pipeline cannot mean, rather than picking one for it.

    A direction that is not recognised used to fall through to ascending, so
    `DESC` or `dsc` silently ranked the least interesting samples first and, in
    a stage that also truncates, kept those and discarded the rest.
    """
    if order.strip().lower() in _DESCENDING + _ASCENDING:
        return []
    accepted = ", ".join(_ASCENDING + _DESCENDING)
    return [f"'{field}' must be one of {accepted}, got '{order}'"]


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
        return bad_direction("order", self.config.order)

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

        scored = sorted(samples, key=_get_val, reverse=descending(self.config.order))
        self.log.info(
            "sorted %d samples by %s (%s)",
            len(scored),
            self.config.by,
            self.config.order,
        )
        return [s.sample_id for s in scored]
