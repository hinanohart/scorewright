"""Sandbox backends for executing candidate programs."""

from __future__ import annotations

from .base import ExecResult, Sandbox
from .subprocess import SubprocessSandbox

__all__ = ["ExecResult", "Sandbox", "SubprocessSandbox"]
