"""Adapter: scorewright IR -> an OpenEvolve evaluation callable.

OpenEvolve drives evolution with an evaluation function of the shape
``evaluate(program_path: str) -> dict[str, float]``. When the returned metrics
contain ``"combined_score"`` OpenEvolve optimizes that; otherwise it averages
the numeric metrics. This adapter builds such a callable from a scorewright
scorer, doing a **pure IR -> native** conversion: it flattens measured signals
into the metrics dict and (optionally) computes ``combined_score`` from an
explicit ``aggregate`` function. Aggregation lives here, in the adapter — never
inside the scorers.

The fail-closed integrity policy is opt-in here, at the judgment layer: with
``reject_on_gaming=True`` a candidate that the :class:`AntiGamingScorer` flags
gets ``combined_score = reject_score`` so the search drops it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from ..scorer import CompositeScorer, Scorer, collect_values
from ..scorers.anti_gaming import is_flagged
from ..types import Candidate, ScoreResult

Aggregate = Callable[[Mapping[str, float]], float]
MetadataFactory = Callable[[str], Mapping[str, object]]


def _build_candidate(program_path: str, metadata_factory: MetadataFactory | None) -> Candidate:
    path = Path(program_path)
    metadata = dict(metadata_factory(program_path)) if metadata_factory else {}
    if path.is_file():
        return Candidate(path=path.parent, entrypoint=path.name, metadata=metadata)
    return Candidate(path=path, metadata=metadata)


def _run(scorer: Scorer | CompositeScorer, candidate: Candidate) -> tuple[ScoreResult, ...]:
    if isinstance(scorer, CompositeScorer):
        return scorer.score_all(candidate)
    return (scorer.score(candidate),)


def to_openevolve_evaluator(
    scorer: Scorer | CompositeScorer,
    *,
    aggregate: Aggregate | None = None,
    reject_on_gaming: bool = False,
    reject_score: float = 0.0,
    metadata_factory: MetadataFactory | None = None,
) -> Callable[[str], dict[str, float]]:
    """Return an OpenEvolve-compatible ``evaluate(program_path) -> dict``.

    Args:
        scorer: A single :class:`~scorewright.scorer.Scorer` or a
            :class:`~scorewright.scorer.CompositeScorer`.
        aggregate: Optional function mapping the metrics dict to a single
            ``combined_score``. If omitted, no ``combined_score`` is injected and
            OpenEvolve averages the metrics itself.
        reject_on_gaming: If ``True``, a flagged candidate (per the anti-gaming
            scorer's ``integrity_flagged`` signal) is forced to ``reject_score``.
        reject_score: The ``combined_score`` assigned to rejected candidates.
        metadata_factory: Optional function producing per-candidate metadata
            (e.g. token usage) keyed off the program path.

    Notes:
        Only signals from ``ok`` results contribute metrics; a failed scorer
        contributes nothing rather than a fabricated value. The boolean
        ``integrity_flagged`` signal is included in the metrics so it is visible
        even when ``reject_on_gaming`` is off (warn-only).
    """

    def evaluate(program_path: str) -> dict[str, float]:
        candidate = _build_candidate(program_path, metadata_factory)
        results = _run(scorer, candidate)
        metrics = collect_values(results)

        gamed = reject_on_gaming and any(is_flagged(r) for r in results)
        if gamed:
            metrics["combined_score"] = reject_score
        elif aggregate is not None:
            metrics["combined_score"] = float(aggregate(metrics))
        return metrics

    return evaluate


__all__ = ["Aggregate", "MetadataFactory", "to_openevolve_evaluator"]
