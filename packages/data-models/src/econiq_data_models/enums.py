"""PostgreSQL enum types, derived from the ontology package.

Deriving them rather than restating them means the database and the Pydantic
contract cannot drift: adding an ontology member and forgetting the migration
becomes a failing test, not a runtime constraint violation in production.
"""

from __future__ import annotations

from enum import StrEnum

from econiq_ontology import (
    AssetClass,
    BottleneckKind,
    CausalRole,
    ClaimType,
    CritiqueKind,
    CritiqueStatus,
    DocumentType,
    EntityType,
    EpistemicStatus,
    EventType,
    EvidenceDependenceKind,
    ExposureKind,
    ExtractionStatus,
    LogicOperator,
    Necessity,
    ProcessArchetype,
    ProcessStateLabel,
    ProcessStatus,
    RelationshipType,
    ScoreFamily,
)
from sqlalchemy import Enum as SAEnum


def pg_enum(python_enum: type[StrEnum], name: str) -> SAEnum:
    """A native PG enum whose values are the ontology's string values."""
    return SAEnum(
        python_enum,
        name=name,
        values_callable=lambda enum: [member.value for member in enum],
        native_enum=True,
        create_constraint=False,
    )


class RequirementNodeKind(StrEnum):
    """A requirement tree node is either a logical group or a Capability leaf."""

    GROUP = "group"
    CAPABILITY = "capability"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    ABSTAINED = "abstained"
    FAILED = "failed"
    REJECTED = "rejected"
    """Output validated but failed a deterministic evaluation check."""


class JournalEntryKind(StrEnum):
    """What a journal entry records (PRD §21)."""

    CREATED = "created"
    EVIDENCE_ADDED = "evidence_added"
    BELIEF_CHANGE = "belief_change"
    STATE_CHANGE = "state_change"
    REVIEW_REQUESTED = "review_requested"
    INVALIDATED = "invalidated"


class WorkStatus(StrEnum):
    """Lifecycle of a queued unit of work."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    """Retryable; will be picked up again after its backoff."""

    DEAD = "dead"
    """Retries exhausted. Kept for inspection, never silently dropped."""

    SUPERSEDED = "superseded"
    """A newer identical unit of work made this one redundant."""


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"


class EmbeddingKind(StrEnum):
    DOCUMENT_BODY = "document_body"
    CLAIM_TEXT = "claim_text"
    EVENT_DESCRIPTION = "event_description"
    PROCESS_DESCRIPTION = "process_description"
    CAPABILITY_DESCRIPTION = "capability_description"


class ValueBasis(StrEnum):
    """Whether a number was measured from data or asserted by a model.

    The distinction is load-bearing (ontology §2.4): "capex_acceleration = 8.7"
    computed from filings and the same figure estimated by an LLM are different
    kinds of fact, and the UI must be able to tell them apart.
    """

    MEASURED = "measured"
    ESTIMATED = "estimated"


ENTITY_TYPE = pg_enum(EntityType, "entity_type")
DOCUMENT_TYPE = pg_enum(DocumentType, "document_type")
EXTRACTION_STATUS = pg_enum(ExtractionStatus, "extraction_status")
CLAIM_TYPE = pg_enum(ClaimType, "claim_type")
EPISTEMIC_STATUS = pg_enum(EpistemicStatus, "epistemic_status")
EVENT_TYPE = pg_enum(EventType, "event_type")
PROCESS_ARCHETYPE = pg_enum(ProcessArchetype, "process_archetype")
PROCESS_STATUS = pg_enum(ProcessStatus, "process_status")
PROCESS_STATE_LABEL = pg_enum(ProcessStateLabel, "process_state_label")
BOTTLENECK_KIND = pg_enum(BottleneckKind, "bottleneck_kind")
LOGIC_OPERATOR = pg_enum(LogicOperator, "logic_operator")
NECESSITY = pg_enum(Necessity, "necessity")
ASSET_CLASS = pg_enum(AssetClass, "asset_class")
EXPOSURE_KIND = pg_enum(ExposureKind, "exposure_kind")
RELATIONSHIP_TYPE = pg_enum(RelationshipType, "relationship_type")
CAUSAL_ROLE = pg_enum(CausalRole, "causal_role")
SCORE_FAMILY = pg_enum(ScoreFamily, "score_family")
REQUIREMENT_NODE_KIND = pg_enum(RequirementNodeKind, "requirement_node_kind")
AGENT_RUN_STATUS = pg_enum(AgentRunStatus, "agent_run_status")
EMBEDDING_KIND = pg_enum(EmbeddingKind, "embedding_kind")
VALUE_BASIS = pg_enum(ValueBasis, "value_basis")
JOURNAL_ENTRY_KIND = pg_enum(JournalEntryKind, "journal_entry_kind")
CRITIQUE_KIND = pg_enum(CritiqueKind, "critique_kind")
CRITIQUE_STATUS = pg_enum(CritiqueStatus, "critique_status")
EVIDENCE_DEPENDENCE_KIND = pg_enum(EvidenceDependenceKind, "evidence_dependence_kind")
WORK_STATUS = pg_enum(WorkStatus, "work_status")
OUTBOX_STATUS = pg_enum(OutboxStatus, "outbox_status")
