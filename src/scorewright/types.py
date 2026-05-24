"""Intermediate representation (IR) for scorewright.

The IR is deliberately small and immutable. Scorers *measure* and emit
:class:`Signal` values carrying a unit and a direction (``higher_is_better``).
They never normalize, weight, or aggregate — that is the job of an adapter or
the calling loop. This keeps measurement auditable and separate from judgment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SignalKind(str, Enum):
    """Coarse category a :class:`Signal` belongs to."""

    CORRECTNESS = "correctness"
    PERFORMANCE = "performance"
    COST = "cost"
    QUALITY = "quality"
    INTEGRITY = "integrity"


@dataclass(frozen=True, slots=True)
class Signal:
    """A single measured quantity.

    Attributes:
        kind: Coarse category (see :class:`SignalKind`).
        name: Stable identifier, e.g. ``"perf_wall_time_s"``. Used as the metric
            key by adapters, so it should be unique within a scorer's output.
        value: The measured value. Always a real measurement; scorers must not
            fabricate a value when they cannot measure (they return
            ``ScoreResult(ok=False)`` instead).
        unit: Human/machine readable unit, e.g. ``"s"``, ``"USD"``, ``"ratio"``.
        higher_is_better: Direction of preference. ``True`` for pass-rate,
            ``False`` for wall-time/cost. Aggregators use this to know which way
            to optimize; scorewright itself never flips it.
        raw: Optional audit payload (full command output, per-run timings, ...).
            Never consumed by aggregation; preserved for inspection only.
    """

    kind: SignalKind
    name: str
    value: float
    unit: str
    higher_is_better: bool
    raw: Any = None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """The result of running one scorer against one candidate.

    Contract:
        * ``ok is True``  -> ``signals`` holds one or more measured signals and
          ``error is None``.
        * ``ok is False`` -> the scorer could not produce a trustworthy
          measurement (execution failure, missing API key, missing pricing,
          ...); ``signals`` is empty and ``error`` explains why. A failed result
          never carries a fabricated value.
    """

    scorer: str
    signals: tuple[Signal, ...]
    ok: bool
    error: str | None = None
    duration_s: float = 0.0

    def signal(self, name: str) -> Signal | None:
        """Return the signal with ``name`` if present, else ``None``."""
        for s in self.signals:
            if s.name == name:
                return s
        return None

    def values(self) -> dict[str, float]:
        """Return a ``{signal_name: value}`` mapping for the measured signals."""
        return {s.name: s.value for s in self.signals}


def _is_safe_entrypoint(entrypoint: str) -> bool:
    """Return ``True`` iff ``entrypoint`` is a single safe relative filename.

    Safe means exactly one path component that is not ``.`` or ``..`` and not
    absolute, so joining it onto a candidate's ``path`` can never escape that
    directory.
    """
    parts = Path(entrypoint).parts
    return (
        len(parts) == 1 and parts[0] not in ("", ".", "..") and not Path(entrypoint).is_absolute()
    )


@dataclass(frozen=True, slots=True)
class Candidate:
    """A program to be scored.

    Attributes:
        path: Working directory containing the candidate program. Scorers that
            execute code do so within (an isolated copy of) this directory.
        entrypoint: Optional default entrypoint (e.g. ``"solution.py"``).
            Scorers may use it to build a command when none is given explicitly.
            Must be a single safe relative filename inside ``path`` — no path
            separators, no ``..`` components, and not absolute — so an
            attacker-controlled candidate cannot make a scorer read files outside
            its working directory.
        metadata: Free-form, read-only metadata. Conventionally carries token
            usage for :class:`~scorewright.scorers.cost.CostScorer` under
            ``metadata["usage"] = {"model": str, "input_tokens": int,
            "output_tokens": int}`` and any judge output for the anti-gaming
            structured-output anchor.

    Raises:
        ValueError: If ``entrypoint`` is not a safe relative filename.
    """

    path: Path
    entrypoint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entrypoint is not None and not _is_safe_entrypoint(self.entrypoint):
            # Reject anything that is not a bare filename: path separators,
            # parent references (``..``), and absolute paths all fail this check,
            # which blocks traversal out of ``path`` (e.g. ``"../../etc/passwd"``).
            raise ValueError(
                f"entrypoint must be a safe relative filename inside the candidate "
                f"directory (no path separators or '..'), got {self.entrypoint!r}"
            )


__all__ = ["Candidate", "ScoreResult", "Signal", "SignalKind"]
