"""Performance scorer: median wall-time and peak RSS over repeated runs."""

from __future__ import annotations

import statistics
import time
from collections.abc import Sequence

from ..sandbox.base import ExecResult, Sandbox
from ..types import Candidate, ScoreResult, Signal, SignalKind


class PerfScorer:
    """Times a command across several runs.

    Runs ``command`` ``repeats`` times in the sandbox and reports the **median**
    wall-clock time (robust to a single slow run) and the maximum observed peak
    RSS. The per-run timings are preserved in ``raw["wall_times_s"]`` — the
    anti-gaming layer reuses them for its performance self-consistency check.

    With ``require_all_ok=True`` (default) the result is ``ok=False`` if any run
    fails or times out, since a partially-failing program has no meaningful
    runtime.
    """

    name = "perf"

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        command: Sequence[str],
        repeats: int = 5,
        timeout_s: float | None = None,
        require_all_ok: bool = True,
    ) -> None:
        if repeats < 1:
            raise ValueError("repeats must be >= 1")
        self.sandbox = sandbox
        self.command = tuple(command)
        self.repeats = repeats
        self.timeout_s = timeout_s
        self.require_all_ok = require_all_ok

    def score(self, candidate: Candidate) -> ScoreResult:
        start = time.perf_counter()
        runs: list[ExecResult] = [
            self.sandbox.run(self.command, cwd=candidate.path, timeout_s=self.timeout_s)
            for _ in range(self.repeats)
        ]
        duration = time.perf_counter() - start

        wall_times = [r.duration_s for r in runs]
        rss_values = [r.peak_rss_kb for r in runs if r.peak_rss_kb is not None]
        failures = [
            {"returncode": r.returncode, "timed_out": r.timed_out} for r in runs if not r.ok
        ]
        raw = {
            "command": list(self.command),
            "repeats": self.repeats,
            "wall_times_s": wall_times,
            "peak_rss_kb": rss_values,
            "returncodes": [r.returncode for r in runs],
            "failures": failures,
        }

        if self.require_all_ok and failures:
            return ScoreResult(
                self.name,
                (),
                False,
                f"{len(failures)}/{self.repeats} runs failed or timed out",
                duration,
            )

        signals = [
            Signal(
                kind=SignalKind.PERFORMANCE,
                name="perf_wall_time_s",
                value=statistics.median(wall_times),
                unit="s",
                higher_is_better=False,
                raw=raw,
            )
        ]
        if rss_values:
            signals.append(
                Signal(
                    kind=SignalKind.PERFORMANCE,
                    name="perf_peak_rss_kb",
                    value=float(max(rss_values)),
                    unit="kb",
                    higher_is_better=False,
                    raw={"peak_rss_kb": rss_values},
                )
            )
        return ScoreResult(self.name, tuple(signals), True, None, duration)


__all__ = ["PerfScorer"]
