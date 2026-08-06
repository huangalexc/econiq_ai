"""PostgreSQL system of record for the econiq ontology.

Postgres holds the canonical ontology; LLMs are processors over this state, never
its source (tech rec §33). Nothing here is updated destructively: revisable
entities are append-only revisions, observations are append-only by nature.
"""

from econiq_data_models.base import EMBEDDING_DIM, Base
from econiq_data_models.enums import (
    AgentRunStatus,
    EmbeddingKind,
    JournalEntryKind,
    RequirementNodeKind,
    ValueBasis,
)
from econiq_data_models.models import (
    AgentRun,
    Asset,
    AssetCandidate,
    AssetExposure,
    AssetState,
    Bottleneck,
    Capability,
    CapabilityRequirement,
    Claim,
    Document,
    Embedding,
    Event,
    EventClaim,
    EvidenceLink,
    JournalEntry,
    ModelVersion,
    Node,
    Process,
    ProcessState,
    ProcessStateFeature,
    PromptVersion,
    QuantitativeObservation,
    Relationship,
    RequirementNode,
    Scorecard,
    ScoreDimension,
)
from econiq_data_models.session import (
    DatabaseSettings,
    create_engine,
    create_session_factory,
    session_scope,
)

__all__ = [
    "EMBEDDING_DIM",
    "AgentRun",
    "AgentRunStatus",
    "Asset",
    "AssetCandidate",
    "AssetExposure",
    "AssetState",
    "Base",
    "Bottleneck",
    "Capability",
    "CapabilityRequirement",
    "Claim",
    "DatabaseSettings",
    "Document",
    "Embedding",
    "EmbeddingKind",
    "Event",
    "EventClaim",
    "EvidenceLink",
    "JournalEntry",
    "JournalEntryKind",
    "ModelVersion",
    "Node",
    "Process",
    "ProcessState",
    "ProcessStateFeature",
    "PromptVersion",
    "QuantitativeObservation",
    "Relationship",
    "RequirementNode",
    "RequirementNodeKind",
    "ScoreDimension",
    "Scorecard",
    "ValueBasis",
    "create_engine",
    "create_session_factory",
    "session_scope",
]
