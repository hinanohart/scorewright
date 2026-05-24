from __future__ import annotations

import os
import sys
import time

import pytest

from scorewright.sandbox import SubprocessSandbox

PY = sys.executable


@pytest.fixture
def sandbox() -> SubprocessSandbox:
    return SubprocessSandbox(cpu_seconds=10, memory_mb=None, timeout_s=20)


def test_runs_and_captures_stdout(sandbox: SubprocessSandbox) -> None:
    r = sandbox.run([PY, "-c", "print('hello')"])
    assert r.returncode == 0
    assert r.ok
    assert r.stdout.strip() == "hello"


def test_captures_stderr_and_nonzero_exit(sandbox: SubprocessSandbox) -> None:
    r = sandbox.run([PY, "-c", "import sys; sys.stderr.write('oops'); sys.exit(3)"])
    assert r.returncode == 3
    assert not r.ok
    assert "oops" in r.stderr


def test_timeout_kills_process(sandbox: SubprocessSandbox) -> None:
    r = sandbox.run([PY, "-c", "import time; time.sleep(10)"], timeout_s=0.4)
    assert r.timed_out is True
    assert r.returncode < 0  # killed by signal


def test_memory_limit_rejects_large_allocation() -> None:
    sb = SubprocessSandbox(memory_mb=256, timeout_s=20)
    r = sb.run([PY, "-c", "x = bytearray(2_000_000_000); print(len(x))"])
    assert r.returncode != 0  # allocation fails under the address-space limit


def test_env_allowlist_excludes_unlisted_vars(
    sandbox: SubprocessSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Put a secret in the *host* environment; the allow-list must filter it out.
    monkeypatch.setenv("SECRET_TOKEN", "super-secret-value")
    code = "import os; print(os.environ.get('SECRET_TOKEN', 'ABSENT'))"
    r = sandbox.run([PY, "-c", code], env_extra=None)
    assert r.stdout.strip() == "ABSENT"


def test_env_extra_is_passed(sandbox: SubprocessSandbox) -> None:
    code = "import os; print(os.environ.get('MY_FLAG', 'MISSING'))"
    r = sandbox.run([PY, "-c", code], env_extra={"MY_FLAG": "on"})
    assert r.stdout.strip() == "on"


def test_fs_isolation_protects_original_dir(tmp_path) -> None:
    sb = SubprocessSandbox(memory_mb=None, isolate_fs=True, timeout_s=20)
    (tmp_path / "seed.txt").write_text("seed")
    r = sb.run([PY, "-c", "open('written_by_candidate.txt','w').write('x')"], cwd=tmp_path)
    assert r.returncode == 0
    # The candidate wrote into an isolated copy; the original dir is untouched.
    assert not (tmp_path / "written_by_candidate.txt").exists()
    assert (tmp_path / "seed.txt").exists()


def test_peak_rss_is_measured_or_none(sandbox: SubprocessSandbox) -> None:
    r = sandbox.run([PY, "-c", "x=[0]*100000; print(len(x))"])
    assert r.peak_rss_kb is None or r.peak_rss_kb > 0


def test_empty_command_raises(sandbox: SubprocessSandbox) -> None:
    with pytest.raises(ValueError):
        sandbox.run([])


# -- robustness / exception safety -----------------------------------------


def test_child_is_reaped_when_pump_raises(
    sandbox: SubprocessSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If output pumping raises after the fork, the child must still be killed
    # and reaped — never left as an orphan/zombie holding resource limits.
    killed: dict[str, int] = {}
    real_kill = SubprocessSandbox._kill_group

    def spy_kill(pid: int) -> None:
        killed["pid"] = pid
        real_kill(pid)

    monkeypatch.setattr(SubprocessSandbox, "_kill_group", staticmethod(spy_kill))

    def boom(*_args: object, **_kwargs: object) -> tuple[bytes, bytes, bool]:
        raise RuntimeError("pump failed")

    monkeypatch.setattr(SubprocessSandbox, "_pump", boom)

    with pytest.raises(RuntimeError, match="pump failed"):
        sandbox.run([PY, "-c", "import time; time.sleep(30)"])

    # The child was reaped by the cleanup path, so waitpid must now report that
    # there is no such child left to wait for.
    assert "pid" in killed
    with pytest.raises(ChildProcessError):
        os.waitpid(killed["pid"], 0)


def test_does_not_hang_when_grandchild_escapes_process_group() -> None:
    # A grandchild that calls setsid escapes killpg and keeps the inherited
    # stdout pipe open. The parent must still return on a bounded budget rather
    # than block until that grandchild exits (here, 30s).
    sb = SubprocessSandbox(memory_mb=None, cpu_seconds=30, timeout_s=0.4)
    code = (
        "import os, time\n"
        "if os.fork() == 0:\n"
        "    os.setsid()\n"  # escape the parent's process group
        "    time.sleep(30)\n"  # keep the inherited write-end open
        "    os._exit(0)\n"
        "time.sleep(30)\n"  # direct child also runs past the timeout
    )
    start = time.monotonic()
    r = sb.run([PY, "-c", code])
    elapsed = time.monotonic() - start
    assert r.timed_out is True
    assert elapsed < 6.0  # timeout(0.4) + drain budget(2) + slack, not ~30s


@pytest.mark.skipif(
    not os.path.isdir(f"/proc/{os.getpid()}/fd"), reason="needs /proc fd introspection"
)
def test_no_fd_leak_when_fork_fails(
    sandbox: SubprocessSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    fd_dir = f"/proc/{os.getpid()}/fd"

    def boom_fork() -> int:
        raise OSError("EAGAIN: cannot fork")

    before = len(os.listdir(fd_dir))
    monkeypatch.setattr(os, "fork", boom_fork)
    with pytest.raises(OSError, match="cannot fork"):
        sandbox.run([PY, "-c", "print(1)"])
    monkeypatch.undo()
    # The six pipe fds opened before the (failed) fork were all cleaned up.
    assert len(os.listdir(fd_dir)) == before


def test_missing_command_reports_exec_failure(sandbox: SubprocessSandbox) -> None:
    r = sandbox.run(["scorewright-no-such-binary-xyz"])
    assert r.returncode == 127
    assert "exec failed" in r.stderr
