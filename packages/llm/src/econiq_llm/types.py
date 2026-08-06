"""Provider-neutral request/response types.

Nothing above this layer knows which provider served a call. That is the point
of the abstraction (tech rec §14): model choice becomes a configuration
decision and a cost/quality experiment, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from econiq_ontology.base import utcnow


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """One structured-output call.

    ``json_schema`` is the *sanitized* schema of the expected output. The caller
    always validates the result against the Pydantic model regardless of what
    the provider claims to guarantee — provider-side enforcement is a
    convenience, never the check that matters.
    """

    model: str
    system: str
    messages: tuple[Message, ...]
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 16_000
    effort: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
        )


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """Raw text plus everything needed to account for the call."""

    text: str
    model: str
    provider: str
    usage: TokenUsage
    latency_ms: float
    stop_reason: str | None = None
    raw_response_id: str | None = None
    completed_at: datetime = field(default_factory=utcnow)
