"""Correctness scorer: run a candidate's test suite in the sandbox."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

from ..sandbox.base import Sandbox
from ..types import Candidate, ScoreResult, Signal, SignalKind

_DEFAULT_TEST_COMMAND = ("python", "-m", "pytest", "-q", "--tb=no")

# pytest prints exactly one outcome summary line, e.g.
#   "===== 1 failed, 2 passed in 0.34s ====="
# It always ends with " in <duration>s". We parse counts only from such a line
# (taking the last one if several match), so incidental prose elsewhere in
# stdout/stderr is not mistaken for the summary. This alone does not defeat a
# candidate that *deliberately* prints a fake summary line; CorrectnessScorer
# reconciles the parsed counts against pytest's (unforgeable) exit code for that.
_SUMMARY_LINE_RE = re.compile(r"^.*?\bin\s+[\d.]+\s*s\b.*$", re.MULTILINE)
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped)")


@dataclass(frozen=True, slots=True)
class PytestCounts:
    """Parsed pytest outcome counts."""

    passed: int
    failed: int
    errors: int
    skipped: int

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
    """Parse pytest pass/fail/error/skip counts from its summary line.

    Only the pytest summary line (the last line ending in ``in <duration>s``
    that carries outcome counts) is parsed, so incidental prose elsewhere in the
    output is not mistaken for the summary. ``"error"`` and ``"errors"`` are
    summed together. Returns ``None`` if no summary is found. Reconciling a
    deliberately faked summary is the caller's job (see :class:`CorrectnessScorer`,
    which cross-checks the exit code).
    """
    summary: str | None = None
    for line in _SUMMARY_LINE_RE.finditer(output):
        if _COUNT_RE.search(line.group(0)):
            summary = line.group(0)  # keep the last count-bearing summary line
    if summary is None:
        return None
    passed = failed = errors = skipped = 0
    for match in _COUNT_RE.finditer(summary):
        n = int(match.group(1))
        label = match.group(2)
        if label == "passed":
            passed += n
        elif label == "failed":
            failed += n
        elif label.startswith("error"):
            errors += n
        else:  # skipped
            skipped += n
    return PytestCounts(passed, failed, errors, skipped)


def _truncate(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


class CorrectnessScorer:
    """Runs a test command and reports the fraction of tests that pass.

    The pass-rate is parsed from pytest's summary counts (skipped tests are
    excluded from the denominator) and **reconciled against pytest's exit code**,
    which the candidate cannot forge: exit 0 means every collected test passed
    (pass-rate 1.0 regardless of any printed counts), and a failing exit whose
    counts do not corroborate the failure is treated as 0.0 (fail closed). A
    candidate that prints fake counts — even a fake summary at process exit —
    therefore cannot inflate the pass-rate the integrity layer trusts.

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
        if exec_result.returncode not in (0, 1):
            return ScoreResult(
                self.name,
                (),
                False,
                f"test runner failed (exit {exec_result.returncode})",
                duration,
            )

        # pytest's exit code is authoritative and cannot be forged by the
        # candidate's own output: 0 => every collected test passed; 1 => at least
        # one failed. We reconcile the parsed counts against it, so a candidate
        # that prints a fake summary — even at process exit, after pytest's real
        # one — cannot inflate the pass-rate.
        pass_rate: float
        if exec_result.returncode == 0:
            pass_rate = 1.0
            if counts is None:
                raw["fallback"] = "exit-code (no parseable counts)"
        elif counts is not None and (counts.failed + counts.errors) > 0:
            rate = counts.pass_rate
            pass_rate = rate if rate is not None else 0.0
        else:
            # Exit code reports a failure the counts don't corroborate (missing
            # or tampered): fail closed rather than trust an inflated pass-rate.
            pass_rate = 0.0
            raw["fallback"] = "exit-code (counts missing or contradict failing exit)"

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
