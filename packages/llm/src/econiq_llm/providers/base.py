"""The provider seam.

Adding a provider means implementing this protocol and registering it. Nothing
else in the codebase changes — that is the whole requirement of tech rec §14:
no provider-specific calls scattered through the system.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from econiq_llm.types import CompletionRequest, CompletionResult


@runtime_checkable
class LLMProvider(Protocol):
    """A minimal, single-shot text completion with optional schema enforcement."""

    name: str

    def supports_structured_output(self) -> bool:
        """Whether the provider can enforce a JSON schema server-side.

        A ``False`` here is not a blocker: the agent runtime validates and
        repairs regardless, because provider enforcement is a convenience and
        Pydantic is the contract.
        """
        ...

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...
