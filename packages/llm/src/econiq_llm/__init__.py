"""LLM provider abstraction, agent runtime and prompt versioning.

The architectural rule this package exists to protect: **the LLM is never the
source of truth** (tech rec §33). Models formulate and interpret; Postgres holds
the ontology; deterministic code computes every number. Everything here is
built so that an unvalidated model output cannot become an ontology object.
"""

from econiq_llm.agent import (
    Agent,
    AgentRunResult,
    CitationEvaluator,
    EvaluationCheck,
    EvaluationReport,
    Evaluator,
)
from econiq_llm.config import LLMSettings, ModelTier
from econiq_llm.costs import PRICING, ModelPricing, estimate_cost_usd
from econiq_llm.errors import (
    LLMError,
    OutputValidationError,
    PromptNotFoundError,
    ProviderNotAvailableError,
    ProviderRefusalError,
)
from econiq_llm.observability import (
    CallObserver,
    CallRecord,
    CollectingObserver,
    LoggingObserver,
)
from econiq_llm.prompts import (
    PROMPTS,
    SHARED_AGENT_PREAMBLE,
    PromptRegistry,
    PromptTemplate,
)
from econiq_llm.providers import AnthropicProvider, LLMProvider, ScriptedProvider
from econiq_llm.schema_tools import sanitize_json_schema, schema_is_recursive
from econiq_llm.service import LLMService, StructuredCall
from econiq_llm.types import (
    CompletionRequest,
    CompletionResult,
    Message,
    Role,
    TokenUsage,
)

__all__ = [
    "PRICING",
    "PROMPTS",
    "SHARED_AGENT_PREAMBLE",
    "Agent",
    "AgentRunResult",
    "AnthropicProvider",
    "CallObserver",
    "CallRecord",
    "CitationEvaluator",
    "CollectingObserver",
    "CompletionRequest",
    "CompletionResult",
    "EvaluationCheck",
    "EvaluationReport",
    "Evaluator",
    "LLMError",
    "LLMProvider",
    "LLMService",
    "LLMSettings",
    "LoggingObserver",
    "Message",
    "ModelPricing",
    "ModelTier",
    "OutputValidationError",
    "PromptNotFoundError",
    "PromptRegistry",
    "PromptTemplate",
    "ProviderNotAvailableError",
    "ProviderRefusalError",
    "Role",
    "ScriptedProvider",
    "StructuredCall",
    "TokenUsage",
    "estimate_cost_usd",
    "sanitize_json_schema",
    "schema_is_recursive",
]
