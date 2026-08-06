"""``LLMService`` — the one place that talks to a model.

Its single non-obvious job is the validation-and-repair loop. Provider-side
schema enforcement is a convenience; the Pydantic model is the contract, and an
object that fails it never reaches the caller. When validation fails the service
shows the model its own output and the exact error and asks for a correction,
which recovers most failures without a wasted full retry — and when it does not,
the call fails loudly rather than returning something half-valid.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from econiq_llm.config import LLMSettings, ModelTier
from econiq_llm.costs import estimate_cost_usd
from econiq_llm.errors import LLMError, OutputValidationError, ProviderRefusalError
from econiq_llm.observability import CallObserver, CallRecord, LoggingObserver
from econiq_llm.providers.base import LLMProvider
from econiq_llm.schema_tools import sanitize_json_schema, schema_is_recursive
from econiq_llm.types import CompletionRequest, Message, Role, TokenUsage

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass(slots=True)
class StructuredCall[TOut: BaseModel]:
    """A validated result plus the full accounting for how it was obtained."""

    value: TOut
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def attempts(self) -> int:
        return len(self.calls)

    @property
    def usage(self) -> TokenUsage:
        total = TokenUsage()
        for call in self.calls:
            total = total + call.usage
        return total

    @property
    def cost_usd(self) -> float | None:
        if any(c.cost_usd is None for c in self.calls):
            return None
        return sum(c.cost_usd or 0.0 for c in self.calls)

    @property
    def model(self) -> str:
        return self.calls[-1].model


class LLMService:
    """Provider-agnostic structured completion."""

    def __init__(
        self,
        provider: LLMProvider,
        settings: LLMSettings | None = None,
        observers: list[CallObserver] | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or LLMSettings()
        self.observers: list[CallObserver] = observers or [LoggingObserver()]

    @classmethod
    def from_settings(cls, settings: LLMSettings | None = None) -> LLMService:
        settings = settings or LLMSettings()
        if settings.provider == "anthropic":
            from econiq_llm.providers.anthropic import AnthropicProvider

            provider: LLMProvider = AnthropicProvider(api_key=settings.anthropic_api_key)
        else:
            raise LLMError(
                f"provider {settings.provider!r} is not implemented; implement "
                f"econiq_llm.providers.base.LLMProvider and register it here"
            )
        return cls(provider, settings)

    def model_for(self, tier: ModelTier) -> str:
        return self.settings.model_for(tier)

    async def structured(
        self,
        *,
        output_model: type[T],
        system: str,
        user_content: str,
        model: str,
        agent_name: str,
        agent_version: str,
        prompt_version: str,
        effort: str | None = None,
        max_attempts: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StructuredCall[T]:
        schema = output_model.model_json_schema()
        recursive = schema_is_recursive(schema)
        # Recursive schemas (the Capability requirement tree, for one) cannot be
        # enforced provider-side. We ask for the shape in the prompt instead and
        # rely entirely on local validation — which is why that loop exists.
        enforced_schema: dict[str, Any] | None = (
            None
            if recursive or not self.provider.supports_structured_output()
            else sanitize_json_schema(schema)
        )
        system_prompt = system if enforced_schema else _with_inline_schema(system, schema)

        messages: list[Message] = [Message(Role.USER, user_content)]
        calls: list[CallRecord] = []
        attempts = max_attempts or self.settings.max_attempts
        last_text = ""

        for attempt in range(1, attempts + 1):
            request = CompletionRequest(
                model=model,
                system=system_prompt,
                messages=tuple(messages),
                json_schema=enforced_schema,
                max_tokens=self.settings.max_tokens,
                effort=effort or self.settings.default_effort,
                metadata=metadata or {},
            )
            try:
                result = await self.provider.complete(request)
            except ProviderRefusalError as exc:
                self._observe(
                    CallRecord(
                        agent_name=agent_name,
                        agent_version=agent_version,
                        prompt_version=prompt_version,
                        provider=self.provider.name,
                        model=model,
                        attempt=attempt,
                        usage=TokenUsage(),
                        latency_ms=0.0,
                        cost_usd=None,
                        ok=False,
                        error=str(exc),
                    ),
                    calls,
                )
                raise

            last_text = result.text
            record = CallRecord(
                agent_name=agent_name,
                agent_version=agent_version,
                prompt_version=prompt_version,
                provider=result.provider,
                model=result.model,
                attempt=attempt,
                usage=result.usage,
                latency_ms=result.latency_ms,
                cost_usd=estimate_cost_usd(result.model, result.usage),
                ok=True,
            )

            try:
                value = output_model.model_validate(_parse_json(result.text))
            except (ValidationError, ValueError) as exc:
                record.ok = False
                record.error = _short(str(exc))
                self._observe(record, calls)
                if attempt == attempts:
                    raise OutputValidationError(
                        f"{agent_name} output failed validation after {attempts} attempts: "
                        f"{_short(str(exc))}",
                        attempts=attempts,
                        last_output=result.text,
                    ) from exc
                messages.append(Message(Role.ASSISTANT, result.text))
                messages.append(Message(Role.USER, _repair_instruction(exc)))
                continue

            self._observe(record, calls)
            return StructuredCall(value=value, calls=calls)

        raise OutputValidationError(  # pragma: no cover - loop always returns or raises
            f"{agent_name} produced no valid output",
            attempts=attempts,
            last_output=last_text,
        )

    def _observe(self, record: CallRecord, calls: list[CallRecord]) -> None:
        calls.append(record)
        for observer in self.observers:
            observer.record(record)


def _parse_json(text: str) -> Any:
    """Parse a JSON object, tolerating code fences and surrounding prose.

    Models occasionally wrap JSON in a fence even when told not to. Recovering
    from that is cheap; failing the whole run over it is not.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("model returned an empty response")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fenced = _FENCE_RE.search(stripped)
    if fenced:
        return json.loads(fenced.group(1).strip())
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        return json.loads(stripped[start : end + 1])
    raise ValueError("model response contained no JSON object")


def _repair_instruction(exc: Exception) -> str:
    return (
        "Your previous response did not satisfy the required schema.\n\n"
        f"Validation error:\n{_short(str(exc), limit=2000)}\n\n"
        "Return a corrected JSON object only. Do not add commentary, do not "
        "invent fields that are not in the schema, and do not change any value "
        "that was already correct."
    )


def _with_inline_schema(system: str, schema: dict[str, Any]) -> str:
    return (
        f"{system}\n\n"
        "Respond with a single JSON object and nothing else. It must validate "
        "against this JSON Schema:\n"
        f"{json.dumps(schema, indent=2, sort_keys=True)}"
    )


def _short(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
