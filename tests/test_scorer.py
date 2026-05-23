from __future__ import annotations

from pathlib import Path

import pytest

from scorewright import Candidate, CompositeScorer, ScoreResult, Signal, SignalKind
from scorewright.scorer import collect_values


class _OkScorer:
    name = "ok"

    def __init__(self, signal_name: str, value: float) -> None:
        self._signal_name = signal_name
        self._value = value

    def score(self, candidate: Candidate) -> ScoreResult:
        sig = Signal(SignalKind.QUALITY, self._signal_name, self._value, "ratio", True)
        return ScoreResult(self.name, (sig,), ok=True)


class _RaisingScorer:
    name = "boom"

    def score(self, candidate: Candidate) -> ScoreResult:
        raise RuntimeError("kaboom")


def _candidate() -> Candidate:
    return Candidate(path=Path("/tmp"))


def test_requires_at_least_one_scorer() -> None:
    with pytest.raises(ValueError):
        CompositeScorer([])


def test_score_all_runs_every_scorer() -> None:
    comp = CompositeScorer([_OkScorer("a", 0.1), _OkScorer("b", 0.2)])
    results = comp.score_all(_candidate())
    assert len(results) == 2
    assert all(r.ok for r in results)


def test_exception_is_isolated_as_failed_result() -> None:
    comp = CompositeScorer([_OkScorer("a", 0.1), _RaisingScorer()])
    results = comp.score_all(_candidate())
    assert results[0].ok is True
    assert results[1].ok is False
    assert results[1].error is not None and "kaboom" in results[1].error


def test_collect_values_flattens_only_ok_results() -> None:
    ok = ScoreResult("a", (Signal(SignalKind.QUALITY, "x", 0.5, "ratio", True),), ok=True)
    bad = ScoreResult("b", (), ok=False, error="nope")
    assert collect_values([ok, bad]) == {"x": 0.5}
