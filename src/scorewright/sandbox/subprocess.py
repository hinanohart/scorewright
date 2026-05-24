"""Default sandbox backend: fork/exec under resource limits.

``SubprocessSandbox`` runs a command in a child process with:

* ``resource`` rlimits — address space, CPU seconds, open files;
* a wall-clock timeout enforced by killing the child's process group;
* a temporary working directory (an isolated copy of the candidate, by default);
* an environment **allow-list**, so no ambient secrets leak into the child.

It uses ``os.fork`` + ``os.execvpe`` + ``os.wait4`` rather than ``subprocess``
so it can read the child's *own* ``rusage`` (accurate peak RSS per call).

This is best-effort OS-level isolation, not a security boundary against
deliberately malicious code. For untrusted inputs use a VM/container backend
(see the ``microsandbox`` extra) or run scorewright inside a disposable VM.
"""

from __future__ import annotations

import contextlib
import os
import select
import shutil
import signal
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .base import ExecResult

try:
    import resource as _resource
except ImportError:  # pragma: no cover - non-POSIX
    _resource = None  # type: ignore[assignment]

_DEFAULT_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
_READ_CHUNK = 65536


class SubprocessSandbox:
    """Run commands under rlimits, a timeout, fs isolation, and an env allow-list.

    Args:
        cpu_seconds: ``RLIMIT_CPU`` soft limit. ``None`` disables it.
        memory_mb: ``RLIMIT_AS`` (address space) limit in megabytes. ``None``
            disables it. Note this caps virtual address space, which can exceed
            resident memory; very small values may prevent an interpreter from
            starting.
        open_files: ``RLIMIT_NOFILE`` limit. ``None`` disables it.
        timeout_s: Default wall-clock timeout in seconds; overridable per
            ``run`` call. ``None`` means no wall-clock limit (CPU limit still
            applies if set).
        env_allowlist: Names of host environment variables to forward to the
            child. Anything not listed (notably API tokens) is withheld.
        isolate_fs: If ``True`` (default), copy the working directory into a
            fresh temp directory for each run so the candidate cannot mutate the
            original tree. The copy is removed afterwards.
    """

    def __init__(
        self,
        *,
        cpu_seconds: float | None = 10,
        memory_mb: float | None = 512,
        open_files: int | None = 256,
        timeout_s: float | None = 30,
        env_allowlist: Sequence[str] = _DEFAULT_ENV_ALLOWLIST,
        isolate_fs: bool = True,
    ) -> None:
        if sys.platform == "win32":  # pragma: no cover - unsupported platform
            raise RuntimeError(
                "SubprocessSandbox requires a POSIX platform (fork/exec). "
                "On Windows, use a container/VM backend."
            )
        self.cpu_seconds = cpu_seconds
        self.memory_mb = memory_mb
        self.open_files = open_files
        self.timeout_s = timeout_s
        self.env_allowlist = tuple(env_allowlist)
        self.isolate_fs = isolate_fs

    # -- public API ---------------------------------------------------------

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
        env_extra: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> ExecResult:
        if not command:
            raise ValueError("command must be a non-empty sequence")
        timeout = self.timeout_s if timeout_s is None else timeout_s
        env = self._build_env(env_extra)

        workdir, cleanup = self._prepare_workdir(cwd)
        try:
            return self._run_in(list(command), workdir, stdin, env, timeout)
        finally:
            cleanup()

    # -- internals ----------------------------------------------------------

    def _build_env(self, env_extra: Mapping[str, str] | None) -> dict[str, str]:
        env = {k: os.environ[k] for k in self.env_allowlist if k in os.environ}
        env.setdefault("PATH", os.defpath)
        if env_extra:
            env.update(env_extra)
        return env

    def _prepare_workdir(self, cwd: Path | None) -> tuple[Path, Callable[[], None]]:
        if self.isolate_fs:
            tmp = tempfile.mkdtemp(prefix="scorewright-")
            dest = Path(tmp) / "work"
            if cwd is not None:
                shutil.copytree(cwd, dest)
            else:
                dest.mkdir()

            def cleanup() -> None:
                shutil.rmtree(tmp, ignore_errors=True)

            return dest, cleanup

        workdir = cwd if cwd is not None else Path.cwd()
        return workdir, (lambda: None)

    def _apply_limits(self) -> None:  # pragma: no cover - runs in child process
        if _resource is None:
            return
        if self.memory_mb is not None:
            limit = int(self.memory_mb * 1024 * 1024)
            _resource.setrlimit(_resource.RLIMIT_AS, (limit, limit))
        if self.cpu_seconds is not None:
            cpu = int(self.cpu_seconds)
            # Soft limit raises SIGXCPU; the +1s hard limit guarantees a SIGKILL
            # if the child catches or ignores SIGXCPU.
            _resource.setrlimit(_resource.RLIMIT_CPU, (cpu, cpu + 1))
        if self.open_files is not None:
            _resource.setrlimit(_resource.RLIMIT_NOFILE, (self.open_files, self.open_files))

    def _run_in(
        self,
        command: list[str],
        workdir: Path,
        stdin: str | None,
        env: dict[str, str],
        timeout: float | None,
    ) -> ExecResult:
        out_r = out_w = err_r = err_w = in_r = in_w = -1
        pid = -1
        start = time.perf_counter()
        try:
            out_r, out_w = os.pipe()
            err_r, err_w = os.pipe()
            in_r, in_w = os.pipe()

            pid = os.fork()
            if pid == 0:  # pragma: no cover - child process, exits via _exit
                self._child(command, workdir, env, (out_r, out_w, err_r, err_w, in_r, in_w))

            # parent: close the child's ends so reads observe EOF when it exits.
            for fd in (out_w, err_w, in_r):
                os.close(fd)
            out_w = err_w = in_r = -1

            try:
                stdout_b, stderr_b, timed_out = self._pump(pid, out_r, err_r, in_w, stdin, timeout)
            finally:
                for fd in (out_r, err_r, in_w):
                    _close_quiet(fd)
                out_r = err_r = in_w = -1
        except BaseException:
            # os.fork() may have failed (no child) or _pump may have raised after
            # the fork. Bounded, leak-free execution is the whole contract, so
            # never leak a pipe fd and never leave the child running or unreaped.
            for fd in (out_r, out_w, err_r, err_w, in_r, in_w):
                if fd >= 0:
                    _close_quiet(fd)
            if pid > 0:
                self._kill_group(pid)
                with contextlib.suppress(ChildProcessError, OSError):
                    os.waitpid(pid, 0)
            raise

        _pid, status, rusage = os.wait4(pid, 0)
        duration = time.perf_counter() - start
        returncode = -os.WTERMSIG(status) if os.WIFSIGNALED(status) else os.WEXITSTATUS(status)

        return ExecResult(
            returncode=returncode,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            duration_s=duration,
            timed_out=timed_out,
            peak_rss_kb=_maxrss_kb(rusage.ru_maxrss),
        )

    def _child(
        self,
        command: list[str],
        workdir: Path,
        env: dict[str, str],
        fds: tuple[int, int, int, int, int, int],
    ) -> None:  # pragma: no cover - child process
        out_r, out_w, err_r, err_w, in_r, in_w = fds
        try:
            os.setsid()  # own process group so the parent can kill the whole tree
            os.dup2(in_r, 0)
            os.dup2(out_w, 1)
            os.dup2(err_w, 2)
            for fd in (out_r, out_w, err_r, err_w, in_r, in_w):
                _close_quiet(fd)
            os.chdir(workdir)
            self._apply_limits()
            os.execvpe(command[0], command, env)
        except BaseException:
            # exec failed (e.g. command not found): surface a short reason on the
            # child's stderr (fd 2 is already dup2'd to the pipe) before exiting,
            # so the parent doesn't get a silent exit 127.
            with contextlib.suppress(OSError):
                os.write(2, f"scorewright: exec failed for {command[0]!r}\n".encode())
            os._exit(127)

    def _pump(
        self,
        pid: int,
        out_r: int,
        err_r: int,
        in_w: int,
        stdin: str | None,
        timeout: float | None,
    ) -> tuple[bytes, bytes, bool]:
        # Feed stdin (inputs are expected to be small; closed to signal EOF).
        if stdin:
            with contextlib.suppress(OSError):
                os.write(in_w, stdin.encode("utf-8"))
        _close_quiet(in_w)

        chunks: dict[int, list[bytes]] = {out_r: [], err_r: []}
        open_fds = {out_r, err_r}
        deadline = None if timeout is None else time.monotonic() + timeout
        timed_out = False

        while open_fds:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
            else:
                remaining = None
            ready, _, _ = select.select(list(open_fds), [], [], remaining)
            if not ready:
                if deadline is not None and time.monotonic() >= deadline:
                    timed_out = True
                    break
                continue
            for fd in ready:
                data = os.read(fd, _READ_CHUNK)
                if data:
                    chunks[fd].append(data)
                else:
                    open_fds.discard(fd)

        if timed_out:
            self._kill_group(pid)
            self._drain(open_fds, chunks)

        return b"".join(chunks[out_r]), b"".join(chunks[err_r]), timed_out

    @staticmethod
    def _kill_group(pid: int) -> None:
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:  # child already gone
            return
        # Never SIGKILL our *own* process group. If cleanup runs immediately
        # after the fork (e.g. on the exception path) the child may not have
        # called setsid yet, so its pgid is still the parent's — killing that
        # group would take down scorewright itself. Fall back to the child pid.
        if pgid == os.getpgrp():
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            return
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # pragma: no cover
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)

    @staticmethod
    def _drain(open_fds: set[int], chunks: dict[int, list[bytes]], budget_s: float = 2.0) -> None:
        """Read output buffered before the kill, bounded by ``budget_s``.

        A grandchild that escaped the process group (e.g. by calling ``setsid``
        itself) can keep the pipe write-end open after the direct child is
        killed, so an unbounded read here would let it stall the parent forever.
        That OS-level escape is outside the sandbox's isolation guarantee, but
        the parent's wall-clock bound must still hold — hence the time budget.
        """
        if not open_fds:
            return
        remaining = set(open_fds)
        deadline = time.monotonic() + budget_s
        while remaining:
            time_left = deadline - time.monotonic()
            if time_left <= 0:
                break
            ready, _, _ = select.select(list(remaining), [], [], time_left)
            if not ready:
                break
            for fd in ready:
                try:
                    data = os.read(fd, _READ_CHUNK)
                except OSError:
                    remaining.discard(fd)
                    continue
                if data:
                    chunks[fd].append(data)
                else:
                    remaining.discard(fd)


def _close_quiet(fd: int) -> None:
    with contextlib.suppress(OSError):
        os.close(fd)


def _maxrss_kb(ru_maxrss: int) -> int | None:
    if ru_maxrss <= 0:
        return None
    # Linux reports kilobytes; macOS reports bytes.
    if sys.platform == "darwin":
        return ru_maxrss // 1024
    return ru_maxrss


__all__ = ["SubprocessSandbox"]
