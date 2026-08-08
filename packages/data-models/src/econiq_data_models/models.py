"""The canonical ontology as relational tables (issue #2).

PostgreSQL is the system of record (tech rec §5–§6). Neo4j, when it arrives, is
a projection of this schema — never the other way round.

Every ontology node registers in ``nodes``, and typed edges in ``relationships``
reference that registry on both ends. That gives real referential integrity for
the graph while the rich non-graph metadata — timestamps, provenance,
confidence, versions — stays relational, which is exactly the shape tech rec §6
argues for.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

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
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from econiq_data_models import enums as e
from econiq_data_models.base import (
    EMBEDDING_DIM,
    Base,
    ObservationMixin,
    RevisionMixin,
    TimestampMixin,
    current_revision_index,
    uuid_pk,
)


def _uuid_col(nullable: bool = False, index: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), nullable=nullable, index=index)


def _node_pk() -> Mapped[uuid.UUID]:
    """Identity column of an ontology entity: its own PK and an FK into ``nodes``."""
    return mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("nodes.node_id", ondelete="RESTRICT"),
        primary_key=True,
    )


def _node_fk(nullable: bool = False, index: bool = True) -> Mapped[uuid.UUID]:
    """A reference to an ontology node.

    Node *type* is enforced in the application layer: Postgres cannot express
    "this column may only reference a Process" without denormalising the type
    into every child table. The evaluation harness (issue #16) asserts it.
    """
    return mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("nodes.node_id", ondelete="RESTRICT"),
        nullable=nullable,
        index=index,
    )


def _run_fk(nullable: bool = True) -> Mapped[uuid.UUID | None]:
    return mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_runs.agent_run_id", ondelete="RESTRICT"),
        nullable=nullable,
        index=True,
    )


def _confidence(nullable: bool = False) -> Mapped[float]:
    return mapped_column(Float, nullable=nullable)


# --------------------------------------------------------------------------- #
# Provenance and versioning
# --------------------------------------------------------------------------- #


class ModelVersion(Base, TimestampMixin):
    """An LLM configuration the system has used.

    Recorded so that "which model believed this?" is answerable years later,
    including after the provider retires the model.
    """

    __tablename__ = "model_versions"

    model_version_id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, comment="effort, max_tokens, etc."
    )

    __table_args__ = (UniqueConstraint("provider", "model", "parameters"),)


class PromptVersion(Base, TimestampMixin):
    """A prompt as it existed when it produced output.

    ``content_hash`` catches the failure versioning alone misses: an edited
    prompt whose version number was never bumped (agent doc §21).
    """

    __tablename__ = "prompt_versions"

    prompt_version_id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("name", "version", "content_hash"),)


class AgentRun(Base, TimestampMixin):
    """One invocation of one agent.

    The join point of the whole provenance chain: every derived row references
    the run that produced it, and the run references the prompt, the model, the
    input it saw and the output it returned.
    """

    __tablename__ = "agent_runs"

    agent_run_id: Mapped[uuid.UUID] = uuid_pk()
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ontology_layer: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prompt_versions.prompt_version_id", ondelete="RESTRICT"),
        nullable=True,
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_versions.model_version_id", ondelete="RESTRICT"),
        nullable=True,
    )
    input_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    output_schema_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Point-in-time cut-off the agent was given (ontology §33).",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[e.AgentRunStatus] = mapped_column(e.AGENT_RUN_STATUS, nullable=False)

    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Deterministic check results for this run."
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Event that triggered this run, for staged propagation (ontology §46).",
    )


# --------------------------------------------------------------------------- #
# Node registry
# --------------------------------------------------------------------------- #


class Node(Base, TimestampMixin):
    """Identity of every ontology object that can participate in the graph.

    One row per object identity, independent of revisions. Typed edges reference
    this table, so a relationship can never point at something that does not
    exist — the integrity guarantee a graph database would give us, kept in
    Postgres (tech rec §6).
    """

    __tablename__ = "nodes"

    node_id: Mapped[uuid.UUID] = uuid_pk()
    node_type: Mapped[EntityType] = mapped_column(e.ENTITY_TYPE, nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(160), nullable=True)

    __table_args__ = (UniqueConstraint("node_type", "slug"),)


# --------------------------------------------------------------------------- #
# Document → Claim → Event
# --------------------------------------------------------------------------- #


class Document(Base, TimestampMixin):
    """Immutable. A document is evidence; it is never rewritten (ontology §4).

    The body lives in object storage and Postgres holds the reference plus
    metadata (tech rec §8). ``content_hash`` is the ingest dedup key.
    """

    __tablename__ = "documents"

    document_id: Mapped[uuid.UUID] = _node_pk()
    source: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    publisher: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[DocumentType] = mapped_column(e.DOCUMENT_TYPE, nullable=False)
    publication_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    raw_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "Normalized text, mirrored here when small enough that agents should "
            "not pay an object-store round trip. The S3 copy stays authoritative."
        ),
    )
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        e.EXTRACTION_STATUS, nullable=False, index=True
    )

    __table_args__ = (
        CheckConstraint("retrieved_at >= publication_time", name="retrieved_after_published"),
        {"comment": "Immutable source documents. Never updated in place."},
    )


class Claim(Base, TimestampMixin):
    """Immutable. An atomic proposition with an exact source location.

    A Claim that cannot be pointed back at its document is not attributable, so
    ``source_location`` is mandatory (ontology §5).
    """

    __tablename__ = "claims"

    claim_id: Mapped[uuid.UUID] = _node_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[ClaimType] = mapped_column(e.CLAIM_TYPE, nullable=False, index=True)
    assertion_source: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="Finer-grained attribution: company_forecast, analyst_opinion, …",
    )
    attributed_to: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_location: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    extraction_confidence: Mapped[float] = _confidence()
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    stated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()


class Event(Base, RevisionMixin):
    """The deduplication layer (ontology §6).

    ``independent_source_count`` is derived from the distinct originating
    publishers of the supporting Claims, not asserted by a model: twenty
    syndications of one wire story are one source, and treating them as twenty
    is the specific failure this layer exists to prevent.
    """

    __tablename__ = "events"

    event_id: Mapped[uuid.UUID] = _node_pk()
    event_type: Mapped[EventType] = mapped_column(e.EVENT_TYPE, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    independent_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    novelty: Mapped[float] = mapped_column(Float, nullable=False)
    materiality: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = _confidence()
    epistemic_status: Mapped[EpistemicStatus] = mapped_column(e.EPISTEMIC_STATUS, nullable=False)
    contradictions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    propagated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this Event was propagated downstream; NULL means pending.",
    )
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        current_revision_index("events", "event_id"),
        CheckConstraint("independent_source_count >= 1", name="sources_positive"),
        CheckConstraint("novelty >= 0 AND novelty <= 10", name="novelty_range"),
        CheckConstraint("materiality >= 0 AND materiality <= 10", name="materiality_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class EventClaim(Base, TimestampMixin):
    """Which Claims support which Event.

    Append-only: a Claim removed from a cluster is marked, never deleted, so the
    clustering decision remains auditable.
    """

    __tablename__ = "event_claims"

    event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("nodes.node_id", ondelete="RESTRICT"), primary_key=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("claims.claim_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()


# --------------------------------------------------------------------------- #
# Process → State → Bottleneck → Capability
# --------------------------------------------------------------------------- #


class Process(Base, RevisionMixin):
    """A persistent latent object that accumulates evidence (ontology §7).

    Drivers and Mechanisms are edges, not columns: they are roles a Process
    plays in a relationship, and a Process is a Mechanism downstream of one and
    a Driver of the next (ontology §9).
    """

    __tablename__ = "processes"

    process_id: Mapped[uuid.UUID] = _node_pk()
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    archetype: Mapped[ProcessArchetype | None] = mapped_column(
        e.PROCESS_ARCHETYPE, nullable=True, index=True
    )
    archetype_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[ProcessStatus] = mapped_column(e.PROCESS_STATUS, nullable=False, index=True)
    merged_into: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("nodes.node_id", ondelete="RESTRICT"), nullable=True
    )
    requires_review: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
        comment=(
            "Human review hook (agent doc §23). A false Process contaminates "
            "the whole graph, so newly discovered ones are flagged."
        ),
    )
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        current_revision_index("processes", "process_id"),
        CheckConstraint(
            "archetype_confidence IS NULL OR archetype IS NOT NULL",
            name="confidence_requires_archetype",
        ),
        CheckConstraint(
            "status <> 'merged' OR merged_into IS NOT NULL", name="merged_needs_target"
        ),
    )


class ProcessState(Base, ObservationMixin):
    """Append-only State estimates (ontology §10).

    Never updated: the sequence of rows *is* the State history, which is what
    makes "why did the system believe this on July 14?" answerable
    (ui_concept §32).

    ``transition_beliefs`` is not called transition_probabilities on purpose —
    until the calibration framework (issue #55) validates them, these are model
    beliefs and the language must not imply otherwise (ontology §35).
    """

    __tablename__ = "process_states"

    process_state_id: Mapped[uuid.UUID] = uuid_pk()
    process_id: Mapped[uuid.UUID] = _node_fk()
    archetype: Mapped[ProcessArchetype] = mapped_column(e.PROCESS_ARCHETYPE, nullable=False)
    categorical_state: Mapped[ProcessStateLabel] = mapped_column(
        e.PROCESS_STATE_LABEL, nullable=False, index=True
    )
    state_confidence: Mapped[float] = _confidence()
    transition_beliefs: Mapped[dict[str, float]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    transition_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    reversal_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    previous_state_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process_states.process_state_id", ondelete="RESTRICT"),
        nullable=True,
    )
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    features: Mapped[list[ProcessStateFeature]] = relationship(
        back_populates="state", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_process_states_process_observed", "process_id", "observed_at"),
        CheckConstraint(
            "state_confidence >= 0 AND state_confidence <= 1", name="state_confidence_range"
        ),
        CheckConstraint("recorded_at >= observed_at", name="recorded_after_observed"),
    )


class ProcessStateFeature(Base):
    """One observable characteristic of a State, e.g. ``capex_acceleration``.

    Relational rather than JSONB because Phase 2 similarity scoring queries
    these across thousands of historical States (ontology §31).
    """

    __tablename__ = "process_state_features"

    process_state_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process_states.process_state_id", ondelete="CASCADE"),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    basis: Mapped[e.ValueBasis] = mapped_column(e.VALUE_BASIS, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    state: Mapped[ProcessState] = relationship(back_populates="features")

    __table_args__ = (CheckConstraint("value >= 0 AND value <= 10", name="feature_range"),)


class Bottleneck(Base, RevisionMixin):
    """What constrains a Process (ontology §11).

    ``currently_binding`` separates a constraint that binds now from one that
    will bind later — conflating them is how a research system talks itself into
    positions years early.
    """

    __tablename__ = "bottlenecks"

    bottleneck_id: Mapped[uuid.UUID] = _node_pk()
    process_id: Mapped[uuid.UUID] = _node_fk()
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[BottleneckKind] = mapped_column(e.BOTTLENECK_KIND, nullable=False, index=True)
    currently_binding: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    demand_pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    supply_elasticity: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_to_expand: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_constraint: Mapped[float | None] = mapped_column(Float, nullable=True)
    relief_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float] = _confidence()
    resolved: Mapped[bool] = mapped_column(nullable=False, default=False)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (current_revision_index("bottlenecks", "bottleneck_id"),)


class Capability(Base, RevisionMixin):
    """A concrete economic capability (ontology §12).

    Shared across Processes on purpose: confluence — several independent
    Processes converging on one Capability (ontology §13) — is only visible if
    the Capability is one node with several inbound edges.
    """

    __tablename__ = "capabilities"

    capability_id: Mapped[uuid.UUID] = _node_pk()
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (current_revision_index("capabilities", "capability_id"),)


class CapabilityRequirement(Base, RevisionMixin):
    """The requirement structure attached to a Bottleneck or Process.

    The logical shape is the point: "domestic production AND processing" implies
    a different Asset universe than the same two capabilities joined by OR
    (ontology §12). The tree itself lives in ``requirement_nodes``.
    """

    __tablename__ = "capability_requirements"

    requirement_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    bottleneck_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("nodes.node_id", ondelete="RESTRICT"), nullable=True
    )
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("nodes.node_id", ondelete="RESTRICT"), nullable=True
    )
    root_node_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        current_revision_index("capability_requirements", "requirement_id"),
        CheckConstraint(
            "bottleneck_id IS NOT NULL OR process_id IS NOT NULL", name="requirement_anchored"
        ),
    )


class RequirementNode(Base):
    """One node of a requirement tree: a logical group or a Capability leaf.

    Kept relational rather than as a JSONB blob so that "which Capabilities does
    this Bottleneck require?" is a join, not a document scan — Asset discovery
    walks these constantly.
    """

    __tablename__ = "requirement_nodes"

    requirement_node_id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    requirement_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("requirement_nodes.requirement_node_id", ondelete="CASCADE"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[e.RequirementNodeKind] = mapped_column(e.REQUIREMENT_NODE_KIND, nullable=False)
    operator: Mapped[LogicOperator | None] = mapped_column(e.LOGIC_OPERATOR, nullable=True)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("nodes.node_id", ondelete="RESTRICT"), nullable=True
    )
    necessity: Mapped[Necessity] = mapped_column(e.NECESSITY, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["requirement_id", "requirement_revision"],
            ["capability_requirements.requirement_id", "capability_requirements.revision"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(kind = 'group' AND operator IS NOT NULL AND capability_id IS NULL) OR "
            "(kind = 'capability' AND capability_id IS NOT NULL AND operator IS NULL)",
            name="node_shape",
        ),
        CheckConstraint("weight >= 0 AND weight <= 1", name="weight_range"),
        Index("ix_requirement_nodes_requirement", "requirement_id", "requirement_revision"),
    )


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #


class Asset(Base, RevisionMixin):
    """An investable projection of an upstream configuration (ontology §14).

    V1 covers the underlying instrument only — options and derivatives are out
    of scope, and there is deliberately nowhere here to record one.
    """

    __tablename__ = "assets"

    asset_id: Mapped[uuid.UUID] = _node_pk()
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(e.ASSET_CLASS, nullable=False, index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    figi: Mapped[str | None] = mapped_column(String(12), nullable=True)
    cik: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Non-equity identifiers. A Commodity Supply Cycle is often expressed most
    # cleanly by the commodity itself, and a policy-driven Process by a currency;
    # an assets table that only knew about tickers would force every thesis into
    # the equity market.
    commodity_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    contract_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    benchmark: Mapped[str | None] = mapped_column(String(128), nullable=True)
    currency_pair: Mapped[str | None] = mapped_column(String(6), nullable=True, index=True)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        current_revision_index("assets", "asset_id"),
        CheckConstraint(
            "asset_class NOT IN ('common_stock', 'etf') OR ticker IS NOT NULL",
            name="listed_assets_need_ticker",
        ),
        CheckConstraint(
            "asset_class <> 'commodity' OR commodity_code IS NOT NULL "
            "OR contract_code IS NOT NULL OR benchmark IS NOT NULL",
            name="commodities_need_a_code",
        ),
        CheckConstraint(
            "asset_class <> 'currency' OR currency_pair IS NOT NULL OR currency_code IS NOT NULL",
            name="currencies_need_a_pair_or_code",
        ),
    )


class AssetCandidate(Base, TimestampMixin):
    """A proposed Asset, before identifier resolution (ontology §3).

    Candidates are kept even when resolution fails: an unresolvable proposal is
    a signal about Asset-discovery quality, and deleting it would hide that.
    """

    __tablename__ = "asset_candidates"

    asset_candidate_id: Mapped[uuid.UUID] = uuid_pk()
    proposed_name: Mapped[str] = mapped_column(String(256), nullable=False)
    proposed_ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    proposed_exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    proposed_symbol: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="Commodity code or currency pair, for non-equity expressions.",
    )
    asset_class: Mapped[AssetClass] = mapped_column(e.ASSET_CLASS, nullable=False)
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("nodes.node_id", ondelete="RESTRICT"), nullable=True
    )
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("nodes.node_id", ondelete="RESTRICT"), nullable=True
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = _confidence()
    resolved_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("nodes.node_id", ondelete="RESTRICT"), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()


class AssetExposure(Base, ObservationMixin):
    """How much of an Asset is exposed to a Process or Capability (ontology §16).

    An observation, not a property: exposure changes as the business changes,
    and a historical snapshot must see the exposure believed at that time.
    """

    __tablename__ = "asset_exposures"

    asset_exposure_id: Mapped[uuid.UUID] = uuid_pk()
    asset_id: Mapped[uuid.UUID] = _node_fk()
    target_id: Mapped[uuid.UUID] = _node_fk()
    target_type: Mapped[EntityType] = mapped_column(e.ENTITY_TYPE, nullable=False)
    exposure_kind: Mapped[ExposureKind] = mapped_column(e.EXPOSURE_KIND, nullable=False)
    directness: Mapped[str] = mapped_column(String(16), nullable=False)
    magnitude: Mapped[float] = mapped_column(Float, nullable=False)
    revenue_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantitative_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = _confidence()
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        Index("ix_asset_exposures_asset_target", "asset_id", "target_id", "observed_at"),
        CheckConstraint("target_type IN ('process', 'capability')", name="exposure_target_type"),
        CheckConstraint("magnitude >= 0 AND magnitude <= 10", name="magnitude_range"),
        CheckConstraint(
            "revenue_share IS NULL OR quantitative_basis IS NOT NULL",
            name="revenue_share_needs_basis",
        ),
    )


class AssetState(Base, ObservationMixin):
    """An Asset's own state, independent of the Process (ontology §16).

    The five dimension groups are stored as JSONB rather than a hundred columns:
    the contract is pinned in ``econiq_ontology.asset_layer``, and Phase 3
    (issues #47–#50) owns populating it. Committing to columns now would be
    guessing at a financial data model we have not chosen a vendor for.
    """

    __tablename__ = "asset_states"

    asset_state_id: Mapped[uuid.UUID] = uuid_pk()
    asset_id: Mapped[uuid.UUID] = _node_fk()
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    fundamental: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    valuation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    market_structure: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    technical: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (Index("ix_asset_states_asset_observed", "asset_id", "observed_at"),)


# --------------------------------------------------------------------------- #
# Graph, evidence and scores
# --------------------------------------------------------------------------- #


class Relationship(Base, RevisionMixin):
    """A typed, evidenced edge (ui_concept §9.1).

    Both endpoints are foreign keys into ``nodes``, so an edge cannot dangle.
    Which ``(source_type, relationship_type, target_type)`` triples are legal is
    enforced by ``econiq_ontology.graph.ALLOWED_EDGES`` before insert — an edge
    from a Bottleneck straight to an Asset would silently skip the Capability
    layer, which is exactly the shortcut this system exists to prevent.
    """

    __tablename__ = "relationships"

    relationship_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[uuid.UUID] = _node_fk()
    target_id: Mapped[uuid.UUID] = _node_fk()
    relationship_type: Mapped[RelationshipType] = mapped_column(
        e.RELATIONSHIP_TYPE, nullable=False, index=True
    )
    causal_role: Mapped[CausalRole | None] = mapped_column(e.CAUSAL_ROLE, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence: Mapped[float] = _confidence()
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        current_revision_index("relationships", "relationship_id"),
        CheckConstraint("source_id <> target_id", name="no_self_edges"),
        CheckConstraint(
            "causal_role IS NULL OR relationship_type = 'influences'",
            name="causal_role_only_on_influences",
        ),
        Index("ix_relationships_source_type", "source_id", "relationship_type"),
        Index("ix_relationships_target_type", "target_id", "relationship_type"),
    )


class EvidenceLink(Base, TimestampMixin):
    """Support for — or against — a statement about a node.

    Contradicting evidence is stored the same way as supporting evidence
    (``supports = false``). Contradiction is a scored dimension of Thesis
    Quality (ontology §17), so it must accumulate, not be filtered out.
    """

    __tablename__ = "evidence_links"

    evidence_link_id: Mapped[uuid.UUID] = uuid_pk()
    subject_id: Mapped[uuid.UUID] = _node_fk()
    evidence_id: Mapped[uuid.UUID] = _node_fk()
    supports: Mapped[bool] = mapped_column(nullable=False, default=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (Index("ix_evidence_links_subject", "subject_id", "supports"),)


class Scorecard(Base, ObservationMixin):
    """A point-in-time set of scores of one family about one subject.

    Thesis, Asset and Trade quality never mix (ontology §17). The family is a
    column and the dimensions are validated against it before insert, so a
    blended cross-family number has nowhere to live.
    """

    __tablename__ = "scorecards"

    scorecard_id: Mapped[uuid.UUID] = uuid_pk()
    subject_id: Mapped[uuid.UUID] = _node_fk()
    subject_type: Mapped[EntityType] = mapped_column(e.ENTITY_TYPE, nullable=False)
    family: Mapped[ScoreFamily] = mapped_column(e.SCORE_FAMILY, nullable=False, index=True)
    composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    process_state_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process_states.process_state_id", ondelete="RESTRICT"),
        nullable=True,
        comment="State the subject was in when scored — scores are state-conditioned.",
    )
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    dimensions: Mapped[list[ScoreDimension]] = relationship(
        back_populates="scorecard", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_scorecards_subject_family", "subject_id", "family", "observed_at"),
        CheckConstraint("family <> 'trade_quality'", name="trade_quality_is_v2"),
        CheckConstraint(
            "composite IS NULL OR composite_method IS NOT NULL",
            name="composite_needs_method",
        ),
    )


class ScoreDimension(Base):
    """One axis of a scorecard, with the inputs it was computed from.

    ``inputs`` is what makes the universal [Explain] primitive (issue #25)
    possible: a score the UI cannot decompose is a score the user cannot audit.
    """

    __tablename__ = "score_dimensions"

    scorecard_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scorecards.scorecard_id", ondelete="CASCADE"),
        primary_key=True,
    )
    dimension: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = _confidence()
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    inputs: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False, default=dict)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    scorecard: Mapped[Scorecard] = relationship(back_populates="dimensions")

    __table_args__ = (CheckConstraint("value >= 0 AND value <= 10", name="score_range"),)


class QuantitativeObservation(Base, ObservationMixin):
    """Canonical numeric facts (ontology §18).

    Restatement-aware by construction: a restated figure is a new row marked
    ``restated``, never an update. Point-in-time integrity depends on being able
    to ask "what was reported as of then", not "what do we now know to be true"
    (ontology §33).
    """

    __tablename__ = "quantitative_observations"

    observation_id: Mapped[uuid.UUID] = uuid_pk()
    subject_id: Mapped[uuid.UUID] = _node_fk()
    metric: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reported_vs_derived: Mapped[str] = mapped_column(String(16), nullable=False)
    restated: Mapped[bool] = mapped_column(nullable=False, default=False)
    restates_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("quantitative_observations.observation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_location: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_quant_obs_subject_metric", "subject_id", "metric", "period_end"),
        CheckConstraint(
            "reported_vs_derived IN ('reported', 'derived')", name="reported_or_derived"
        ),
        CheckConstraint(
            "period_end IS NULL OR period_start IS NULL OR period_end >= period_start",
            name="period_ordered",
        ),
    )


class Embedding(Base, TimestampMixin):
    """Vectors for dedup, similarity and semantic search (tech rec §7).

    pgvector inside Postgres rather than a separate vector store: the embedding
    workload can migrate later if scale demands, and until then the vectors sit
    next to the objects they describe.
    """

    __tablename__ = "embeddings"

    embedding_id: Mapped[uuid.UUID] = uuid_pk()
    node_id: Mapped[uuid.UUID] = _node_fk()
    kind: Mapped[e.EmbeddingKind] = mapped_column(e.EMBEDDING_KIND, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False, default=EMBEDDING_DIM)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    source_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Hash of the embedded text; detects staleness."
    )

    __table_args__ = (
        UniqueConstraint("node_id", "kind", "model"),
        Index(
            "ix_embeddings_vector",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class JournalEntry(Base, ObservationMixin):
    """A chronological record of what changed and why (PRD §21).

    Immutable and append-only. The revision tables record *what the system
    believes*; the journal records *why it changed its mind*, in the form a
    human reads: "state confidence 7.2 → 7.8, + utility capex, + interconnection
    acceleration". Without it the graph can be reconstructed but not explained.
    """

    __tablename__ = "journal_entries"

    journal_entry_id: Mapped[uuid.UUID] = uuid_pk()
    subject_id: Mapped[uuid.UUID] = _node_fk()
    subject_type: Mapped[EntityType] = mapped_column(e.ENTITY_TYPE, nullable=False)
    kind: Mapped[e.JournalEntryKind] = mapped_column(
        e.JOURNAL_ENTRY_KIND, nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Signed changes: [{direction, statement, rationale}, …].",
    )
    triggering_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("nodes.node_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (Index("ix_journal_entries_subject_time", "subject_id", "observed_at"),)


class Critique(Base, ObservationMixin):
    """An adversarial finding against a Process (agent doc §6.5).

    Append-only and never deleted. A thesis that survived attack is stronger
    than one that was never attacked, and that is only visible if the attacks
    stay on the record — which is also what lets the evaluation harness measure
    how many critiques turned out to be right (issue #57).

    ``testable_with`` is the load-bearing field: a critique that names the
    observation which would settle it becomes a monitoring condition later
    (issue #32), while one that cannot be settled is only an opinion.
    """

    __tablename__ = "critiques"

    critique_id: Mapped[uuid.UUID] = uuid_pk()
    subject_id: Mapped[uuid.UUID] = _node_fk()
    subject_type: Mapped[EntityType] = mapped_column(e.ENTITY_TYPE, nullable=False)
    kind: Mapped[CritiqueKind] = mapped_column(e.CRITIQUE_KIND, nullable=False, index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    testable_with: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_most_damaging: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[CritiqueStatus] = mapped_column(e.CRITIQUE_STATUS, nullable=False, index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supporting_claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        Index("ix_critiques_subject_status", "subject_id", "status", "observed_at"),
        CheckConstraint("severity >= 0 AND severity <= 10", name="severity_range"),
    )


class Counterfactual(Base, ObservationMixin):
    """An alternative world in which the Process fails (issue #66, agent doc §10.1).

    Distinct from a Critique, and the distinction is the reason this is its own
    table rather than an eighth ``CritiqueKind``. A critique attacks the
    evidence that exists; a counterfactual accepts it and asks what else could
    have produced it. They are answered differently, monitored differently, and
    scored on different axes — folding them together would make
    counterfactual_robustness uncomputable, because there would be no way to
    tell which findings it was supposed to be computed from.

    ``observable_indicators`` is the load-bearing field, as ``testable_with`` is
    for a Critique: an alternative world nobody could ever detect is not a
    research finding, and it is the shape a straw man usually takes.
    """

    __tablename__ = "counterfactuals"

    counterfactual_id: Mapped[uuid.UUID] = uuid_pk()
    process_id: Mapped[uuid.UUID] = _node_fk()
    challenged_assumption: Mapped[str] = mapped_column(Text, nullable=False)
    alternative_world: Mapped[str] = mapped_column(Text, nullable=False)
    affected_links: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    assets_harmed: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    observable_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    plausibility: Mapped[float] = mapped_column(Float, nullable=False)
    severity_if_true: Mapped[float] = mapped_column(Float, nullable=False)
    is_most_dangerous: Mapped[bool] = mapped_column(nullable=False, default=False)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set when a later run replaced this set. Never deleted.",
    )
    supporting_claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        Index("ix_counterfactuals_process", "process_id", "superseded_at", "observed_at"),
        CheckConstraint("plausibility >= 0 AND plausibility <= 10", name="plausibility_range"),
        CheckConstraint("severity_if_true >= 0 AND severity_if_true <= 10", name="severity_range"),
    )


class EvidenceDependence(Base, ObservationMixin):
    """One reason two pieces of evidence are not independent (issue #67).

    Directed: ``dependent_event_id`` leans on ``source_event_id``. The direction
    matters for derivative reporting — a wire story and the paper that picked it
    up are not symmetric, and the effective source count should keep the
    original rather than whichever row was written first.

    Stored as its own table rather than as a `derived_from` edge because the
    kind is computed on: the effective independent-source count comes from the
    connected components of this graph, and a kind kept in an edge's prose
    rationale could not be read by the code that needs it.
    """

    __tablename__ = "evidence_dependencies"

    evidence_dependence_id: Mapped[uuid.UUID] = uuid_pk()
    process_id: Mapped[uuid.UUID] = _node_fk()
    source_event_id: Mapped[uuid.UUID] = _node_fk()
    dependent_event_id: Mapped[uuid.UUID] = _node_fk()
    kind: Mapped[EvidenceDependenceKind] = mapped_column(
        e.EVIDENCE_DEPENDENCE_KIND, nullable=False, index=True
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = _confidence()
    detected_by: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="'computed' or 'judged' — whether code or an agent found it.",
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = _run_fk()

    __table_args__ = (
        Index("ix_evidence_dependencies_process", "process_id", "superseded_at"),
        CheckConstraint("source_event_id <> dependent_event_id", name="no_self_dependence"),
    )


class OutboxEvent(Base, TimestampMixin):
    """A typed domain event, written in the same transaction as the state change.

    The transactional outbox pattern (tech rec §11). Writing to a queue and to
    Postgres in two operations means one can succeed while the other fails, and
    the resulting gap is invisible — either an Event that nothing acts on, or
    work scheduled for a state change that rolled back. Here the event is a row
    in the same commit, and a dispatcher moves it outward afterwards.
    """

    __tablename__ = "outbox_events"

    outbox_event_id: Mapped[uuid.UUID] = uuid_pk()
    event_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    subject_type: Mapped[EntityType | None] = mapped_column(e.ENTITY_TYPE, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the state change happened, not when it was dispatched.",
    )
    status: Mapped[e.OutboxStatus] = mapped_column(e.OUTBOX_STATUS, nullable=False, index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_outbox_pending", "status", "occurred_at"),)


class WorkItem(Base, TimestampMixin):
    """One unit of scheduled work.

    Postgres is the queue. ``SELECT … FOR UPDATE SKIP LOCKED`` gives safe
    concurrent claiming without a broker, and at the volumes this system will
    see — a few thousand agent calls a day — the orchestration is nowhere near
    the bottleneck. The LLM spend is. See ``docs/orchestration.md``.

    ``idempotency_key`` is what makes the queue safe to double-write: the event
    path and the reconciler both enqueue, and the unique index means the second
    one is a no-op rather than a duplicate agent run.
    """

    __tablename__ = "work_items"

    work_item_id: Mapped[uuid.UUID] = uuid_pk()
    stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[e.WorkStatus] = mapped_column(e.WORK_STATUS, nullable=False, index=True)
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        comment="Lower runs first. Live material events outrank backfill.",
    )
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Backoff and time-based triggers both express themselves here.",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="event | reconciler | schedule | manual — how this was enqueued.",
    )
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outbox_events.outbox_event_id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # Only one *open* unit of work per key. Completed ones stay for audit,
        # so re-running a stage later is still possible.
        Index(
            "uq_work_items_open_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_work_items_claimable", "status", "priority", "run_after"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
    )
