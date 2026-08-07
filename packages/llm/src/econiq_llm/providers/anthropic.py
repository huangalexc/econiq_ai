"""Anthropic provider.

The only provider implemented in Phase 0. Others (OpenAI, Google, local) plug
in behind ``LLMProvider`` without touching anything above this module — see
``econiq_llm.providers.registry``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from econiq_llm.errors import ProviderNotAvailableError, ProviderRefusalError
from econiq_llm.types import CompletionRequest, CompletionResult, TokenUsage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from anthropic import AsyncAnthropic


class AnthropicProvider:
    """Structured-output completions against the Anthropic Messages API.

    Two behaviours are deliberate:

    * **Adaptive thinking is left on** (the default on current models) and
      reasoning depth is steered with ``effort``, not a token budget.
    * **A refusal is an outcome, not an exception to swallow.** The API returns
      HTTP 200 with ``stop_reason == "refusal"``; we surface it as a typed error
      so the orchestrator can record an abstention rather than retrying a prompt
      that will be declined again.
    """

    name = "anthropic"

    def __init__(self, client: AsyncAnthropic | None = None, api_key: str | None = None) -> None:
        self._client = client or self._build_client(api_key)

    @staticmethod
    def _build_client(api_key: str | None) -> AsyncAnthropic:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise ProviderNotAvailableError(
                "the 'anthropic' extra is required: uv sync --extra anthropic"
            ) from exc
        # A bare constructor resolves ANTHROPIC_API_KEY or an `ant auth login`
        # profile; only pass a key when one was configured explicitly.
        return AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()

    def supports_structured_output(self) -> bool:
        return True

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        output_config: dict[str, Any] = {}
        if request.json_schema is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": request.json_schema,
            }
        if request.effort is not None:
            output_config["effort"] = request.effort

        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
        }
        if output_config:
            kwargs["output_config"] = output_config

        started = time.perf_counter()
        response = await self._client.messages.create(**kwargs)
        latency_ms = (time.perf_counter() - started) * 1000

        if response.stop_reason == "refusal":
            raise ProviderRefusalError(
                f"model declined the request (category="
                f"{getattr(response.stop_details, 'category', None)})"
            )

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        usage = response.usage
        return CompletionResult(
            text=text,
            model=response.model,
            provider=self.name,
            usage=TokenUsage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            ),
            latency_ms=latency_ms,
            stop_reason=response.stop_reason,
            raw_response_id=response.id,
        )
