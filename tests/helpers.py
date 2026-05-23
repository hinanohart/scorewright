"""Test helpers: a scriptable fake sandbox for deterministic scorer tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from scorewright.sandbox.base import ExecResult

Responder = Callable[[tuple[str, ...], int], ExecResult]


def exec_result(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    duration_s: float = 0.01,
    timed_out: bool = False,
    peak_rss_kb: int | None = 1000,
) -> ExecResult:
    return ExecResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_s=duration_s,
        timed_out=timed_out,
        peak_rss_kb=peak_rss_kb,
    )


class FakeSandbox:
    """A :class:`~scorewright.sandbox.base.Sandbox` whose outputs are scripted.

    ``responder`` receives the command tuple and a 0-based call index and returns
    an :class:`ExecResult`, giving tests full deterministic control over timings
    and test-summary output without spawning real processes.
    """

    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
        env_extra: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> ExecResult:
        idx = len(self.calls)
        self.calls.append(tuple(command))
        return self._responder(tuple(command), idx)
