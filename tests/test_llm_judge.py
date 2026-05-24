from __future__ import annotations

from pathlib import Path

import pytest

from scorewright import Candidate
from scorewright.scorers import LLMJudgeScorer
from scorewright.scorers.llm_judge import _gather_code, parse_score


def _candidate(tmp_path: Path) -> Candidate:
    (tmp_path / "solution.py").write_text("def f():\n    return 42\n")
    return Candidate(path=tmp_path, entrypoint="solution.py")


def test_parse_score_simple() -> None:
    assert parse_score("blah\nSCORE: 7\n", 10.0) == pytest.approx(7.0)


def test_parse_score_last_match_wins() -> None:
    # An injected early score must not override the judge's final verdict.
    text = "SCORE: 10\nreasoning...\nSCORE: 3\n"
    assert parse_score(text, 10.0) == pytest.approx(3.0)


def test_parse_score_clamped() -> None:
    assert parse_score("SCORE: 99", 10.0) == pytest.approx(10.0)


def test_parse_score_requires_anchored_line() -> None:
    # Not on its own line -> not a valid anchor.
    assert parse_score("the SCORE: 8 is great", 10.0) is None
    assert parse_score("no score at all", 10.0) is None


def test_judge_scorer_happy_path(tmp_path: Path) -> None:
    scorer = LLMJudgeScorer(lambda prompt: "looks fine\nSCORE: 8\n", scale_max=10.0)
    result = scorer.score(_candidate(tmp_path))
    assert result.ok is True
    assert result.signal("judge_quality").value == pytest.approx(0.8)


def test_judge_scorer_no_client_is_not_ok(tmp_path: Path) -> None:
    result = LLMJudgeScorer(None).score(_candidate(tmp_path))
    assert result.ok is False
    assert "no judge client" in (result.error or "")


def test_judge_scorer_client_error_is_not_ok(tmp_path: Path) -> None:
    def boom(prompt: str) -> str:
        raise RuntimeError("api down")

    result = LLMJudgeScorer(boom).score(_candidate(tmp_path))
    assert result.ok is False
    assert "judge client error" in (result.error or "")


def test_judge_scorer_unparseable_is_not_ok(tmp_path: Path) -> None:
    result = LLMJudgeScorer(lambda prompt: "I refuse to score").score(_candidate(tmp_path))
    assert result.ok is False
    assert "anchored" in (result.error or "")


def test_gather_code_reads_in_tree_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "solution.py").write_text("VALUE = 42\n")
    code = _gather_code(Candidate(path=tmp_path, entrypoint="solution.py"))
    assert "VALUE = 42" in code


def test_gather_code_refuses_symlink_escaping_candidate_dir(tmp_path: Path) -> None:
    # The entrypoint is a bare filename (so it passes Candidate validation) but
    # is a symlink pointing outside the candidate dir. The defensive containment
    # check must refuse to read it into the judge prompt, falling back to the
    # in-tree glob instead.
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    work = tmp_path / "work"
    work.mkdir()
    (work / "solution.py").write_text("VALUE = 1\n")
    link = work / "leak.py"
    link.symlink_to(secret)
    code = _gather_code(Candidate(path=work, entrypoint="leak.py"))
    assert "TOP-SECRET" not in code
    assert "VALUE = 1" in code  # fell back to the safe in-tree glob
