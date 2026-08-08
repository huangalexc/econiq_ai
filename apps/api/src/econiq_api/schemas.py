"""Response models.

These are API-shaped views, not the ontology models themselves — the ontology
carries validators and defaults that are about *producing* an object, and a
response only needs to describe one. But every enum and every vocabulary comes
from ``econiq_ontology``, so the API cannot drift from the contract without a
type error.

One rule shows up repeatedly below: a derived number is never returned without
the means to explain it. A score carries its dimensions and their inputs; a
State carries its features and their basis; an Asset carries the chain that
found it. The UI's [Explain] primitive (issue #25) is only possible if the API
never strips that.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from econiq_ontology import (
    AssetClass,
    BottleneckKind,
    CritiqueKind,
    CritiqueStatus,
    EntityType,
    EventType,
    ExposureKind,
    LogicOperator,
    Necessity,
    ProcessArchetype,
    ProcessStateLabel,
    ProcessStatus,
    RelationshipType,
    ScoreFamily,
)
from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class PageMeta(ApiModel):
    limit: int
    offset: int
    returned: int
    total: int | None = Field(
        default=None, description="Omitted where counting would be more expensive than the page."
    )


class NodeRef(ApiModel):
    """A pointer to any node, with enough to render it."""

    id: uuid.UUID
    type: EntityType
    label: str
    slug: str | None = None


# --------------------------------------------------------------------------- #
# Processes
# --------------------------------------------------------------------------- #


class ProcessSummaryOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    archetype: ProcessArchetype | None
    archetype_confidence: float | None
    status: ProcessStatus
    requires_review: bool
    revision: int
    current_state: ProcessStateLabel | None = None
    state_confidence: float | None = None
    state_observed_at: datetime | None = None


class StateFeatureOut(ApiModel):
    name: str
    value: float
    basis: str = Field(
        description="'measured' or 'estimated' — whether code computed it or an agent judged it."
    )
    rationale: str | None = None


class ProcessStateOut(ApiModel):
    id: uuid.UUID
    archetype: ProcessArchetype
    categorical_state: ProcessStateLabel
    state_confidence: float
    observed_at: datetime
    recorded_at: datetime
    features: list[StateFeatureOut] = Field(default_factory=list)
    transition_beliefs: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Model belief that the Process moves next to each State. Not "
            "probabilities: uncalibrated until the calibration framework validates "
            "them (ontology §35)."
        ),
    )
    transition_indicators: list[str] = Field(default_factory=list)
    reversal_indicators: list[str] = Field(default_factory=list)
    provenance: ProvenanceOut | None = None


class JournalEntryOut(ApiModel):
    """Why the system changed its mind (PRD §21)."""

    id: uuid.UUID
    kind: str
    summary: str
    observed_at: datetime
    confidence_before: float | None
    confidence_after: float | None
    changes: list[dict[str, Any]] = Field(default_factory=list)
    triggering_event_id: uuid.UUID | None = None


class CritiqueOut(ApiModel):
    id: uuid.UUID
    kind: CritiqueKind
    statement: str
    severity: float
    rationale: str
    testable_with: str | None
    is_most_damaging: bool
    status: CritiqueStatus
    observed_at: datetime

    @classmethod
    def from_row(cls, row: Any) -> CritiqueOut:
        # Built explicitly rather than by attribute matching: the ORM primary
        # key is `critique_id` and silently returning nothing for `id` would be
        # a worse failure than a mapping that has to be maintained.
        return cls(
            id=row.critique_id,
            kind=row.kind,
            statement=row.statement,
            severity=row.severity,
            rationale=row.rationale,
            testable_with=row.testable_with,
            is_most_damaging=row.is_most_damaging,
            status=row.status,
            observed_at=row.observed_at,
        )


class ProcessDetailOut(ProcessSummaryOut):
    state: ProcessStateOut | None = None
    open_bottlenecks: list[BottleneckOut] = Field(default_factory=list)
    open_critiques: list[CritiqueOut] = Field(default_factory=list)
    evidence_event_count: int = 0
    contradicting_event_count: int = 0


# --------------------------------------------------------------------------- #
# Events and evidence
# --------------------------------------------------------------------------- #


class EventOut(ApiModel):
    id: uuid.UUID
    event_type: EventType
    title: str
    description: str
    occurred_at: datetime
    independent_source_count: int = Field(
        description=(
            "Distinct reports behind this Event after syndication collapse — not "
            "the document count (ontology §47)."
        )
    )
    novelty: float
    materiality: float
    confidence: float
    contradictions: list[str] = Field(default_factory=list)
    propagated_at: datetime | None = Field(
        default=None,
        description="When this Event cleared the significance gate. Null means it is accumulating.",
    )
    revision: int


class ProvenanceOut(ApiModel):
    """Who produced a derived row, with what, and when (ui_concept §23, §29).

    One shape for every explanation. §23 requires model version, timestamp and
    confidence on all of them, and three near-identical bespoke versions would
    have drifted the first time one of them gained a field.
    """

    agent_run_id: uuid.UUID
    agent_name: str
    agent_version: str
    model: str | None = None
    provider: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None
    prompt_content_hash: str | None = Field(
        default=None,
        description=(
            "First 12 characters. Enough to tell whether two rows came from the "
            "same prompt text, which is the question a reader actually has."
        ),
    )
    as_of: datetime = Field(description="The cut-off the agent was given.")
    recorded_at: datetime
    status: str
    evaluation_passed: bool | None = Field(
        default=None,
        description="Whether the deterministic checks accepted this output.",
    )
    advisories: list[str] = Field(
        default_factory=list,
        description="Non-blocking check failures. The output was accepted with these noted.",
    )


class ClaimOut(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    text: str
    claim_type: str
    assertion_source: str | None
    attributed_to: str | None
    extraction_confidence: float
    source_location: dict[str, Any] = Field(
        description="Verified span: the quote and its offsets in the parsed document."
    )
    stated_at: datetime | None = Field(
        default=None,
        description=(
            "When the Claim says the thing happened, where that differs from "
            "when its document was published."
        ),
    )
    provenance: ProvenanceOut | None = Field(
        default=None,
        description=(
            "The extraction run. Null means nothing can be attributed, which is "
            "shown rather than hidden — an unattributable quotation is exactly "
            "what the evidence chain exists to prevent."
        ),
    )


class DocumentOut(ApiModel):
    id: uuid.UUID
    source: str
    publisher: str | None
    title: str
    url: str | None
    document_type: str
    publication_time: datetime
    storage_uri: str | None


class EventDetailOut(EventOut):
    claims: list[ClaimOut] = Field(default_factory=list)
    documents: list[DocumentOut] = Field(default_factory=list)


class EvidenceTrailOut(ApiModel):
    """A statement traced to the documents behind it (agent doc §2.4)."""

    subject: NodeRef
    supporting_events: list[NodeRef] = Field(default_factory=list)
    contradicting_events: list[NodeRef] = Field(default_factory=list)
    claim_ids: list[uuid.UUID] = Field(default_factory=list)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    is_evidenced: bool


class ProvenanceInspectionOut(ApiModel):
    """The full drill-down behind one node (ui_concept §29).

    §29 is explicit that "evidence should never be represented merely as an
    undifferentiated AI summary". So this returns the Claims themselves, with
    their verified source spans and the run that extracted each — not counts,
    and not a paraphrase.
    """

    subject: NodeRef
    is_evidenced: bool
    supporting_events: list[NodeRef] = Field(default_factory=list)
    contradicting_events: list[NodeRef] = Field(default_factory=list)
    claims: list[ClaimOut] = Field(default_factory=list)
    documents: list[DocumentOut] = Field(default_factory=list)
    independent_source_count: int = Field(
        default=0,
        description=(
            "Distinct reports after syndication collapse, summed over the "
            "supporting Events — not the document count (ontology §47)."
        ),
    )


# --------------------------------------------------------------------------- #
# Bottlenecks and capabilities
# --------------------------------------------------------------------------- #


class BottleneckOut(ApiModel):
    id: uuid.UUID
    process_id: uuid.UUID
    name: str
    description: str
    kind: BottleneckKind
    currently_binding: bool = Field(
        description="Whether it constrains the Process now, or would only later."
    )
    demand_pressure: float | None
    supply_elasticity: float | None
    time_to_expand: float | None
    current_constraint: float | None
    relief_indicators: list[str] = Field(default_factory=list)
    confidence: float
    resolved: bool

    @classmethod
    def from_row(cls, row: Any) -> BottleneckOut:
        return cls(
            id=row.bottleneck_id,
            process_id=row.process_id,
            name=row.name,
            description=row.description,
            kind=row.kind,
            currently_binding=row.currently_binding,
            demand_pressure=row.demand_pressure,
            supply_elasticity=row.supply_elasticity,
            time_to_expand=row.time_to_expand,
            current_constraint=row.current_constraint,
            relief_indicators=list(row.relief_indicators),
            confidence=row.confidence,
            resolved=row.resolved,
        )


class RequirementNodeOut(ApiModel):
    """One node of a requirement tree.

    Returned as a tree rather than a flat list because AND and OR imply
    completely different sets of participants (ontology §12), and flattening for
    transport would discard the distinction the mapping agent was asked for.
    """

    kind: str
    operator: LogicOperator | None = None
    label: str | None = None
    capability: NodeRef | None = None
    necessity: Necessity
    weight: float
    children: list[RequirementNodeOut] = Field(default_factory=list)


class CapabilityOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    aliases: list[str] = Field(default_factory=list)


class CapabilityDetailOut(CapabilityOut):
    upstream_processes: list[NodeRef] = Field(
        default_factory=list,
        description=(
            "Processes reaching this Capability. Several independent ones is "
            "confluence (ontology §13), read off the graph rather than asserted."
        ),
    )
    expressed_by: list[NodeRef] = Field(default_factory=list)


class RequirementOut(ApiModel):
    bottleneck_id: uuid.UUID
    revision: int
    root: RequirementNodeOut
    capability_count: int


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #


class AssetIdentifiersOut(ApiModel):
    """Not equity-only: a commodity carries a code and a benchmark, a currency a pair."""

    ticker: str | None = None
    exchange: str | None = None
    isin: str | None = None
    commodity_code: str | None = None
    contract_code: str | None = None
    benchmark: str | None = None
    currency_pair: str | None = None
    currency_code: str | None = None


class AssetOut(ApiModel):
    id: uuid.UUID
    name: str
    asset_class: AssetClass
    identifiers: AssetIdentifiersOut
    country: str | None
    currency: str | None
    sector: str | None
    industry: str | None
    is_active: bool


class ExposureOut(ApiModel):
    id: uuid.UUID
    target: NodeRef
    exposure_kind: ExposureKind
    directness: str
    magnitude: float
    revenue_share: float | None
    quantitative_basis: str | None = Field(
        default=None, description="The figure a revenue share rests on, where one was supplied."
    )
    rationale: str
    confidence: float
    observed_at: datetime


class PathStepOut(ApiModel):
    relationship_type: RelationshipType
    rationale: str | None
    to: NodeRef


class DiscoveryPathOut(ApiModel):
    """One route from a Process down to an Asset, with the reason at each step."""

    start: NodeRef
    steps: list[PathStepOut]
    depth: int
    weight: float


class AssetDetailOut(AssetOut):
    discovery_chain: list[DiscoveryPathOut] = Field(
        default_factory=list, description="Why this Asset is in the graph (issue #28)."
    )
    exposures: list[ExposureOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Scores, graph, runs
# --------------------------------------------------------------------------- #


class ScoreDimensionOut(ApiModel):
    dimension: str
    value: float
    confidence: float
    method: str
    inputs: dict[str, float] = Field(
        default_factory=dict, description="What the value was computed from."
    )
    rationale: str | None = None


class ScorecardOut(ApiModel):
    """One family, never a blend.

    Thesis, Asset and Trade quality are separate by construction (ontology §17),
    and there is deliberately no endpoint that combines them.
    """

    id: uuid.UUID
    subject: NodeRef
    family: ScoreFamily
    observed_at: datetime
    composite: float | None
    composite_method: str | None
    dimensions: list[ScoreDimensionOut] = Field(default_factory=list)
    provenance: ProvenanceOut | None = None


class GraphNodeOut(ApiModel):
    id: uuid.UUID
    type: EntityType
    label: str
    slug: str | None = None


class GraphEdgeOut(ApiModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    relationship_type: RelationshipType
    weight: float
    confidence: float
    rationale: str | None = None


class SubgraphOut(ApiModel):
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)


class AssetReachOut(ApiModel):
    asset: NodeRef
    shortest_hops: int
    distinct_source_count: int
    best_weight: float
    paths: list[DiscoveryPathOut] = Field(default_factory=list)


class IntegrityViolationOut(ApiModel):
    kind: str
    node_id: uuid.UUID | None
    detail: str


class IntegrityReportOut(ApiModel):
    ok: bool
    checked_at: datetime | None
    violations: list[IntegrityViolationOut] = Field(default_factory=list)


class AgentRunOut(ApiModel):
    """The provenance record every derived row cites."""

    id: uuid.UUID
    agent_name: str
    agent_version: str
    ontology_layer: str
    status: str
    as_of: datetime
    started_at: datetime
    finished_at: datetime | None
    attempts: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: float | None
    evaluation: dict[str, Any] | None = None
    trigger_event_id: uuid.UUID | None = None


class PipelineStageOut(ApiModel):
    name: str
    priority: int
    concurrency: int
    triggered_by: list[str]
    emits: list[str]
    description: str
    has_handler: bool
    has_reconciler: bool


class QueueDepthOut(ApiModel):
    stage: str | None
    pending: int
    running: int
    failed: int
    dead: int


class HealthOut(ApiModel):
    status: str
    database: bool
    schema_version: str | None = None


RequirementNodeOut.model_rebuild()
ProcessDetailOut.model_rebuild()


# --------------------------------------------------------------------------- #
# Discover feed (issue #20, ui_concept §5)
# --------------------------------------------------------------------------- #


class RankComponentOut(ApiModel):
    """One input to the Discover rank, with the arithmetic left visible.

    Returned so the ranking can be taken apart on screen (#25). A rank nobody
    can decompose is a number the reader has to take on trust, which is the
    opposite of what this product is for.
    """

    name: str
    raw: float = Field(description="The measurement, in its own units.")
    normalised: float = Field(ge=0.0, le=1.0)
    weight: float
    contribution: float


class EmergingProcessOut(ProcessSummaryOut):
    """A row of the emerging-Process panel (§5.1)."""

    rank_score: float
    components: list[RankComponentOut] = Field(default_factory=list)
    evidence_recent: int = Field(description="Evidence links in the trailing window.")
    evidence_prior: int = Field(description="The window before it, for comparison.")
    evidence_delta: int
    contradiction_count: int = Field(
        description=(
            "Evidence recorded against this Process. Shown rather than netted "
            "off: contradiction is a scored dimension, not a deduction (§17)."
        )
    )
    source_breadth: int = Field(
        description=(
            "Distinct publishers behind the supporting Events. A media-coverage "
            "proxy, reported beside the rank rather than inside it — Phase 0 has "
            "no market data, and calling this 'attention' would make §5.2's "
            "central claim untestable."
        )
    )
    capability_count: int
    asset_count: int
    binding_bottlenecks: list[str] = Field(default_factory=list)


class UnavailableInputOut(ApiModel):
    """A §5.1 ranking input this deployment cannot compute, and why."""

    name: str
    reason: str


class DiscoverFeedOut(ApiModel):
    """The Discover feed, with its own limits attached.

    ``unavailable_inputs`` is part of the response rather than documentation: a
    ranking that silently drops half of its stated inputs is a different ranking
    wearing the same name, and the screen should be able to say so.
    """

    processes: list[EmergingProcessOut] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    window_days: int
    unavailable_inputs: list[UnavailableInputOut] = Field(default_factory=list)
    is_prediction: Literal[False] = Field(
        default=False,
        description=(
            "A discovery ranking, not a forecast (ui_concept §5.2). Present so a "
            "client cannot mistake the ordering for a predicted return."
        ),
    )


# --------------------------------------------------------------------------- #
# Process timeline (issue #20)
# --------------------------------------------------------------------------- #


class TimelineEntryOut(ApiModel):
    """One dated thing that happened to a Process.

    State changes, journal entries and evidence arrivals share an axis because
    the question the Process screen answers is "what changed and why", and the
    answer is usually an evidence arrival next to the belief change it caused.
    Three separate lists would leave the reader doing that join by eye.
    """

    kind: Literal["state", "journal", "evidence", "critique"]
    occurred_at: datetime = Field(description="When the thing being described happened.")
    recorded_at: datetime = Field(description="When the system learned it.")
    title: str
    detail: str | None = None
    subject_id: uuid.UUID | None = Field(
        default=None, description="The Event, State or entry this entry points at."
    )
    supports: bool | None = Field(
        default=None, description="Evidence direction, where the entry is evidence."
    )
    confidence_before: float | None = None
    confidence_after: float | None = None
    state_label: ProcessStateLabel | None = None


class ProcessTimelineOut(ApiModel):
    process_id: uuid.UUID
    entries: list[TimelineEntryOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Archetype State machines (issues #22, #23)
# --------------------------------------------------------------------------- #


class StateNodeOut(ApiModel):
    """One State on an archetype's machine."""

    state: ProcessStateLabel
    ordinal: int = Field(description="Position in the developmental sequence.")
    maturity: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Ordinal normalised to 0-1. The Emergence Radar's maturity axis "
            "(§5.2). A position on a machine, not an age or a probability."
        ),
    )
    transitions_to: list[str] = Field(default_factory=list)
    is_terminal: bool


class ArchetypeMachineOut(ApiModel):
    """The State model of one archetype (ontology §8).

    Served so the terminal draws the machine from the ontology rather than from
    a copy. The sequence defines which States are adjacent, and an inlined copy
    would drift the first time an archetype gained one.
    """

    archetype: ProcessArchetype
    cyclical: bool
    states: list[StateNodeOut] = Field(default_factory=list)
