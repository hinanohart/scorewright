"""Cost scorer: turn recorded token usage into a USD figure."""

from __future__ import annotations

import time
from collections.abc import Mapping

from .._pricing import ModelPrice
from ..types import Candidate, ScoreResult, Signal, SignalKind


class CostScorer:
    """Computes USD cost from token usage recorded on the candidate.

    The scorer reads usage from ``candidate.metadata["usage"]``, expected to be
    a mapping with ``model`` (str), ``input_tokens`` (int) and ``output_tokens``
    (int). It multiplies those by the supplied ``pricing`` table.

    A pricing table is **required** — scorewright ships no authoritative prices.
    When usage is missing/malformed, or the model is absent from the table, the
    scorer returns ``ok=False`` with an explanation rather than guessing a cost.
    """

    name = "cost"

    def __init__(self, pricing: Mapping[str, ModelPrice]) -> None:
        if not pricing:
            raise ValueError("CostScorer requires a non-empty pricing table")
        self.pricing = dict(pricing)

    def score(self, candidate: Candidate) -> ScoreResult:
        start = time.perf_counter()
        usage = candidate.metadata.get("usage")
        if not isinstance(usage, Mapping):
            return self._fail(start, "no token usage in candidate.metadata['usage']")

        model = usage.get("model")
        if not isinstance(model, str):
            return self._fail(start, "usage is missing a string 'model' field")
        price = self.pricing.get(model)
        if price is None:
            known = ", ".join(sorted(self.pricing)) or "(none)"
            return self._fail(start, f"model {model!r} not in pricing table; known: {known}")

        try:
            input_tokens = int(usage["input_tokens"])
            output_tokens = int(usage["output_tokens"])
        except (KeyError, TypeError, ValueError) as exc:
            return self._fail(start, f"invalid token counts: {exc}")

        try:
            cost = price.cost_usd(input_tokens, output_tokens)
        except ValueError as exc:
            return self._fail(start, str(exc))

        signal = Signal(
            kind=SignalKind.COST,
            name="cost_usd",
            value=cost,
            unit="USD",
            higher_is_better=False,
            raw={
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "input_per_mtok": price.input_per_mtok,
                "output_per_mtok": price.output_per_mtok,
            },
        )
        return ScoreResult(self.name, (signal,), True, None, time.perf_counter() - start)

    def _fail(self, start: float, message: str) -> ScoreResult:
        return ScoreResult(self.name, (), False, message, time.perf_counter() - start)


__all__ = ["CostScorer"]
