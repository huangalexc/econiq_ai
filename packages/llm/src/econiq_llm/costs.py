"""Token cost accounting.

Cost per agent run is a first-class metric, not an afterthought: the phase plan
budgets LLM spend per Process update, and the evaluation harness (issue #16)
compares models on quality *and* cost. Prices are USD per million tokens and
must be kept in step with the provider's published pricing.
"""

from __future__ import annotations

from dataclasses import dataclass

from econiq_llm.types import TokenUsage


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """USD per million tokens."""

    input_per_mtok: float
    output_per_mtok: float
    cache_read_multiplier: float = 0.1
    cache_write_multiplier: float = 1.25


#: Verified against Anthropic's published pricing on 2026-08-06.
PRICING: dict[str, ModelPricing] = {
    "claude-opus-5": ModelPricing(5.00, 25.00),
    "claude-sonnet-5": ModelPricing(3.00, 15.00),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00),
}


def estimate_cost_usd(model: str, usage: TokenUsage) -> float | None:
    """Cost of one call, or ``None`` for a model with no pricing entry.

    ``None`` rather than zero: an unknown price must not be recorded as free.
    """
    pricing = PRICING.get(model) or PRICING.get(_strip_snapshot(model))
    if pricing is None:
        return None
    million = 1_000_000
    return (
        usage.input_tokens * pricing.input_per_mtok
        + usage.output_tokens * pricing.output_per_mtok
        + usage.cache_read_input_tokens * pricing.input_per_mtok * pricing.cache_read_multiplier
        + usage.cache_creation_input_tokens
        * pricing.input_per_mtok
        * pricing.cache_write_multiplier
    ) / million


def _strip_snapshot(model: str) -> str:
    """``claude-haiku-4-5-20251001`` -> ``claude-haiku-4-5``."""
    parts = model.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
        return parts[0]
    return model
