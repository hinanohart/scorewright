"""Correctness scorer: run a candidate's test suite in the sandbox."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence

from ..sandbox.base import Sandbox
from ..types import Candidate, ScoreResult, Signal, SignalKind

_DEFAULT_TEST_COMMAND = ("python", "-m", "pytest", "-q", "--tb=no")

# pytest summary fragments, e.g. "3 passed", "1 failed", "2 errors", "5 skipped".
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped)")


class PytestCounts:
    """Parsed pytest outcome counts."""

    __slots__ = ("errors", "failed", "passed", "skipped")

    def __init__(self, passed: int, failed: int, errors: int, skipped: int) -> None:
        self.passed = passed
        self.failed = failed
        self.errors = errors
        self.skipped = skipped

    @property
    def graded(self) -> int:
        """Tests that count toward the pass-rate denominator (excludes skipped)."""
        return self.passed + self.failed + self.errors

    @property
    def pass_rate(self) -> float | None:
        return self.passed / self.graded if self.graded else None

    def as_dict(self) -> dict[str, int]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
        }


def parse_pytest_counts(output: str) -> PytestCounts | None:
    """Parse pytest pass/fail/error/skip counts from its output.

    Returns ``None`` if no recognizable counts are present. ``"error"`` and
    ``"errors"`` are summed together.
    """
    found = False
    passed = failed = errors = skipped = 0
    for match in _COUNT_RE.finditer(output):
        found = True
        n = int(match.group(1))
        label = match.group(2)
        if label == "passed":
            passed += n
        elif label == "failed":
            failed += n
        elif label in ("error", "errors"):
            errors += n
        elif label == "skipped":
            skipped += n
    if not found:
        return None
    return PytestCounts(passed, failed, errors, skipped)


def _truncate(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


class CorrectnessScorer:
    """Runs a test command and reports the fraction of tests that pass.

    The pass-rate is parsed from pytest's summary counts (skipped tests are
    excluded from the denominator). If counts cannot be parsed, the scorer falls
    back to the process exit code (0 -> 1.0, otherwise 0.0) and records the
    fallback in ``raw``.

    A result is ``ok=False`` (no fabricated value) when the run times out, when
    no tests are collected (pytest exit code 5), or when the runner itself fails
    (exit codes other than 0/1).
    """

    name = "correctness"

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        test_command: Sequence[str] = _DEFAULT_TEST_COMMAND,
        timeout_s: float | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.test_command = tuple(test_command)
        self.timeout_s = timeout_s

    def score(self, candidate: Candidate) -> ScoreResult:
        start = time.perf_counter()
        exec_result = self.sandbox.run(
            self.test_command, cwd=candidate.path, timeout_s=self.timeout_s
        )
        duration = time.perf_counter() - start
        combined = exec_result.stdout + "\n" + exec_result.stderr
        counts = parse_pytest_counts(combined)

        raw = {
            "returncode": exec_result.returncode,
            "timed_out": exec_result.timed_out,
            "counts": counts.as_dict() if counts else None,
            "stdout": _truncate(exec_result.stdout),
            "stderr": _truncate(exec_result.stderr),
            "command": list(self.test_command),
        }

        if exec_result.timed_out:
            return ScoreResult(self.name, (), False, "test run timed out", duration)
        if exec_result.returncode == 5:
            return ScoreResult(self.name, (), False, "no tests collected", duration)

        pass_rate: float | None = counts.pass_rate if counts else None
        if pass_rate is None:
            if exec_result.returncode in (0, 1):
                pass_rate = 1.0 if exec_result.returncode == 0 else 0.0
                raw["fallback"] = "exit-code (no parseable counts)"
            else:
                return ScoreResult(
                    self.name,
                    (),
                    False,
                    f"test runner failed (exit {exec_result.returncode})",
                    duration,
                )

        signal = Signal(
            kind=SignalKind.CORRECTNESS,
            name="correctness_pass_rate",
            value=pass_rate,
            unit="ratio",
            higher_is_better=True,
            raw=raw,
        )
        return ScoreResult(self.name, (signal,), True, None, duration)


__all__ = ["CorrectnessScorer", "PytestCounts", "parse_pytest_counts"]
