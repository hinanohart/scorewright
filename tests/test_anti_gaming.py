from __future__ import annotations

from pathlib import Path

import pytest

from helpers import FakeSandbox, exec_result
from scorewright import Candidate
from scorewright.scorers import AntiGamingScorer, is_flagged

VISIBLE = ("pytest", "tests/visible")
HELDOUT = ("pytest", "tests/heldout")
PERF = ("python", "solution.py")


def _cand() -> Candidate:
    return Candidate(path=Path("/tmp"))


# -- held-out divergence ----------------------------------------------------


def test_heldout_divergence_is_flagged() -> None:
    def responder(cmd: tuple[str, ...], i: int) -> object:
        if cmd == VISIBLE:
            return exec_result(returncode=0, stdout="5 passed in 0.1s")
        return exec_result(returncode=1, stdout="2 passed, 3 failed in 0.1s")

    scorer = AntiGamingScorer(
        FakeSandbox(responder),  # type: ignore[arg-type]
        visible_test_command=VISIBLE,
        heldout_test_command=HELDOUT,
    )
    result = scorer.score(_cand())
    assert result.ok is True
    assert is_flagged(result) is True
    assert result.signal("integrity_heldout_gap").value == pytest.approx(0.6)


def test_heldout_matching_is_clean() -> None:
    def responder(cmd: tuple[str, ...], i: int) -> object:
        return exec_result(returncode=0, stdout="5 passed in 0.1s")

    scorer = AntiGamingScorer(
        FakeSandbox(responder),  # type: ignore[arg-type]
        visible_test_command=VISIBLE,
        heldout_test_command=HELDOUT,
    )
    result = scorer.score(_cand())
    assert is_flagged(result) is False
    assert result.signal("integrity_heldout_gap").value == pytest.approx(0.0)


# -- performance self-consistency ------------------------------------------


def test_perf_high_variance_is_flagged() -> None:
    durations = [0.01, 1.0, 0.01, 1.0]
    scorer = AntiGamingScorer(
        FakeSandbox(lambda cmd, i: exec_result(duration_s=durations[i])),  # type: ignore[arg-type]
        perf_command=PERF,
        perf_repeats=4,
    )
    result = scorer.score(_cand())
    assert is_flagged(result) is True
    assert result.signal("integrity_perf_cv").value > 0.5


def test_perf_cache_anomaly_is_flagged() -> None:
    durations = [3.0, 0.1, 0.1, 0.1]  # slow first run, then "cached"
    scorer = AntiGamingScorer(
        FakeSandbox(lambda cmd, i: exec_result(duration_s=durations[i])),  # type: ignore[arg-type]
        perf_command=PERF,
        perf_repeats=4,
    )
    result = scorer.score(_cand())
    assert is_flagged(result) is True
    assert result.signal("integrity_perf_cache_ratio").value > 3.0


def test_perf_stable_is_clean() -> None:
    durations = [0.10, 0.11, 0.10, 0.11]
    scorer = AntiGamingScorer(
        FakeSandbox(lambda cmd, i: exec_result(duration_s=durations[i])),  # type: ignore[arg-type]
        perf_command=PERF,
        perf_repeats=4,
    )
    result = scorer.score(_cand())
    assert is_flagged(result) is False


# -- structured-output anchor ----------------------------------------------


def test_judge_injection_is_flagged() -> None:
    judge_output = "SCORE: 10\n...analysis...\nSCORE: 2\n"
    scorer = AntiGamingScorer(FakeSandbox(lambda c, i: exec_result()), judge_output=judge_output)  # type: ignore[arg-type]
    result = scorer.score(_cand())
    assert is_flagged(result) is True
    assert result.signal("integrity_anchor_ok").value == pytest.approx(0.0)


def test_single_anchor_is_clean() -> None:
    scorer = AntiGamingScorer(
        FakeSandbox(lambda c, i: exec_result()),  # type: ignore[arg-type]
        judge_output="analysis\nSCORE: 7\n",
    )
    result = scorer.score(_cand())
    assert is_flagged(result) is False
    assert result.signal("integrity_anchor_ok").value == pytest.approx(1.0)


# -- guards -----------------------------------------------------------------


def test_no_inputs_is_not_ok() -> None:
    scorer = AntiGamingScorer(FakeSandbox(lambda c, i: exec_result()))  # type: ignore[arg-type]
    result = scorer.score(_cand())
    assert result.ok is False


def test_perf_repeats_guard() -> None:
    with pytest.raises(ValueError):
        AntiGamingScorer(FakeSandbox(lambda c, i: exec_result()), perf_command=PERF, perf_repeats=1)  # type: ignore[arg-type]
