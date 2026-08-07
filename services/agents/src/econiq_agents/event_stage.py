"""The Claims → Events stage (issue #7).

::

    unclustered Claims
      → deterministic candidate retrieval (pgvector + time window)
      → Event Resolution agent
      → Events, with source independence computed in code
      → Event Significance agent
      → PropagationPolicy decides what reaches the Process layer

Retrieval before judgement, and policy after it. The agent's job is the middle
step — deciding which Claims describe the same occurrence — and nothing else.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from econiq_data_models import Claim, Document, EmbeddingKind, Event, EventClaim
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import EntityMention
from econiq_schemas import (
    ClaimForResolution,
    EventResolutionInput,
    EventSignificanceInput,
    KnownEvent,
    ProposedEvent,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.embeddings import Embedder, EmbeddingStore, HashingEmbedder
from econiq_agents.event_agents import (
    EventResolutionAgent,
    EventSignificanceAgent,
    PropagationDecision,
    PropagationPolicy,
)
from econiq_agents.event_persistence import EventWriter, PersistedEvent
from econiq_agents.independence import assess_independence
from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.prompts import EVENT_RESOLUTION_V1, EVENT_SIGNIFICANCE_V1

logger = logging.getLogger("econiq.agents.events")

#: How far back to look for Events a new cluster might belong to. Reporting on
#: one occurrence trails it by days, not months, and a wider window mostly adds
#: candidates the agent has to reject.
DEFAULT_MERGE_WINDOW = timedelta(days=14)

#: Placeholder novelty/materiality for an Event whose significance run failed.
#: Mid-scale rather than zero: an unscored Event is unknown, not unimportant.
UNSCORED = 5.0


@dataclass(frozen=True, slots=True)
class ResolvedEvent:
    persisted: PersistedEvent
    proposed: ProposedEvent
    decision: PropagationDecision | None = None
    significance_run_id: uuid.UUID | None = None

    @property
    def propagated(self) -> bool:
        return self.decision is not None and self.decision.propagate


@dataclass(frozen=True, slots=True)
class EventResolutionOutcome:
    events: list[ResolvedEvent] = field(default_factory=list)
    unassigned_claim_ids: list[str] = field(default_factory=list)
    resolution_run_id: uuid.UUID | None = None
    skipped_reason: str | None = None

    @property
    def duplicate_suppression(self) -> int:
        """Documents that added no independent source.

        The headline deduplication metric of issue #7: how much repetition the
        Event layer absorbed instead of passing downstream as evidence.
        """
        return sum(event.persisted.suppressed_duplicates for event in self.events)

    @property
    def propagated(self) -> list[ResolvedEvent]:
        return [event for event in self.events if event.propagated]


class EventResolutionStage:
    """Turns accumulated Claims into canonical Events."""

    def __init__(
        self,
        service: LLMService,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedder: Embedder | None = None,
        policy: PropagationPolicy | None = None,
        merge_window: timedelta = DEFAULT_MERGE_WINDOW,
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.embeddings = EmbeddingStore(session_factory, embedder or HashingEmbedder())
        self.policy = policy or PropagationPolicy()
        self.merge_window = merge_window
        self.resolver = EventResolutionAgent(service)
        self.significance = EventSignificanceAgent(service)
        self.writer = EventWriter(session_factory)
        self.runs = AgentRunRecorder(session_factory)

    async def run(
        self, *, as_of: datetime | None = None, limit: int = 50
    ) -> EventResolutionOutcome:
        as_of = as_of or datetime.now(UTC)
        claims = await self._unclustered_claims(as_of, limit)
        if not claims:
            return EventResolutionOutcome(skipped_reason="no unclustered claims")

        known = await self._candidate_events(claims, as_of)
        payload = EventResolutionInput(as_of=as_of, claims=claims, known_events=known)

        try:
            resolution = await self.resolver.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("event resolution failed: %s", exc)
            return EventResolutionOutcome(skipped_reason=str(exc))

        resolution_run_id = await self.runs.record(
            resolution,
            payload=payload,
            prompt=EVENT_RESOLUTION_V1,
            ontology_layer=self.resolver.ontology_layer,
            provider=self.service.provider.name,
        )

        resolved: list[ResolvedEvent] = []
        for proposed in resolution.output.events:
            resolved.append(
                await self._resolve_one(
                    proposed, payload, as_of=as_of, resolution_run_id=resolution_run_id
                )
            )

        return EventResolutionOutcome(
            events=resolved,
            unassigned_claim_ids=list(resolution.output.unassigned_claim_ids),
            resolution_run_id=resolution_run_id,
        )

    @staticmethod
    def _embedding_text(proposed: ProposedEvent, payload: EventResolutionInput) -> str:
        """What an Event is embedded as.

        The canonical title and description are a summary in the agent's words;
        later reporting will be phrased like the *Claims*, not like the summary.
        Including the supporting Claim text is what makes a second wave of
        coverage retrieve the Event it belongs to.
        """
        by_id = {claim.claim_id: claim.text for claim in payload.claims}
        supporting = [
            by_id[claim_id] for claim_id in proposed.supporting_claim_ids if claim_id in by_id
        ]
        return "\n".join([proposed.canonical_title, proposed.description, *supporting])

    async def _resolve_one(
        self,
        proposed: ProposedEvent,
        payload: EventResolutionInput,
        *,
        as_of: datetime,
        resolution_run_id: uuid.UUID,
    ) -> ResolvedEvent:
        """Score, persist and gate one cluster.

        Significance runs first so the scores land on the revision they
        describe. The identity is minted here for exactly that reason — the
        significance agent needs something to refer to before the row exists.
        """
        event_id = (
            uuid.UUID(proposed.merge_into_event_id)
            if proposed.merge_into_event_id
            else uuid.uuid4()
        )
        sources = await self._independent_source_estimate(proposed)

        significance_payload = EventSignificanceInput(
            as_of=as_of,
            event_id=str(event_id),
            title=proposed.canonical_title,
            description=proposed.description,
            event_type=proposed.event_type,
            timestamp=proposed.timestamp,
            independent_source_count=max(sources, 1),
        )
        significance = None
        significance_run_id: uuid.UUID | None = None
        try:
            significance = await self.significance.run(significance_payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("significance scoring failed for %s: %s", event_id, exc)

        if significance is not None:
            significance_run_id = await self.runs.record(
                significance,
                payload=significance_payload,
                prompt=EVENT_SIGNIFICANCE_V1,
                ontology_layer=self.significance.ontology_layer,
                provider=self.service.provider.name,
            )

        persisted = await self.writer.persist(
            proposed,
            agent_run_id=resolution_run_id,
            event_id=event_id,
            novelty=(significance.output.novelty.value if significance is not None else UNSCORED),
            materiality=(
                significance.output.economic_materiality.value
                if significance is not None
                else UNSCORED
            ),
        )
        await self.embeddings.upsert(
            persisted.event_id,
            EmbeddingKind.EVENT_DESCRIPTION,
            self._embedding_text(proposed, payload),
        )

        if significance is None:
            return ResolvedEvent(persisted=persisted, proposed=proposed, significance_run_id=None)

        decision = self.policy.decide(
            significance.output,
            independent_source_count=persisted.independence.independent_source_count,
        )
        if decision.propagate:
            await self.writer.mark_propagated(persisted.event_id)
        else:
            logger.info("holding event %s: %s", persisted.event_id, decision.reason)

        return ResolvedEvent(
            persisted=persisted,
            proposed=proposed,
            decision=decision,
            significance_run_id=significance_run_id,
        )

    async def _independent_source_estimate(self, proposed: ProposedEvent) -> int:
        """Independent sources behind a cluster, before it is written.

        The significance agent is told how well corroborated an Event is, so the
        count has to exist before the row does. ``EventWriter`` recomputes it
        over the persisted cluster; this is the same computation on the same
        documents.
        """
        claim_ids = [uuid.UUID(cid) for cid in proposed.supporting_claim_ids]
        async with self.session_factory() as session:
            documents = await self.writer._source_documents(session, claim_ids)
        return assess_independence(documents).independent_source_count

    async def _unclustered_claims(self, as_of: datetime, limit: int) -> list[ClaimForResolution]:
        """Claims not yet part of any Event, oldest first.

        Only claims published at or before ``as_of`` are considered: an
        as-of-date run must not see evidence that did not exist yet
        (ontology §33).
        """
        assigned = select(EventClaim.claim_id).where(EventClaim.removed_at.is_(None))
        query = (
            select(
                Claim.claim_id,
                Claim.text,
                Claim.document_id,
                Claim.entities,
                Document.publisher,
                Document.publication_time,
            )
            .join(Document, Document.document_id == Claim.document_id)
            .where(Claim.claim_id.notin_(assigned), Document.publication_time <= as_of)
            .order_by(Document.publication_time)
            .limit(limit)
        )
        async with self.session_factory() as session:
            rows = (await session.execute(query)).all()

        return [
            ClaimForResolution(
                claim_id=str(row.claim_id),
                text=row.text,
                document_id=str(row.document_id),
                publisher=row.publisher,
                publication_time=row.publication_time,
                entities=[EntityMention.model_validate(e) for e in (row.entities or [])],
            )
            for row in rows
        ]

    async def _candidate_events(
        self, claims: list[ClaimForResolution], as_of: datetime
    ) -> list[KnownEvent]:
        """Existing Events a cluster might extend.

        Vector search narrows by meaning, the time window narrows by plausibility,
        and only what survives both is put in front of the agent. Showing it the
        whole Event table would be slower, costlier and less accurate.
        """
        vectors = self.embeddings.embedder.embed([claim.text for claim in claims])
        candidate_ids: dict[uuid.UUID, float] = {}
        for vector in vectors:
            for node_id, distance in await self.embeddings.nearest(
                vector, EmbeddingKind.EVENT_DESCRIPTION, limit=5
            ):
                candidate_ids[node_id] = min(distance, candidate_ids.get(node_id, 1.0))

        if not candidate_ids:
            return []

        earliest = min(claim.publication_time for claim in claims) - self.merge_window
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Event)
                    .where(
                        Event.event_id.in_(list(candidate_ids)),
                        Event.valid_to.is_(None),
                        Event.occurred_at >= earliest,
                        Event.occurred_at <= as_of,
                    )
                    .order_by(Event.occurred_at.desc())
                )
            ).scalars()
            events = list(rows)

        events.sort(key=lambda event: candidate_ids[event.event_id])
        return [
            KnownEvent(
                event_id=str(event.event_id),
                title=event.title,
                event_type=event.event_type,
                timestamp=event.occurred_at,
            )
            for event in events
        ]
