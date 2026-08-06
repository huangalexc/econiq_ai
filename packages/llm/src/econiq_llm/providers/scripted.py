"""A deterministic provider for tests and offline development.

Every agent boundary in this system is a validated schema, which means every
boundary can be tested without a network call (agent doc §14). This provider is
what makes that practical: hand it the responses, assert on the behaviour.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from econiq_llm.errors import ProviderNotAvailableError
from econiq_llm.types import CompletionRequest, CompletionResult, TokenUsage


class ScriptedProvider:
    """Returns queued responses in order.

    ``responses`` may include deliberately malformed JSON to exercise the
    validation-and-repair loop — the case that matters most, since it is the
    boundary that stops a hallucinated field from reaching Postgres.
    """

    name = "scripted"

    def __init__(self, responses: Iterable[str], *, structured: bool = True) -> None:
        self._responses: deque[str] = deque(responses)
        self._structured = structured
        self.requests: list[CompletionRequest] = []

    def supports_structured_output(self) -> bool:
        return self._structured

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if not self._responses:
            raise ProviderNotAvailableError("ScriptedProvider ran out of responses")
        text = self._responses.popleft()
        return CompletionResult(
            text=text,
            model=request.model,
            provider=self.name,
            usage=TokenUsage(input_tokens=len(request.system) // 4, output_tokens=len(text) // 4),
            latency_ms=0.0,
            stop_reason="end_turn",
        )
