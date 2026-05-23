"""scorewright — sandboxed, multi-signal, cross-framework fitness scoring.

See the README for an overview. The core public surface:

* IR — :class:`Candidate`, :class:`Signal`, :class:`ScoreResult`, :class:`SignalKind`
* orchestration — :class:`Scorer`, :class:`CompositeScorer`
* scorers — under :mod:`scorewright.scorers`
* sandboxes — under :mod:`scorewright.sandbox`
* adapters — under :mod:`scorewright.adapters`
"""

from __future__ import annotations

from .scorer import CompositeScorer, Scorer, collect_values
from .types import Candidate, ScoreResult, Signal, SignalKind

__version__ = "0.1.0a1"

__all__ = [
    "Candidate",
    "CompositeScorer",
    "ScoreResult",
    "Scorer",
    "Signal",
    "SignalKind",
    "__version__",
    "collect_values",
]
