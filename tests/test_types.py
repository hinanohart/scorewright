from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scorewright import Candidate, ScoreResult, Signal, SignalKind


def _signal(name: str, value: float) -> Signal:
    return Signal(SignalKind.CORRECTNESS, name, value, "ratio", higher_is_better=True)


def test_signal_is_frozen() -> None:
    sig = _signal("a", 1.0)
    with pytest.raises(FrozenInstanceError):
        sig.value = 2.0  # type: ignore[misc]


def test_score_result_signal_lookup_and_values() -> None:
    a, b = _signal("a", 0.5), _signal("b", 0.9)
    result = ScoreResult("s", (a, b), ok=True)
    assert result.signal("a") is a
    assert result.signal("missing") is None
    assert result.values() == {"a": 0.5, "b": 0.9}


def test_failed_result_has_no_signals() -> None:
    result = ScoreResult("s", (), ok=False, error="boom")
    assert result.values() == {}
    assert result.error == "boom"


def test_candidate_defaults() -> None:
    cand = Candidate(path=Path("/tmp/x"))
    assert cand.entrypoint is None
    assert cand.metadata == {}


def test_candidate_accepts_safe_entrypoint() -> None:
    cand = Candidate(path=Path("/tmp/x"), entrypoint="solution.py")
    assert cand.entrypoint == "solution.py"


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "../secret.py",
        "sub/dir/solution.py",
        "/etc/passwd",
        "..",
    ],
)
def test_candidate_rejects_traversal_entrypoint(bad: str) -> None:
    with pytest.raises(ValueError, match="safe relative filename"):
        Candidate(path=Path("/tmp/x"), entrypoint=bad)


def test_signal_kind_values() -> None:
    assert SignalKind.INTEGRITY.value == "integrity"
    assert {k.value for k in SignalKind} == {
        "correctness",
        "performance",
        "cost",
        "quality",
        "integrity",
    }
