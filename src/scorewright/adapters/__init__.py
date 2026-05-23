"""Adapters converting scorewright's IR into host-framework shapes."""

from __future__ import annotations

from .openevolve import to_openevolve_evaluator

__all__ = ["to_openevolve_evaluator"]
