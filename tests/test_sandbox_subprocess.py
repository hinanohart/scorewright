from __future__ import annotations

import sys

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
