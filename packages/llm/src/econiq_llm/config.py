"""LLM configuration.

Model choice per agent tier is a configuration decision, deliberately not a
code one — the open question in the handoff (§6.4, "LLM provider(s) and model
tiering per agent") is answered here and in deployment config, and can be
revisited without touching an agent.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelTier(StrEnum):
    """What an agent's job is worth, in model terms.

    Agents declare a tier rather than a model id, so re-tiering the system is a
    config change and an evaluation question, not a refactor.
    """

    REASONING = "reasoning"
    """Judgement-heavy work: Process discovery, State estimation, critique."""

    STANDARD = "standard"
    """Structured extraction and classification at volume."""

    FAST = "fast"
    """High-volume routing where a wrong answer is cheap to detect."""


class LLMSettings(BaseSettings):
    """Environment-driven LLM configuration (``ECONIQ_LLM_*``)."""

    model_config = SettingsConfigDict(env_prefix="ECONIQ_LLM_", env_file=".env", extra="ignore")

    provider: str = "anthropic"
    anthropic_api_key: str | None = None

    reasoning_model: str = "claude-opus-5"
    standard_model: str = "claude-sonnet-5"
    fast_model: str = "claude-haiku-4-5"

    critic_model: str | None = Field(
        default=None,
        description=(
            "Model for adversarial agents. Point this at a different family from "
            "the reasoning model when one is available: independence is worth "
            "more than re-querying the same model (agent doc §22). Falls back to "
            "the reasoning model."
        ),
    )

    default_effort: str = Field(
        default="high",
        description="Reasoning depth hint. Raise for critique agents, lower for routing.",
    )
    max_tokens: int = Field(default=16_000, ge=256)
    max_attempts: int = Field(
        default=3,
        ge=1,
        description="Total structured-output attempts, including repair retries.",
    )
    request_timeout_s: float = Field(default=600.0, gt=0)

    @property
    def resolved_critic_model(self) -> str:
        return self.critic_model or self.reasoning_model

    def model_for(self, tier: ModelTier) -> str:
        return {
            ModelTier.REASONING: self.reasoning_model,
            ModelTier.STANDARD: self.standard_model,
            ModelTier.FAST: self.fast_model,
        }[tier]
