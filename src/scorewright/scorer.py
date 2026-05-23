"""Scorer protocol and the non-aggregating :class:`CompositeScorer`."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from .types import Candidate, ScoreResult


@runtime_checkable
class Scorer(Protocol):
    """A scorer measures one aspect of a candidate.

    Implementations must:
        * expose a stable ``name``;
        * return a :class:`~scorewright.types.ScoreResult`;
        * set ``ok=False`` with an ``error`` rather than raising for *expected*
          failure modes (missing key, execution error, ...). Unexpected
          exceptions are tolerated by :class:`CompositeScorer`, but a
          well-behaved scorer reports them itself.
    """

    name: str

    def score(self, candidate: Candidate) -> ScoreResult: ...


class CompositeScorer:
    """Runs a list of scorers and collects their results.

    It deliberately performs **no aggregation**: there is no single fitness
    number here. Combining signals (and choosing weights) is the caller's or the
    adapter's explicit responsibility. ``CompositeScorer`` only guarantees that
    one misbehaving scorer cannot abort the whole batch — an unexpected
    exception is captured as a failed :class:`ScoreResult`.
    """

    def __init__(self, scorers: Sequence[Scorer]) -> None:
        if not scorers:
            raise ValueError("CompositeScorer requires at least one scorer")
        self._scorers: tuple[Scorer, ...] = tuple(scorers)

    @property
    def scorers(self) -> tuple[Scorer, ...]:
        return self._scorers

    def score_all(self, candidate: Candidate) -> tuple[ScoreResult, ...]:
        """Score ``candidate`` with every scorer; return one result each."""
        return tuple(self._score_one(scorer, candidate) for scorer in self._scorers)

    @staticmethod
    def _score_one(scorer: Scorer, candidate: Candidate) -> ScoreResult:
        start = time.perf_counter()
        try:
            return scorer.score(candidate)
        except Exception as exc:
            return ScoreResult(
                scorer=getattr(scorer, "name", type(scorer).__name__),
                signals=(),
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                duration_s=time.perf_counter() - start,
            )


def collect_values(results: Iterable[ScoreResult]) -> dict[str, float]:
    """Flatten the measured signals of several results into ``{name: value}``.

    Only signals from ``ok`` results are included. Duplicate signal names across
    scorers overwrite earlier entries, so keep signal names unique. This helper
    is a convenience for adapters; it does not weight or normalize.
    """
    out: dict[str, float] = {}
    for result in results:
        if result.ok:
            out.update(result.values())
    return out


__all__ = ["CompositeScorer", "Scorer", "collect_values"]
