"""Event Resolution and Event Significance agents (agent doc §5).

Event resolution is where the system stops treating repetition as evidence.
The rule from §5.1 — "do not count repeated reporting of the same source as
independent evidence" — is represented structurally: the agent reports the
distinct publishers behind a cluster, and code derives the independent source
count from that rather than trusting a number the model made up.
"""

from __future__ import annotations

from datetime import datetime

from econiq_ontology import Confidence, EntityMention, EventType
from pydantic import Field

from econiq_schemas.base import AgentInput, AgentIO, AgentOutput, ScoredJudgement


class ClaimForResolution(AgentIO):
    """One Claim as presented to the resolution agent."""

    claim_id: str
    text: str
    document_id: str
    publisher: str | None = None
    publication_time: datetime
    entities: list[EntityMention] = Field(default_factory=list)


class KnownEvent(AgentIO):
    """An existing Event a new cluster might belong to, rather than duplicate."""

    event_id: str
    title: str
    event_type: EventType
    timestamp: datetime


class EventResolutionInput(AgentInput):
    claims: list[ClaimForResolution] = Field(min_length=1)
    known_events: list[KnownEvent] = Field(
        default_factory=list, description="Recent Events in the same entity neighbourhood."
    )


class ProposedEvent(AgentIO):
    """A cluster of Claims describing one real-world occurrence."""

    canonical_title: str
    description: str
    event_type: EventType
    timestamp: datetime = Field(description="When the occurrence happened.")
    supporting_claim_ids: list[str] = Field(min_length=1)
    distinct_publishers: list[str] = Field(
        default_factory=list,
        description=(
            "Publishers behind the cluster. Syndications of one wire story name "
            "the originating publisher once, not once per outlet."
        ),
    )
    contradictions: list[str] = Field(
        default_factory=list, description="Points on which the Claims disagree."
    )
    entities: list[EntityMention] = Field(default_factory=list)
    confidence: Confidence
    merge_into_event_id: str | None = Field(
        default=None, description="Set when this is new evidence for a known Event."
    )


class EventResolutionOutput(AgentOutput):
    events: list[ProposedEvent] = Field(default_factory=list)
    unassigned_claim_ids: list[str] = Field(
        default_factory=list,
        description="Claims that describe no discrete occurrence (context, background).",
    )


class EventSignificanceInput(AgentInput):
    event_id: str
    title: str
    description: str
    event_type: EventType
    timestamp: datetime
    independent_source_count: int = Field(ge=1)
    related_process_summaries: list[str] = Field(
        default_factory=list, description="Short descriptions of potentially affected Processes."
    )


class EventSignificanceOutput(AgentOutput):
    """Decides whether an Event warrants propagation (agent doc §5.2).

    This is the gate that keeps updates staged and triggered rather than
    synchronous (ontology §46): most Events should not move the graph.

    Note the deliberate absence of any return or direction field: §5.2 forbids
    predicting asset returns here. ``asset_relevance`` says only whether an
    Asset is implicated, never how it would move.
    """

    novelty: ScoredJudgement
    economic_materiality: ScoredJudgement
    credibility: ScoredJudgement
    persistence_potential: ScoredJudgement
    process_relevance: ScoredJudgement
    asset_relevance: ScoredJudgement
    should_trigger_update: bool
    trigger_rationale: str = Field(min_length=1)
