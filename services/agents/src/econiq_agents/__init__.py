"""Agent implementations (issues #6 onward).

Agents are ordinary Python classes over ``econiq_llm.Agent``: narrow, typed and
stopping at their ontology layer. Everything they produce carries the agent run
that produced it.
"""

from econiq_agents.clustering_metrics import (
    ClusteringMetrics,
    clusters_from_pairs,
    duplicate_suppression_rate,
    evaluate_clustering,
)
from econiq_agents.document_agents import (
    ClaimExtractionAgent,
    DocumentClassifierAgent,
    QuoteGroundingEvaluator,
    ResolvedSpan,
    normalize_for_matching,
    resolve_span,
)
from econiq_agents.embeddings import (
    Embedder,
    EmbeddingStore,
    HashingEmbedder,
    cosine_similarity,
)
from econiq_agents.event_agents import (
    EventResolutionAgent,
    EventSignificanceAgent,
    PropagationDecision,
    PropagationPolicy,
)
from econiq_agents.event_persistence import EventWriter, PersistedEvent
from econiq_agents.event_stage import (
    EventResolutionOutcome,
    EventResolutionStage,
    ResolvedEvent,
)
from econiq_agents.extraction import DocumentExtractionStage, ExtractionOutcome
from econiq_agents.graph_writer import GraphWriter, IllegalEdgeError, WrittenEdge
from econiq_agents.independence import (
    IndependenceAssessment,
    SourceDocument,
    assess_independence,
    jaccard,
    shingles,
)
from econiq_agents.persistence import (
    AgentRunRecorder,
    ClaimPersistResult,
    ClaimWriter,
)
from econiq_agents.process_agents import (
    LayerBoundaryEvaluator,
    ProcessDiscoveryAgent,
    ProcessUpdateAgent,
)
from econiq_agents.process_persistence import AppliedUpdate, PersistedProcess, ProcessWriter
from econiq_agents.process_stage import ProcessDiscoveryStage, ProcessOutcome
from econiq_agents.prompts import (
    CLAIM_EXTRACTION_V1,
    DOCUMENT_CLASSIFIER_V1,
    EVENT_RESOLUTION_V1,
    EVENT_SIGNIFICANCE_V1,
    PROCESS_DISCOVERY_V1,
    PROCESS_UPDATE_V1,
)

__all__ = [
    "CLAIM_EXTRACTION_V1",
    "DOCUMENT_CLASSIFIER_V1",
    "EVENT_RESOLUTION_V1",
    "EVENT_SIGNIFICANCE_V1",
    "PROCESS_DISCOVERY_V1",
    "PROCESS_UPDATE_V1",
    "AgentRunRecorder",
    "AppliedUpdate",
    "ClaimExtractionAgent",
    "ClaimPersistResult",
    "ClaimWriter",
    "ClusteringMetrics",
    "DocumentClassifierAgent",
    "DocumentExtractionStage",
    "Embedder",
    "EmbeddingStore",
    "EventResolutionAgent",
    "EventResolutionOutcome",
    "EventResolutionStage",
    "EventSignificanceAgent",
    "EventWriter",
    "ExtractionOutcome",
    "GraphWriter",
    "HashingEmbedder",
    "IllegalEdgeError",
    "IndependenceAssessment",
    "LayerBoundaryEvaluator",
    "PersistedEvent",
    "PersistedProcess",
    "ProcessDiscoveryAgent",
    "ProcessDiscoveryStage",
    "ProcessOutcome",
    "ProcessUpdateAgent",
    "ProcessWriter",
    "PropagationDecision",
    "PropagationPolicy",
    "QuoteGroundingEvaluator",
    "ResolvedEvent",
    "ResolvedSpan",
    "SourceDocument",
    "WrittenEdge",
    "assess_independence",
    "clusters_from_pairs",
    "cosine_similarity",
    "duplicate_suppression_rate",
    "evaluate_clustering",
    "jaccard",
    "normalize_for_matching",
    "resolve_span",
    "shingles",
]
