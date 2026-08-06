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
from econiq_agents.critic_agent import (
    CoverageReport,
    Independence,
    MostDamagingEvaluator,
    NoRescueEvaluator,
    ProcessCriticAgent,
    TestabilityEvaluator,
    coverage_of,
)
from econiq_agents.critic_stage import CritiqueOutcome, ProcessCritiqueStage
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
    PROCESS_ARCHETYPE_V1,
    PROCESS_DISCOVERY_V1,
    PROCESS_STATE_V1,
    PROCESS_UPDATE_V1,
)
from econiq_agents.scoring import ScorecardWriter, ScoringError
from econiq_agents.state_agents import (
    MeasuredFeatureEvaluator,
    ProcessArchetypeAgent,
    ProcessStateAgent,
    StateTransitionEvaluator,
    TransitionSignificance,
    classify_transition,
)
from econiq_agents.state_persistence import AppliedArchetype, RecordedState, StateWriter
from econiq_agents.state_stage import ProcessStateStage, StateOutcome

__all__ = [
    "CLAIM_EXTRACTION_V1",
    "DOCUMENT_CLASSIFIER_V1",
    "EVENT_RESOLUTION_V1",
    "EVENT_SIGNIFICANCE_V1",
    "PROCESS_ARCHETYPE_V1",
    "PROCESS_DISCOVERY_V1",
    "PROCESS_STATE_V1",
    "PROCESS_UPDATE_V1",
    "AgentRunRecorder",
    "AppliedArchetype",
    "AppliedUpdate",
    "ClaimExtractionAgent",
    "ClaimPersistResult",
    "ClaimWriter",
    "ClusteringMetrics",
    "CoverageReport",
    "CritiqueOutcome",
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
    "Independence",
    "IndependenceAssessment",
    "LayerBoundaryEvaluator",
    "MeasuredFeatureEvaluator",
    "MostDamagingEvaluator",
    "NoRescueEvaluator",
    "PersistedEvent",
    "PersistedProcess",
    "ProcessArchetypeAgent",
    "ProcessCriticAgent",
    "ProcessCritiqueStage",
    "ProcessDiscoveryAgent",
    "ProcessDiscoveryStage",
    "ProcessOutcome",
    "ProcessStateAgent",
    "ProcessStateStage",
    "ProcessUpdateAgent",
    "ProcessWriter",
    "PropagationDecision",
    "PropagationPolicy",
    "QuoteGroundingEvaluator",
    "RecordedState",
    "ResolvedEvent",
    "ResolvedSpan",
    "ScorecardWriter",
    "ScoringError",
    "SourceDocument",
    "StateOutcome",
    "StateTransitionEvaluator",
    "StateWriter",
    "TestabilityEvaluator",
    "TransitionSignificance",
    "WrittenEdge",
    "assess_independence",
    "classify_transition",
    "clusters_from_pairs",
    "cosine_similarity",
    "coverage_of",
    "duplicate_suppression_rate",
    "evaluate_clustering",
    "jaccard",
    "normalize_for_matching",
    "resolve_span",
    "shingles",
]
