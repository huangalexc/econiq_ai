"""Agent implementations (issues #6 onward).

Agents are ordinary Python classes over ``econiq_llm.Agent``: narrow, typed and
stopping at their ontology layer. Everything they produce carries the agent run
that produced it.
"""

from econiq_agents.document_agents import (
    ClaimExtractionAgent,
    DocumentClassifierAgent,
    QuoteGroundingEvaluator,
    ResolvedSpan,
    normalize_for_matching,
    resolve_span,
)
from econiq_agents.extraction import DocumentExtractionStage, ExtractionOutcome
from econiq_agents.persistence import (
    AgentRunRecorder,
    ClaimPersistResult,
    ClaimWriter,
)
from econiq_agents.prompts import CLAIM_EXTRACTION_V1, DOCUMENT_CLASSIFIER_V1

__all__ = [
    "CLAIM_EXTRACTION_V1",
    "DOCUMENT_CLASSIFIER_V1",
    "AgentRunRecorder",
    "ClaimExtractionAgent",
    "ClaimPersistResult",
    "ClaimWriter",
    "DocumentClassifierAgent",
    "DocumentExtractionStage",
    "ExtractionOutcome",
    "QuoteGroundingEvaluator",
    "ResolvedSpan",
    "normalize_for_matching",
    "resolve_span",
]
