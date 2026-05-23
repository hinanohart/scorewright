from __future__ import annotations

import sys
from pathlib import Path

import pytest

from helpers import FakeSandbox, exec_result
from scorewright import Candidate
from scorewright.sandbox import SubprocessSandbox
from scorewright.scorers import PerfScorer

PY = sys.executable


def test_median_wall_time_from_fake_runs(tmp_path: Path) -> None:
    durations = [0.10, 0.30, 0.20]  # median 0.20
    sandbox = FakeSandbox(lambda cmd, i: exec_result(duration_s=durations[i]))
    scorer = PerfScorer(sandbox, command=["x"], repeats=3)
    result = scorer.score(Candidate(path=tmp_path))
    assert result.ok is True
    assert result.signal("perf_wall_time_s").value == pytest.approx(0.20)
    assert result.signal("perf_peak_rss_kb").value == pytest.approx(1000.0)


def test_failure_makes_result_not_ok(tmp_path: Path) -> None:
    sandbox = FakeSandbox(lambda cmd, i: exec_result(returncode=1))
    scorer = PerfScorer(sandbox, command=["x"], repeats=2)
    result = scorer.score(Candidate(path=tmp_path))
    assert result.ok is False
    assert result.error is not None


def test_repeats_must_be_positive() -> None:
    with pytest.raises(ValueError):
        PerfScorer(FakeSandbox(lambda c, i: exec_result()), command=["x"], repeats=0)


def test_integration_real_sandbox(tmp_path: Path) -> None:
    sandbox = SubprocessSandbox(memory_mb=None, timeout_s=20)
    scorer = PerfScorer(sandbox, command=[PY, "-c", "sum(range(1000))"], repeats=3)
    result = scorer.score(Candidate(path=tmp_path))
    assert result.ok is True
    assert result.signal("perf_wall_time_s").value > 0
