"""LLM-judge scorer (GenRM-style) with hardened structured-output parsing.

The judge model is injected as a plain ``Callable[[str], str]`` (prompt ->
response text), so scorewright takes no hard dependency on any LLM SDK and never
touches API keys itself. If no client is supplied, or the client raises, the
scorer fails closed (``ok=False``) rather than inventing a quality score.

The response parser is deliberately strict — line-anchored, last-match-wins,
fail-closed — to resist prompt-injection and rambling outputs. The same
:func:`parse_score` primitive backs the anti-gaming structured-output anchor.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from ..types import Candidate, ScoreResult, Signal, SignalKind

JudgeClient = Callable[[str], str]

# Line-anchored "SCORE: <number>" / "SCORE = <number>". MULTILINE so it must own
# its line; we take the LAST match so a trailing verdict wins over any injected
# earlier "SCORE:" planted in the candidate or a chain-of-thought preamble.
_SCORE_RE = re.compile(r"^\s*SCORE\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*$", re.MULTILINE)

_DEFAULT_RUBRIC = (
    "You are a strict code reviewer. Rate the candidate solution's overall "
    "quality (correctness, clarity, robustness). Think briefly, then end your "
    "reply with a single line in EXACTLY this format and nothing after it:\n"
    "SCORE: <number from 0 to {scale_max}>"
)
_DEFAULT_SOURCE_GLOBS = ("solution.py", "*.py")
_MAX_CODE_CHARS = 12000


def parse_score(text: str, scale_max: float) -> float | None:
    """Extract a 0..``scale_max`` score from judge output, or ``None``.

    Returns the last line-anchored ``SCORE:`` value, clamped to
    ``[0, scale_max]``. Returns ``None`` (fail-closed) when no anchored score is
    present.
    """
    matches = _SCORE_RE.findall(text)
    if not matches:
        return None
    value = float(matches[-1])
    return max(0.0, min(scale_max, value))


def _is_within(path: Path, root: Path) -> bool:
    """Return ``True`` iff ``path`` resolves to a location inside ``root``."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _gather_code(candidate: Candidate) -> str:
    files: list[Path] = []
    if candidate.entrypoint:
        entry = candidate.path / candidate.entrypoint
        # Defence in depth: Candidate validates entrypoint, but never feed an
        # out-of-tree file into a prompt sent to an external LLM regardless.
        if _is_within(entry, candidate.path) and entry.is_file():
            files.append(entry)
    if not files:
        for pattern in _DEFAULT_SOURCE_GLOBS:
            files = [
                f for f in sorted(candidate.path.glob(pattern)) if _is_within(f, candidate.path)
            ]
            if files:
                break
    parts: list[str] = []
    total = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippet = f"# --- {path.name} ---\n{text}\n"
        if total + len(snippet) > _MAX_CODE_CHARS:
            snippet = snippet[: _MAX_CODE_CHARS - total] + "\n...[truncated]\n"
            parts.append(snippet)
            break
        parts.append(snippet)
        total += len(snippet)
    return "".join(parts)


class LLMJudgeScorer:
    """Asks an injected judge model for a quality score in ``[0, 1]``."""

    name = "llm_judge"

    def __init__(
        self,
        judge_client: JudgeClient | None,
        *,
        rubric: str = _DEFAULT_RUBRIC,
        scale_max: float = 10.0,
        source_globs: Sequence[str] = _DEFAULT_SOURCE_GLOBS,
    ) -> None:
        if scale_max <= 0:
            raise ValueError("scale_max must be positive")
        self.judge_client = judge_client
        self.rubric = rubric
        self.scale_max = scale_max
        self.source_globs = tuple(source_globs)

    def _build_prompt(self, candidate: Candidate) -> str:
        rubric = self.rubric.format(scale_max=self.scale_max)
        code = _gather_code(candidate)
        return f"{rubric}\n\n=== CANDIDATE CODE ===\n{code}\n=== END ===\n"

    def score(self, candidate: Candidate) -> ScoreResult:
        start = time.perf_counter()
        if self.judge_client is None:
            return ScoreResult(
                self.name, (), False, "no judge client provided", time.perf_counter() - start
            )
        prompt = self._build_prompt(candidate)
        try:
            response = self.judge_client(prompt)
        except Exception as exc:
            return ScoreResult(
                self.name,
                (),
                False,
                f"judge client error: {type(exc).__name__}: {exc}",
                time.perf_counter() - start,
            )

        raw_score = parse_score(response, self.scale_max)
        duration = time.perf_counter() - start
        if raw_score is None:
            return ScoreResult(
                self.name,
                (),
                False,
                "judge response had no anchored 'SCORE:' line",
                duration,
            )

        normalized = raw_score / self.scale_max
        signal = Signal(
            kind=SignalKind.QUALITY,
            name="judge_quality",
            value=normalized,
            unit="ratio",
            higher_is_better=True,
            raw={
                "raw_score": raw_score,
                "scale_max": self.scale_max,
                "response": response[:4000],
            },
        )
        return ScoreResult(self.name, (signal,), True, None, duration)


__all__ = ["JudgeClient", "LLMJudgeScorer", "parse_score"]
