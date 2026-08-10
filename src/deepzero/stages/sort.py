from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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


def metric_reader(path: str) -> Callable[[ProcessorEntry], float]:
    """read a numeric value at `stage.key` off a sample, for ordering.

    Anything missing or unreadable sorts as zero rather than raising: a reducer
    ranks whatever reached it, and one sample whose stage recorded a string
    should not stop the ordering of the rest. Both reducers use this so a change
    to how a metric is read cannot apply to one and not the other.
    """
    stage_name, _, data_key = path.partition(".")

    def _read(entry: ProcessorEntry) -> float:
        output = entry.history.get(stage_name)
        if output is None:
            return 0.0
        try:
            return float(output.data.get(data_key, 0))
        except (TypeError, ValueError):
            return 0.0

    return _read


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
        scored = sorted(
            samples,
            key=metric_reader(self.config.by),
            reverse=descending(self.config.order),
        )
        self.log.info(
            "sorted %d samples by %s (%s)",
            len(scored),
            self.config.by,
            self.config.order,
        )
        return [s.sample_id for s in scored]
