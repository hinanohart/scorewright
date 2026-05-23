"""Token pricing helpers for :class:`~scorewright.scorers.cost.CostScorer`.

scorewright bundles **no authoritative price list**. Prices change often and
vary by provider/region/tier, so :class:`CostScorer` requires you to pass a
pricing mapping explicitly. The :data:`EXAMPLE_PRICING` snapshot below is a
*clearly dated example* for tests and demos only — do not rely on it for real
accounting; pass your own up-to-date table.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD price per 1,000,000 tokens, split by direction.

    Attributes:
        input_per_mtok: USD per 1M input (prompt) tokens.
        output_per_mtok: USD per 1M output (completion) tokens.
    """

    input_per_mtok: float
    output_per_mtok: float

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Return the USD cost for the given token counts."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000


# Example only. Snapshot date below; verify against your provider before use.
EXAMPLE_PRICING_DATE = "2026-05-24"
EXAMPLE_PRICING: dict[str, ModelPrice] = {
    # Illustrative values for tests/demos; NOT an authoritative price list.
    "demo-small": ModelPrice(input_per_mtok=0.10, output_per_mtok=0.40),
    "demo-large": ModelPrice(input_per_mtok=1.00, output_per_mtok=4.00),
}


__all__ = ["EXAMPLE_PRICING", "EXAMPLE_PRICING_DATE", "ModelPrice"]
