"""Anti-gaming integrity scorer.

Reward hacking / scorer gaming is normally checked *offline*, after a run. This
scorer instead produces **integrity signals as a first-class part of fitness**,
so an evolution / agent loop can see — every generation — whether a candidate is
likely gaming the scorer rather than solving the task. The checks are
deterministic heuristics (no ML, no fabricated values):

1. **Held-out divergence** — a candidate that scores far higher on visible tests
   than on held-out tests is overfitting the graded set.
2. **Performance self-consistency** — re-running the *same* input should give
   stable timings. A large coefficient of variation, or a first-run that is much
   slower than the rest, hints at sleeping/caching tricks that game a perf score.
3. **Structured-output anchor** — a judge response should contain exactly one
   line-anchored ``SCORE:``. Extra anchored scores suggest an injection planted
   to fool an LLM judge.

The scorer is **warn-only**: it *measures* integrity and emits an
``integrity_flagged`` signal (1.0 = suspicious, 0.0 = clean) plus the reasons,
but it never itself rejects a candidate — that judgment belongs to the caller or
the adapter (opt in via the OpenEvolve adapter's ``reject_on_gaming``). This
keeps measurement separate from judgment, consistent with the rest of
scorewright. Thresholds are heuristic and configurable; treat the flag as a
prompt to look, not as proof.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Sequence

from ..sandbox.base import Sandbox
from ..types import Candidate, ScoreResult, Signal, SignalKind
from .correctness import parse_pytest_counts
from .llm_judge import _SCORE_RE


class AntiGamingScorer:
    """Emits deterministic integrity signals for a candidate.

    Each check is optional and runs only if its inputs are supplied. At least
    one check must be runnable, otherwise the result is ``ok=False``.

    Args:
        sandbox: Sandbox used to execute test / perf commands.
        visible_test_command: Test command for the graded (visible) set.
        heldout_test_command: Test command for the held-out set. Both visible
            and held-out commands are required to run the divergence check.
        perf_command: Command timed repeatedly for the self-consistency check.
        perf_repeats: Number of identical perf runs (>= 2).
        judge_output: A judge response string to anchor-check (often taken from
            ``candidate.metadata['judge_output']`` if not passed here).
        heldout_gap_threshold: Flag if ``visible - heldout`` pass-rate exceeds this.
        perf_cv_threshold: Flag if the coefficient of variation of timings exceeds this.
        cache_ratio_threshold: Flag if ``first_run / median(rest)`` exceeds this.
        timeout_s: Per-command timeout passed to the sandbox.
    """

    name = "anti_gaming"

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        visible_test_command: Sequence[str] | None = None,
        heldout_test_command: Sequence[str] | None = None,
        perf_command: Sequence[str] | None = None,
        perf_repeats: int = 4,
        judge_output: str | None = None,
        heldout_gap_threshold: float = 0.25,
        perf_cv_threshold: float = 0.5,
        cache_ratio_threshold: float = 3.0,
        timeout_s: float | None = None,
    ) -> None:
        if perf_repeats < 2:
            raise ValueError("perf_repeats must be >= 2 for a self-consistency check")
        self.sandbox = sandbox
        self.visible_test_command = tuple(visible_test_command) if visible_test_command else None
        self.heldout_test_command = tuple(heldout_test_command) if heldout_test_command else None
        self.perf_command = tuple(perf_command) if perf_command else None
        self.perf_repeats = perf_repeats
        self.judge_output = judge_output
        self.heldout_gap_threshold = heldout_gap_threshold
        self.perf_cv_threshold = perf_cv_threshold
        self.cache_ratio_threshold = cache_ratio_threshold
        self.timeout_s = timeout_s

    def score(self, candidate: Candidate) -> ScoreResult:
        start = time.perf_counter()
        signals: list[Signal] = []
        reasons: list[str] = []
        ran_any = False

        if self.visible_test_command and self.heldout_test_command:
            ran_any = True
            self._check_heldout(candidate, signals, reasons)

        if self.perf_command:
            ran_any = True
            self._check_perf(candidate, signals, reasons)

        judge_output = self.judge_output
        if judge_output is None:
            meta = candidate.metadata.get("judge_output")
            judge_output = meta if isinstance(meta, str) else None
        if judge_output is not None:
            ran_any = True
            self._check_anchor(judge_output, signals, reasons)

        duration = time.perf_counter() - start
        if not ran_any:
            return ScoreResult(
                self.name,
                (),
                False,
                "no integrity checks could run (no inputs provided)",
                duration,
            )

        flagged = bool(reasons)
        signals.append(
            Signal(
                kind=SignalKind.INTEGRITY,
                name="integrity_flagged",
                value=1.0 if flagged else 0.0,
                unit="bool",
                higher_is_better=False,
                raw={"flagged": flagged, "reasons": list(reasons)},
            )
        )
        return ScoreResult(self.name, tuple(signals), True, None, duration)

    # -- checks -------------------------------------------------------------

    def _pass_rate(self, candidate: Candidate, command: tuple[str, ...]) -> float | None:
        result = self.sandbox.run(command, cwd=candidate.path, timeout_s=self.timeout_s)
        if result.timed_out or result.returncode not in (0, 1):
            return None
        counts = parse_pytest_counts(result.stdout + "\n" + result.stderr)
        if counts is None:
            return 1.0 if result.returncode == 0 else 0.0
        return counts.pass_rate

    def _check_heldout(
        self, candidate: Candidate, signals: list[Signal], reasons: list[str]
    ) -> None:
        assert self.visible_test_command and self.heldout_test_command
        visible = self._pass_rate(candidate, self.visible_test_command)
        heldout = self._pass_rate(candidate, self.heldout_test_command)
        if visible is None or heldout is None:
            return  # cannot compare; emit nothing rather than a fabricated gap
        gap = visible - heldout
        if gap > self.heldout_gap_threshold:
            reasons.append(
                f"held-out divergence: visible={visible:.2f} heldout={heldout:.2f} "
                f"gap={gap:.2f} > {self.heldout_gap_threshold:.2f}"
            )
        signals.append(
            Signal(
                kind=SignalKind.INTEGRITY,
                name="integrity_heldout_gap",
                value=gap,
                unit="ratio",
                higher_is_better=False,
                raw={"visible_pass_rate": visible, "heldout_pass_rate": heldout},
            )
        )

    def _check_perf(self, candidate: Candidate, signals: list[Signal], reasons: list[str]) -> None:
        assert self.perf_command
        times: list[float] = []
        for _ in range(self.perf_repeats):
            result = self.sandbox.run(
                self.perf_command, cwd=candidate.path, timeout_s=self.timeout_s
            )
            if not result.ok:
                return  # a failing run makes timing meaningless; skip the check
            times.append(result.duration_s)

        mean = statistics.fmean(times)
        cv = statistics.pstdev(times) / mean if mean > 0 else 0.0
        if cv > self.perf_cv_threshold:
            reasons.append(
                f"perf self-consistency: CV={cv:.2f} > {self.perf_cv_threshold:.2f} "
                f"over {self.perf_repeats} identical runs"
            )
        signals.append(
            Signal(
                kind=SignalKind.INTEGRITY,
                name="integrity_perf_cv",
                value=cv,
                unit="ratio",
                higher_is_better=False,
                raw={"wall_times_s": times, "mean_s": mean},
            )
        )

        rest = times[1:]
        median_rest = statistics.median(rest)
        if median_rest > 0:
            cache_ratio = times[0] / median_rest
            if cache_ratio > self.cache_ratio_threshold:
                reasons.append(
                    f"perf cache anomaly: first_run/median_rest={cache_ratio:.2f} "
                    f"> {self.cache_ratio_threshold:.2f} (possible caching/state leak)"
                )
            signals.append(
                Signal(
                    kind=SignalKind.INTEGRITY,
                    name="integrity_perf_cache_ratio",
                    value=cache_ratio,
                    unit="ratio",
                    higher_is_better=False,
                    raw={"first_s": times[0], "median_rest_s": median_rest},
                )
            )

    def _check_anchor(self, judge_output: str, signals: list[Signal], reasons: list[str]) -> None:
        matches = _SCORE_RE.findall(judge_output)
        n = len(matches)
        if n == 0:
            return  # nothing to anchor; not applicable
        anchor_ok = n == 1
        if not anchor_ok:
            reasons.append(
                f"structured-output anchor: {n} anchored 'SCORE:' lines (possible judge-injection)"
            )
        signals.append(
            Signal(
                kind=SignalKind.INTEGRITY,
                name="integrity_anchor_ok",
                value=1.0 if anchor_ok else 0.0,
                unit="bool",
                higher_is_better=True,
                raw={"anchored_score_lines": n, "values": matches},
            )
        )


def is_flagged(result: ScoreResult) -> bool:
    """Return ``True`` if an anti-gaming ``ScoreResult`` flagged the candidate."""
    signal = result.signal("integrity_flagged")
    return signal is not None and signal.value >= 1.0


__all__ = ["AntiGamingScorer", "is_flagged"]
