"""Optional VM-isolated sandbox backend (interface stub).

In v0.1.0a1 this is an **import-guarded interface stub**: it conforms to the
:class:`~scorewright.sandbox.base.Sandbox` protocol's shape but does not yet
execute commands. The full backend (libkrun microVM via the ``microsandbox``
package) is planned for v0.2. Construction fails fast if the optional
dependency is missing, and ``run`` raises ``NotImplementedError`` so no caller
can mistake the stub for a working sandbox.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from pathlib import Path

from .base import ExecResult

_HAVE_MICROSANDBOX = importlib.util.find_spec("microsandbox") is not None


class MicrosandboxSandbox:
    """Placeholder for the libkrun-backed microVM sandbox (v0.2)."""

    def __init__(self, **_kwargs: object) -> None:
        if not _HAVE_MICROSANDBOX:
            raise RuntimeError(
                "MicrosandboxSandbox requires the optional 'microsandbox' "
                "dependency: pip install 'scorewright[microsandbox]'"
            )
        raise NotImplementedError(
            "MicrosandboxSandbox is an interface stub in v0.1.0a1; the libkrun "
            "microVM backend is planned for v0.2. Use SubprocessSandbox today."
        )

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
        env_extra: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> ExecResult:  # pragma: no cover - unreachable; __init__ always raises
        raise NotImplementedError


__all__ = ["MicrosandboxSandbox"]
