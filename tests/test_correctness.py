from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scorewright import Candidate
from scorewright.sandbox import SubprocessSandbox
from scorewright.scorers import CorrectnessScorer
from scorewright.scorers.correctness import parse_pytest_counts

PY = sys.executable
TEST_CMD = [PY, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider"]


@pytest.fixture
def sandbox() -> SubprocessSandbox:
    # Disable the address-space limit so the inner pytest interpreter is not
    # starved; correctness is about exit/parse behaviour, not memory limits.
    return SubprocessSandbox(memory_mb=None, cpu_seconds=30, timeout_s=120)


def _write(tmp_path: Path, body: str) -> Candidate:
    (tmp_path / "test_candidate.py").write_text(body)
    return Candidate(path=tmp_path)


def test_parse_pytest_counts_basic() -> None:
    counts = parse_pytest_counts("=== 3 passed, 1 failed, 2 skipped in 0.1s ===")
    assert counts is not None
    assert (counts.passed, counts.failed, counts.skipped) == (3, 1, 2)
    assert counts.graded == 4
    assert counts.pass_rate == pytest.approx(0.75)


def test_parse_pytest_counts_errors_summed() -> None:
    counts = parse_pytest_counts("1 passed, 2 errors in 0.1s")
    assert counts is not None
    assert counts.errors == 2
    assert counts.pass_rate == pytest.approx(1 / 3)


def test_parse_pytest_counts_none_when_unparseable() -> None:
    assert parse_pytest_counts("no recognizable summary here") is None


def test_parse_ignores_non_summary_prose() -> None:
    # A stray "7 passed" in prose (no "in <duration>s") must not be parsed as a
    # summary; only the genuine summary line is used.
    out = "note: 7 passed earlier today\n=== 1 passed in 0.01s ===\n"
    counts = parse_pytest_counts(out)
    assert counts is not None
    assert counts.passed == 1


def test_parse_uses_last_summary_when_candidate_fakes_one() -> None:
    # A gaming candidate prints a fake summary first; pytest's real summary is
    # last, so the last count-bearing summary line wins.
    out = "999 passed in 0.001s\n.\n1 failed, 1 passed in 0.02s\n"
    counts = parse_pytest_counts(out)
    assert counts is not None
    assert (counts.passed, counts.failed) == (1, 1)


def test_all_tests_pass(sandbox: SubprocessSandbox, tmp_path: Path) -> None:
    cand = _write(tmp_path, "def test_a():\n    assert 1 + 1 == 2\n")
    result = CorrectnessScorer(sandbox, test_command=TEST_CMD).score(cand)
    assert result.ok is True
    assert result.signal("correctness_pass_rate").value == pytest.approx(1.0)


def test_partial_failure_gives_fractional_rate(sandbox: SubprocessSandbox, tmp_path: Path) -> None:
    body = "def test_pass():\n    assert True\n\ndef test_fail():\n    assert False\n"
    cand = _write(tmp_path, body)
    result = CorrectnessScorer(sandbox, test_command=TEST_CMD).score(cand)
    assert result.ok is True
    assert result.signal("correctness_pass_rate").value == pytest.approx(0.5)


def test_no_tests_collected_is_not_ok(sandbox: SubprocessSandbox, tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("x = 1\n")
    result = CorrectnessScorer(sandbox, test_command=TEST_CMD).score(Candidate(path=tmp_path))
    assert result.ok is False
    assert result.error is not None


def test_exit_code_overrides_trailing_fake_summary(
    sandbox: SubprocessSandbox, tmp_path: Path
) -> None:
    # A failing test whose process prints a fake "all passed" summary at exit
    # (after pytest's real summary). pytest's exit code (1) is authoritative and
    # cannot be forged, so the pass-rate must be 0.0, not inflated to 1.0.
    (tmp_path / "conftest.py").write_text(
        "import atexit, os\natexit.register(lambda: os.write(1, b'999 passed in 0.00s\\n'))\n"
    )
    (tmp_path / "test_candidate.py").write_text("def test_fail():\n    assert False\n")
    result = CorrectnessScorer(sandbox, test_command=TEST_CMD).score(Candidate(path=tmp_path))
    assert result.ok is True
    assert result.signal("correctness_pass_rate").value == 0.0
