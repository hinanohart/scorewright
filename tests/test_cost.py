from __future__ import annotations

from pathlib import Path

import pytest

from scorewright import Candidate
from scorewright._pricing import EXAMPLE_PRICING, ModelPrice
from scorewright.scorers import CostScorer


def _candidate(usage: object) -> Candidate:
    return Candidate(path=Path("/tmp"), metadata={"usage": usage})


def test_model_price_math() -> None:
    price = ModelPrice(input_per_mtok=1.0, output_per_mtok=4.0)
    # 1M input @ $1 + 0.5M output @ $4 = 1 + 2 = 3
    assert price.cost_usd(1_000_000, 500_000) == pytest.approx(3.0)


def test_model_price_rejects_negative() -> None:
    with pytest.raises(ValueError):
        ModelPrice(1.0, 1.0).cost_usd(-1, 0)


def test_cost_scorer_computes_usd() -> None:
    scorer = CostScorer(EXAMPLE_PRICING)
    usage = {"model": "demo-large", "input_tokens": 1_000_000, "output_tokens": 0}
    result = scorer.score(_candidate(usage))
    assert result.ok is True
    assert result.signal("cost_usd").value == pytest.approx(1.0)


def test_missing_usage_is_not_ok() -> None:
    scorer = CostScorer(EXAMPLE_PRICING)
    result = scorer.score(Candidate(path=Path("/tmp")))
    assert result.ok is False
    assert result.error is not None


def test_unknown_model_is_not_ok() -> None:
    scorer = CostScorer(EXAMPLE_PRICING)
    usage = {"model": "nope", "input_tokens": 1, "output_tokens": 1}
    result = scorer.score(_candidate(usage))
    assert result.ok is False
    assert "not in pricing table" in (result.error or "")


def test_invalid_token_counts_is_not_ok() -> None:
    scorer = CostScorer(EXAMPLE_PRICING)
    usage = {"model": "demo-small", "input_tokens": "not-a-number", "output_tokens": 1}
    result = scorer.score(_candidate(usage))
    assert result.ok is False
    assert "invalid token counts" in (result.error or "")


def test_non_mapping_usage_is_not_ok() -> None:
    scorer = CostScorer(EXAMPLE_PRICING)
    result = scorer.score(Candidate(path=Path("/tmp"), metadata={"usage": [1, 2, 3]}))
    assert result.ok is False


def test_empty_pricing_table_raises() -> None:
    with pytest.raises(ValueError):
        CostScorer({})
