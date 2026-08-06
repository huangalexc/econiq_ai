"""Typed failures of the LLM layer.

Each of these means something different to the orchestrator: a refusal should
be recorded as an abstention, a validation failure should be repaired, and a
provider outage should be retried later.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for every failure raised by this package."""


class ProviderNotAvailableError(LLMError):
    """The provider could not be constructed or has nothing left to return."""


class ProviderRefusalError(LLMError):
    """The model declined the request. Retrying the same prompt will not help."""


class OutputValidationError(LLMError):
    """The model's output failed schema validation after every repair attempt.

    Reaching this means no ontology object was created — which is the correct
    outcome. An unvalidated object must never enter the system of record
    (tech rec §33).
    """

    def __init__(self, message: str, *, attempts: int, last_output: str) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_output = last_output


class PromptNotFoundError(LLMError):
    """A prompt version was requested that the registry does not contain."""
