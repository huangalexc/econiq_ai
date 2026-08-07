"""The Event → Process stage (issue #8).

Runs on Events the propagation gate released (issue #7), not on every Event.
That is the staged architecture of ontology §46 working as intended: the Event
layer absorbs the noise, and only what survives it costs a reasoning-tier call
here.

::

    propagated Events
      → candidate Processes (pgvector + active graph)
      → Process Discovery agent
      → new Processes (review-flagged) and evidenced edges
      → Process Update agent, for the ones materially changed
      → new revisions + journal entries
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from econiq_data_models import Claim, EmbeddingKind, Event, EventClaim, Process
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import ProcessStatus, RelationshipType
from econiq_schemas import (
    EventSummary,
    ProcessAffected,
    ProcessDiscoveryInput,
    ProcessImplication,
    ProcessSummary,
    ProcessUpdateInput,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.embeddings import Embedder, EmbeddingStore, HashingEmbedder
from econiq_agents.graph_writer import GraphWriter, IllegalEdgeError
from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.process_agents import ProcessDiscoveryAgent, ProcessUpdateAgent
from econiq_agents.process_persistence import AppliedUpdate, PersistedProcess, ProcessWriter
from econiq_agents.prompts import PROCESS_DISCOVERY_V1, PROCESS_UPDATE_V1

logger = logging.getLogger("econiq.agents.processes")

#: How many existing Processes to put in front of the discovery agent. The graph
#: will not stay small; showing all of it would blow the context and bury the
#: relevant few.
MAX_CANDIDATE_PROCESSES = 25


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    event_id: uuid.UUID
    created: list[PersistedProcess] = field(default_factory=list)
    updated: list[AppliedUpdate] = field(default_factory=list)
    evidenced: list[uuid.UUID] = field(default_factory=list)
    """Processes the Event corroborated without changing."""

    discovery_run_id: uuid.UUID | None = None
    skipped_reason: str | None = None

    @property
    def needs_state_review(self) -> list[uuid.UUID]:
        """Processes whose State the update agent thinks may have moved.

        Consumed by the Process State agent (#9). Carried rather than acted on:
        the State layer has one owner.
        """
        return [
            update.process_id
            for update in self.updated
            if update.state_change_recommended or update.feature_deltas
        ]


class ProcessDiscoveryStage:
    """Turns propagated Events into Process graph changes."""

    def __init__(
        self,
        service: LLMService,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.embeddings = EmbeddingStore(session_factory, embedder or HashingEmbedder())
        self.discovery = ProcessDiscoveryAgent(service)
        self.updater = ProcessUpdateAgent(service)
        self.writer = ProcessWriter(session_factory)
        self.graph = GraphWriter(session_factory)
        self.runs = AgentRunRecorder(session_factory)

    async def run_pending(self, *, limit: int = 10) -> list[ProcessOutcome]:
        """Process every Event released by the propagation gate."""
        outcomes: list[ProcessOutcome] = []
        for event_id in await self._pending_event_ids(limit):
            outcomes.append(await self.run(event_id))
        return outcomes

    async def run(self, event_id: uuid.UUID) -> ProcessOutcome:
        event, claim_texts = await self._load_event(event_id)
        if event is None:
            return ProcessOutcome(event_id=event_id, skipped_reason="event not found")

        candidates = await self._candidate_processes(event)
        payload = ProcessDiscoveryInput(
            as_of=event.occurred_at,
            event=EventSummary(
                event_id=str(event_id),
                title=event.title,
                description=event.description,
                timestamp=event.occurred_at,
                materiality=event.materiality,
                novelty=event.novelty,
                supporting_claim_ids=list(claim_texts),
            ),
            claim_texts=claim_texts,
            existing_processes=candidates,
        )

        try:
            discovery = await self.discovery.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("process discovery failed for event %s: %s", event_id, exc)
            return ProcessOutcome(event_id=event_id, skipped_reason=str(exc))

        discovery_run_id = await self.runs.record(
            discovery,
            payload=payload,
            prompt=PROCESS_DISCOVERY_V1,
            ontology_layer=self.discovery.ontology_layer,
            provider=self.service.provider.name,
            trigger_event_id=event_id,
        )

        created: list[PersistedProcess] = []
        for proposal in discovery.output.new_processes:
            persisted = await self.writer.create(
                proposal,
                agent_run_id=discovery_run_id,
                observed_at=event.occurred_at,
                triggering_event_id=event_id,
            )
            created.append(persisted)
            await self.embeddings.upsert(
                persisted.process_id,
                EmbeddingKind.PROCESS_DESCRIPTION,
                f"{proposal.name}\n{proposal.description}",
            )
            await self._link(
                event_id,
                persisted.process_id,
                RelationshipType.AFFECTS,
                confidence=proposal.confidence,
                rationale=proposal.causal_mechanism,
                agent_run_id=discovery_run_id,
            )
            # The Event that gave rise to a Process is its first evidence. Only
            # recording the edge would leave the Process looking unevidenced to
            # every accumulation query that follows.
            await self.graph.add_evidence(
                subject_id=persisted.process_id,
                evidence_id=event_id,
                supports=True,
                agent_run_id=discovery_run_id,
                weight=proposal.confidence,
                note=proposal.causal_mechanism,
            )

        updated: list[AppliedUpdate] = []
        evidenced: list[uuid.UUID] = []
        for affected in discovery.output.affected_processes:
            process_id = uuid.UUID(affected.process_id)
            await self._link(
                event_id,
                process_id,
                RelationshipType.AFFECTS,
                confidence=affected.confidence,
                rationale=affected.causal_mechanism,
                agent_run_id=discovery_run_id,
            )
            await self.graph.add_evidence(
                subject_id=process_id,
                evidence_id=event_id,
                supports=True,
                agent_run_id=discovery_run_id,
                weight=affected.confidence,
                note=affected.causal_mechanism,
            )
            if affected.implication is ProcessImplication.MATERIALLY_CHANGES:
                applied = await self._update(
                    process_id, affected, event, claim_texts, event_id=event_id
                )
                if applied is not None:
                    updated.append(applied)
            elif affected.implication is ProcessImplication.PROVIDES_EVIDENCE:
                evidenced.append(process_id)

        return ProcessOutcome(
            event_id=event_id,
            created=created,
            updated=updated,
            evidenced=evidenced,
            discovery_run_id=discovery_run_id,
        )

    async def _update(
        self,
        process_id: uuid.UUID,
        affected: ProcessAffected,
        event: Event,
        claim_texts: dict[str, str],
        *,
        event_id: uuid.UUID,
    ) -> AppliedUpdate | None:
        summary = await self._process_summary(process_id)
        if summary is None:
            logger.warning("discovery named unknown process %s", process_id)
            return None

        payload = ProcessUpdateInput(
            as_of=event.occurred_at,
            process=summary,
            event=EventSummary(
                event_id=str(event_id),
                title=event.title,
                description=event.description,
                timestamp=event.occurred_at,
                materiality=event.materiality,
                novelty=event.novelty,
                supporting_claim_ids=list(claim_texts),
            ),
            claim_texts=claim_texts,
        )
        try:
            update = await self.updater.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("process update failed for %s: %s", process_id, exc)
            return None

        run_id = await self.runs.record(
            update,
            payload=payload,
            prompt=PROCESS_UPDATE_V1,
            ontology_layer=self.updater.ontology_layer,
            provider=self.service.provider.name,
            trigger_event_id=event_id,
        )
        return await self.writer.apply_update(
            process_id,
            update.output,
            agent_run_id=run_id,
            observed_at=event.occurred_at,
            triggering_event_id=event_id,
        )

    async def _link(
        self,
        event_id: uuid.UUID,
        process_id: uuid.UUID,
        relationship_type: RelationshipType,
        *,
        confidence: float,
        rationale: str,
        agent_run_id: uuid.UUID,
    ) -> None:
        try:
            await self.graph.relate(
                source_id=event_id,
                target_id=process_id,
                relationship_type=relationship_type,
                confidence=confidence,
                rationale=rationale,
                agent_run_id=agent_run_id,
            )
        except IllegalEdgeError:
            # The edge is refused, the run keeps its record, and the failure is
            # loud in the log rather than silently corrupting the graph.
            logger.exception("refused an illegal edge from event %s", event_id)

    async def _pending_event_ids(self, limit: int) -> list[uuid.UUID]:
        """Propagated Events that discovery has not seen yet.

        Keyed on the agent-run log rather than a flag column: the record of what
        ran already exists, and a second source of truth would drift from it.
        """
        from econiq_data_models import AgentRun

        seen = select(AgentRun.trigger_event_id).where(
            AgentRun.agent_name == "process_discovery",
            AgentRun.trigger_event_id.is_not(None),
        )
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Event.event_id)
                    .where(
                        Event.valid_to.is_(None),
                        Event.propagated_at.is_not(None),
                        Event.event_id.notin_(seen),
                    )
                    .order_by(Event.occurred_at)
                    .limit(limit)
                )
            ).scalars()
            return list(rows)

    async def _load_event(self, event_id: uuid.UUID) -> tuple[Event | None, dict[str, str]]:
        async with self.session_factory() as session:
            event = (
                await session.execute(
                    select(Event).where(Event.event_id == event_id, Event.valid_to.is_(None))
                )
            ).scalar_one_or_none()
            if event is None:
                return None, {}
            rows = (
                await session.execute(
                    select(Claim.claim_id, Claim.text)
                    .join(EventClaim, EventClaim.claim_id == Claim.claim_id)
                    .where(EventClaim.event_id == event_id, EventClaim.removed_at.is_(None))
                )
            ).all()
        return event, {str(row.claim_id): row.text for row in rows}

    async def _candidate_processes(self, event: Event) -> list[ProcessSummary]:
        """Which existing Processes to show the agent.

        Semantically near ones first, then the rest of the active graph up to a
        cap. Both matter: retrieval finds the obvious match, and the tail is what
        stops the agent creating a duplicate of something it was never shown.
        """
        vector = self.embeddings.embedder.embed([f"{event.title}\n{event.description}"])[0]
        nearest = await self.embeddings.nearest(
            vector, EmbeddingKind.PROCESS_DESCRIPTION, limit=MAX_CANDIDATE_PROCESSES
        )
        ranked = {node_id: distance for node_id, distance in nearest}

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Process).where(
                        Process.valid_to.is_(None),
                        Process.status.in_(
                            [ProcessStatus.ACTIVE, ProcessStatus.CANDIDATE, ProcessStatus.DORMANT]
                        ),
                    )
                )
            ).scalars()
            processes = list(rows)

        processes.sort(key=lambda p: ranked.get(p.process_id, 1.0))
        return [
            ProcessSummary(
                process_id=str(process.process_id),
                name=process.name,
                description=process.description,
                archetype=process.archetype,
            )
            for process in processes[:MAX_CANDIDATE_PROCESSES]
        ]

    async def _process_summary(self, process_id: uuid.UUID) -> ProcessSummary | None:
        async with self.session_factory() as session:
            process = await self._current(session, process_id)
        if process is None:
            return None
        return ProcessSummary(
            process_id=str(process_id),
            name=process.name,
            description=process.description,
            archetype=process.archetype,
        )

    async def _current(self, session: AsyncSession, process_id: uuid.UUID) -> Process | None:
        result = await session.execute(
            select(Process).where(Process.process_id == process_id, Process.valid_to.is_(None))
        )
        return result.scalar_one_or_none()


def now() -> datetime:
    return datetime.now(UTC)
