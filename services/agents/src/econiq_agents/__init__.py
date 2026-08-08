"""Agent implementations (issues #6 onward).

Agents are ordinary Python classes over ``econiq_llm.Agent``: narrow, typed and
stopping at their ontology layer. Everything they produce carries the agent run
that produced it.
"""

from econiq_agents.asset_agents import (
    AssetDiscoveryAgent,
    AssetExposureAgent,
    InstrumentBreadthEvaluator,
    NoRankingEvaluator,
    QuantitativeBasisEvaluator,
    material_candidates,
)
from econiq_agents.asset_persistence import (
    AssetResolution,
    AssetWriter,
    ExposureWriter,
    PersistedExposures,
    ResolvedAsset,
    resolution_rate,
)
from econiq_agents.asset_stage import AssetDiscoveryStage, AssetOutcome
from econiq_agents.capability_agents import (
    BindingClarityEvaluator,
    BottleneckIdentificationAgent,
    CapabilityConfluenceAgent,
    CapabilityMappingAgent,
    ConfluenceScopeEvaluator,
    RequirementStructureEvaluator,
    independent_support,
)
from econiq_agents.capability_persistence import (
    BottleneckWriter,
    CapabilityWriter,
    PersistedBottleneck,
    PersistedRequirement,
    ResolvedCapability,
    requirement_summary,
    slugify,
)
from econiq_agents.capability_stage import (
    CapabilityOutcome,
    CapabilityStage,
    ConfluenceResult,
)
from econiq_agents.clustering_metrics import (
    ClusteringMetrics,
    clusters_from_pairs,
    duplicate_suppression_rate,
    evaluate_clustering,
)
from econiq_agents.counterfactual_agent import (
    CounterfactualAgent,
    DiversityEvaluator,
    FalsifiabilityEvaluator,
    PlausibilityEvaluator,
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
from econiq_agents.dependence import (
    Dependence,
    EvidenceItem,
    effective_sources,
    structural_dependencies,
    undecided_pairs,
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
from econiq_agents.independence_agent import EvidenceIndependenceAgent
from econiq_agents.independence_stage import IndependenceOutcome, IndependenceStage
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
    ASSET_DISCOVERY_V1,
    ASSET_EXPOSURE_V1,
    BOTTLENECK_IDENTIFICATION_V1,
    CAPABILITY_CONFLUENCE_V1,
    CAPABILITY_MAPPING_V1,
    CLAIM_EXTRACTION_V1,
    DOCUMENT_CLASSIFIER_V1,
    EVENT_RESOLUTION_V1,
    EVENT_SIGNIFICANCE_V1,
    PROCESS_ARCHETYPE_V1,
    PROCESS_DISCOVERY_V1,
    PROCESS_STATE_V1,
    PROCESS_UPDATE_V1,
)
from econiq_agents.reference_universe import (
    COMMODITIES,
    CURRENCIES,
    REFERENCE_UNIVERSE,
    ReferenceInstrument,
    lookup,
    resolvable_names,
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
from econiq_agents.thesis_scorer import (
    COMPUTED_AXES,
    JUDGED_AXES,
    UNAVAILABLE_AXES,
    ThesisScoringAgent,
)
from econiq_agents.thesis_stage import ThesisOutcome, ThesisStage

__all__ = [
    "ASSET_DISCOVERY_V1",
    "ASSET_EXPOSURE_V1",
    "BOTTLENECK_IDENTIFICATION_V1",
    "CAPABILITY_CONFLUENCE_V1",
    "CAPABILITY_MAPPING_V1",
    "CLAIM_EXTRACTION_V1",
    "COMMODITIES",
    "COMPUTED_AXES",
    "CURRENCIES",
    "DOCUMENT_CLASSIFIER_V1",
    "EVENT_RESOLUTION_V1",
    "EVENT_SIGNIFICANCE_V1",
    "JUDGED_AXES",
    "PROCESS_ARCHETYPE_V1",
    "PROCESS_DISCOVERY_V1",
    "PROCESS_STATE_V1",
    "PROCESS_UPDATE_V1",
    "REFERENCE_UNIVERSE",
    "UNAVAILABLE_AXES",
    "AgentRunRecorder",
    "AppliedArchetype",
    "AppliedUpdate",
    "AssetDiscoveryAgent",
    "AssetDiscoveryStage",
    "AssetExposureAgent",
    "AssetOutcome",
    "AssetResolution",
    "AssetWriter",
    "BindingClarityEvaluator",
    "BottleneckIdentificationAgent",
    "BottleneckWriter",
    "CapabilityConfluenceAgent",
    "CapabilityMappingAgent",
    "CapabilityOutcome",
    "CapabilityStage",
    "CapabilityWriter",
    "ClaimExtractionAgent",
    "ClaimPersistResult",
    "ClaimWriter",
    "ClusteringMetrics",
    "ConfluenceResult",
    "ConfluenceScopeEvaluator",
    "CounterfactualAgent",
    "CoverageReport",
    "CritiqueOutcome",
    "Dependence",
    "DiversityEvaluator",
    "DocumentClassifierAgent",
    "DocumentExtractionStage",
    "Embedder",
    "EmbeddingStore",
    "EventResolutionAgent",
    "EventResolutionOutcome",
    "EventResolutionStage",
    "EventSignificanceAgent",
    "EventWriter",
    "EvidenceIndependenceAgent",
    "EvidenceItem",
    "ExposureWriter",
    "ExtractionOutcome",
    "FalsifiabilityEvaluator",
    "GraphWriter",
    "HashingEmbedder",
    "IllegalEdgeError",
    "Independence",
    "IndependenceAssessment",
    "IndependenceOutcome",
    "IndependenceStage",
    "InstrumentBreadthEvaluator",
    "LayerBoundaryEvaluator",
    "MeasuredFeatureEvaluator",
    "MostDamagingEvaluator",
    "NoRankingEvaluator",
    "NoRescueEvaluator",
    "PersistedBottleneck",
    "PersistedEvent",
    "PersistedExposures",
    "PersistedProcess",
    "PersistedRequirement",
    "PlausibilityEvaluator",
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
    "QuantitativeBasisEvaluator",
    "QuoteGroundingEvaluator",
    "RecordedState",
    "ReferenceInstrument",
    "RequirementStructureEvaluator",
    "ResolvedAsset",
    "ResolvedCapability",
    "ResolvedEvent",
    "ResolvedSpan",
    "ScorecardWriter",
    "ScoringError",
    "SourceDocument",
    "StateOutcome",
    "StateTransitionEvaluator",
    "StateWriter",
    "TestabilityEvaluator",
    "ThesisOutcome",
    "ThesisScoringAgent",
    "ThesisStage",
    "TransitionSignificance",
    "WrittenEdge",
    "assess_independence",
    "classify_transition",
    "clusters_from_pairs",
    "cosine_similarity",
    "coverage_of",
    "duplicate_suppression_rate",
    "effective_sources",
    "evaluate_clustering",
    "independent_support",
    "jaccard",
    "lookup",
    "material_candidates",
    "normalize_for_matching",
    "requirement_summary",
    "resolution_rate",
    "resolvable_names",
    "resolve_span",
    "shingles",
    "slugify",
    "structural_dependencies",
    "undecided_pairs",
]
