"""Call-level telemetry.

Token, cost and latency tracking are hooks rather than a hard dependency on a
tracing vendor: Langfuse or Phoenix (tech rec §26) attaches later by
implementing ``CallObserver``, and the agent-run log (issue #16) attaches by
implementing the same protocol.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from econiq_ontology.base import utcnow

from econiq_llm.types import TokenUsage

logger = logging.getLogger("econiq.llm")


@dataclass(slots=True)
class CallRecord:
    """One provider call, successful or not.

    ``attempt`` distinguishes the first try from repair retries, which is how
    the eval harness measures how often a model fails its own schema — a direct
    quality signal when comparing models.
    """

    agent_name: str
    agent_version: str
    prompt_version: str
    provider: str
    model: str
    attempt: int
    usage: TokenUsage
    latency_ms: float
    cost_usd: float | None
    ok: bool
    error: str | None = None
    started_at: datetime = field(default_factory=utcnow)


class CallObserver(Protocol):
    def record(self, call: CallRecord) -> None: ...


class LoggingObserver:
    """Default observer: structured log lines, no external dependency."""

    def record(self, call: CallRecord) -> None:
        logger.info(
            "llm_call agent=%s@%s prompt=%s model=%s attempt=%d ok=%s "
            "in=%d out=%d latency_ms=%.0f cost_usd=%s%s",
            call.agent_name,
            call.agent_version,
            call.prompt_version,
            call.model,
            call.attempt,
            call.ok,
            call.usage.input_tokens,
            call.usage.output_tokens,
            call.latency_ms,
            "unknown" if call.cost_usd is None else f"{call.cost_usd:.6f}",
            f" error={call.error}" if call.error else "",
        )


class CollectingObserver:
    """Keeps records in memory. Used by tests and the eval harness."""

    def __init__(self) -> None:
        self.calls: list[CallRecord] = []

    def record(self, call: CallRecord) -> None:
        self.calls.append(call)

    @property
    def total_usage(self) -> TokenUsage:
        total = TokenUsage()
        for call in self.calls:
            total = total + call.usage
        return total

    @property
    def total_cost_usd(self) -> float | None:
        """``None`` if any call had unknown pricing — a partial total would
        understate spend, which is worse than admitting the gap."""
        if any(call.cost_usd is None for call in self.calls):
            return None
        return sum(call.cost_usd or 0.0 for call in self.calls)
