from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from scorewright import Candidate, CompositeScorer, ScoreResult, Signal, SignalKind
from scorewright.adapters import to_openevolve_evaluator


class _StaticScorer:
    def __init__(self, name: str, signal_name: str, value: float, kind: SignalKind) -> None:
        self.name = name
        self._sn = signal_name
        self._v = value
        self._kind = kind

    def score(self, candidate: Candidate) -> ScoreResult:
        sig = Signal(self._kind, self._sn, self._v, "ratio", True)
        return ScoreResult(self.name, (sig,), ok=True)


class _GamingScorer:
    name = "anti_gaming"

    def __init__(self, flagged: bool) -> None:
        self._flagged = flagged

    def score(self, candidate: Candidate) -> ScoreResult:
        sig = Signal(
            SignalKind.INTEGRITY,
            "integrity_flagged",
            1.0 if self._flagged else 0.0,
            "bool",
            higher_is_better=False,
        )
        return ScoreResult(self.name, (sig,), ok=True)


def test_evaluate_returns_metric_dict(tmp_path: Path) -> None:
    scorer = CompositeScorer(
        [
            _StaticScorer("correctness", "correctness_pass_rate", 0.9, SignalKind.CORRECTNESS),
            _StaticScorer("perf", "perf_wall_time_s", 0.5, SignalKind.PERFORMANCE),
        ]
    )
    evaluate = to_openevolve_evaluator(scorer)
    metrics = evaluate(str(tmp_path))
    assert metrics == {"correctness_pass_rate": 0.9, "perf_wall_time_s": 0.5}
    assert all(isinstance(v, float) for v in metrics.values())


def test_aggregate_injects_combined_score(tmp_path: Path) -> None:
    scorer = _StaticScorer("correctness", "correctness_pass_rate", 0.8, SignalKind.CORRECTNESS)
    evaluate = to_openevolve_evaluator(
        scorer, aggregate=lambda m: m.get("correctness_pass_rate", 0.0) * 100
    )
    metrics = evaluate(str(tmp_path))
    assert metrics["combined_score"] == pytest.approx(80.0)


def test_reject_on_gaming_forces_reject_score(tmp_path: Path) -> None:
    scorer = CompositeScorer(
        [
            _StaticScorer("correctness", "correctness_pass_rate", 1.0, SignalKind.CORRECTNESS),
            _GamingScorer(flagged=True),
        ]
    )
    evaluate = to_openevolve_evaluator(
        scorer,
        aggregate=lambda m: 100.0,
        reject_on_gaming=True,
        reject_score=-1.0,
    )
    metrics = evaluate(str(tmp_path))
    assert metrics["combined_score"] == pytest.approx(-1.0)


def test_reject_off_keeps_aggregate_even_if_flagged(tmp_path: Path) -> None:
    scorer = CompositeScorer(
        [
            _StaticScorer("correctness", "correctness_pass_rate", 1.0, SignalKind.CORRECTNESS),
            _GamingScorer(flagged=True),
        ]
    )
    evaluate = to_openevolve_evaluator(scorer, aggregate=lambda m: 42.0, reject_on_gaming=False)
    metrics = evaluate(str(tmp_path))
    assert metrics["combined_score"] == pytest.approx(42.0)
    assert metrics["integrity_flagged"] == pytest.approx(1.0)


def test_metadata_factory_and_file_path(tmp_path: Path) -> None:
    program = tmp_path / "solution.py"
    program.write_text("x = 1\n")
    seen: dict[str, object] = {}

    def factory(path: str) -> Mapping[str, object]:
        seen["path"] = path
        return {"usage": {"model": "demo", "input_tokens": 1, "output_tokens": 1}}

    class _MetaScorer:
        name = "meta"

        def score(self, candidate: Candidate) -> ScoreResult:
            # entrypoint derived from a file path; metadata threaded through
            assert candidate.entrypoint == "solution.py"
            assert candidate.metadata["usage"]["model"] == "demo"  # type: ignore[index]
            return ScoreResult(
                self.name, (Signal(SignalKind.COST, "cost_usd", 0.0, "USD", False),), ok=True
            )

    evaluate = to_openevolve_evaluator(_MetaScorer(), metadata_factory=factory)
    metrics = evaluate(str(program))
    assert seen["path"] == str(program)
    assert "cost_usd" in metrics
