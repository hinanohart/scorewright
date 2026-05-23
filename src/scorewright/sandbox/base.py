"""Sandbox abstraction: a uniform ``run`` interface and its result type."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ExecResult:
    """Outcome of executing a command inside a sandbox.

    Attributes:
        returncode: Process exit code. ``-signal`` on signal-kill (POSIX
            convention); set to ``-9`` style values when the sandbox kills a
            timed-out process group.
        stdout: Captured standard output (decoded, ``errors="replace"``).
        stderr: Captured standard error (decoded, ``errors="replace"``).
        duration_s: Wall-clock seconds the command ran (measured by the host).
        timed_out: ``True`` if the sandbox killed the command for exceeding its
            wall-clock budget.
        peak_rss_kb: Best-effort peak resident set size in kilobytes, or
            ``None`` when the platform cannot report it. On POSIX this comes
            from ``getrusage(RUSAGE_CHILDREN).ru_maxrss`` and reflects the
            largest child reaped so far, so treat it as an upper-bounded
            estimate, not an exact per-call figure.
    """

    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool
    peak_rss_kb: int | None

    @property
    def ok(self) -> bool:
        """``True`` iff the command exited 0 and did not time out."""
        return self.returncode == 0 and not self.timed_out


@runtime_checkable
class Sandbox(Protocol):
    """Executes a command under resource limits and isolation.

    Implementations decide *how* isolation is achieved (subprocess rlimits, a
    microVM, ...). The contract is only that ``run`` never raises for ordinary
    process failure — it reports it through :class:`ExecResult`.
    """

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
        env_extra: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> ExecResult: ...


__all__ = ["ExecResult", "Sandbox"]
