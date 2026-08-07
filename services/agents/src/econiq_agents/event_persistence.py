"""Writing Events into the system of record.

Events are revisable, so accumulating evidence writes a *new revision* rather
than mutating the old one: the previous revision keeps its ``valid_to`` and its
independent-source count, and "what did we believe about this Event on July 14?"
stays answerable (ui_concept §32).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from econiq_data_models import Claim, Document, Event, EventClaim, Node
from econiq_ontology import EntityType, EpistemicStatus, utcnow
from econiq_schemas import ProposedEvent
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.independence import IndependenceAssessment, SourceDocument, assess_independence


@dataclass(frozen=True, slots=True)
class PersistedEvent:
    event_id: uuid.UUID
    revision: int
    created: bool
    """False when this revision extended an existing Event."""

    independence: IndependenceAssessment = field(
        default_factory=lambda: IndependenceAssessment(independent_source_count=0)
    )
    claim_ids: tuple[uuid.UUID, ...] = ()

    @property
    def suppressed_duplicates(self) -> int:
        return self.independence.suppressed


class EventWriter:
    """Persists clusters as Events, with source independence computed here."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def persist(
        self,
        proposed: ProposedEvent,
        *,
        agent_run_id: uuid.UUID,
        novelty: float,
        materiality: float,
        event_id: uuid.UUID | None = None,
    ) -> PersistedEvent:
        """Write the cluster as an Event revision.

        ``event_id`` is supplied by the caller so that significance scoring can
        run against the same identity *before* the row is written: novelty and
        materiality belong on the revision they describe, not on a later
        in-place update of it.
        """
        claim_ids = [uuid.UUID(cid) for cid in proposed.supporting_claim_ids]

        async with self.session_factory() as session:
            documents = await self._source_documents(session, claim_ids)

        existing_id = (
            uuid.UUID(proposed.merge_into_event_id) if proposed.merge_into_event_id else None
        )
        if existing_id is not None:
            return await self._extend(
                existing_id,
                proposed,
                claim_ids,
                documents,
                agent_run_id=agent_run_id,
                novelty=novelty,
                materiality=materiality,
            )
        return await self._create(
            proposed,
            claim_ids,
            documents,
            agent_run_id=agent_run_id,
            novelty=novelty,
            materiality=materiality,
            event_id=event_id or uuid.uuid4(),
        )

    async def _create(
        self,
        proposed: ProposedEvent,
        claim_ids: list[uuid.UUID],
        documents: list[SourceDocument],
        *,
        agent_run_id: uuid.UUID,
        novelty: float,
        materiality: float,
        event_id: uuid.UUID,
    ) -> PersistedEvent:
        independence = assess_independence(documents)

        async with self.session_factory() as session:
            session.add(Node(node_id=event_id, node_type=EntityType.EVENT))
            await session.flush()
            session.add(
                self._row(
                    event_id=event_id,
                    revision=1,
                    proposed=proposed,
                    independence=independence,
                    agent_run_id=agent_run_id,
                    novelty=novelty,
                    materiality=materiality,
                )
            )
            for claim_id in claim_ids:
                session.add(
                    EventClaim(event_id=event_id, claim_id=claim_id, agent_run_id=agent_run_id)
                )
            await session.commit()

        return PersistedEvent(
            event_id=event_id,
            revision=1,
            created=True,
            independence=independence,
            claim_ids=tuple(claim_ids),
        )

    async def _extend(
        self,
        event_id: uuid.UUID,
        proposed: ProposedEvent,
        claim_ids: list[uuid.UUID],
        documents: list[SourceDocument],
        *,
        agent_run_id: uuid.UUID,
        novelty: float,
        materiality: float,
    ) -> PersistedEvent:
        async with self.session_factory() as session:
            current = await self._current_revision(session, event_id)
            if current is None:
                raise LookupError(f"cannot extend unknown event {event_id}")

            existing_claim_ids = await self._claim_ids(session, event_id)
            new_claim_ids = [cid for cid in claim_ids if cid not in existing_claim_ids]
            all_claim_ids = list(existing_claim_ids) + new_claim_ids

            # Independence is recomputed over the whole cluster, not incremented:
            # a new document may be syndication of one already counted.
            all_documents = await self._source_documents(session, all_claim_ids)
            independence = assess_independence(all_documents)

            closed_at = utcnow()
            await session.execute(
                update(Event)
                .where(Event.event_id == event_id, Event.valid_to.is_(None))
                .values(valid_to=closed_at)
            )
            revision = current.revision + 1
            session.add(
                self._row(
                    event_id=event_id,
                    revision=revision,
                    proposed=proposed,
                    independence=independence,
                    agent_run_id=agent_run_id,
                    novelty=novelty,
                    materiality=materiality,
                    valid_from=closed_at,
                )
            )
            for claim_id in new_claim_ids:
                session.add(
                    EventClaim(event_id=event_id, claim_id=claim_id, agent_run_id=agent_run_id)
                )
            await session.commit()

        return PersistedEvent(
            event_id=event_id,
            revision=revision,
            created=False,
            independence=independence,
            claim_ids=tuple(all_claim_ids),
        )

    @staticmethod
    def _row(
        *,
        event_id: uuid.UUID,
        revision: int,
        proposed: ProposedEvent,
        independence: IndependenceAssessment,
        agent_run_id: uuid.UUID,
        novelty: float,
        materiality: float,
        valid_from: datetime | None = None,
    ) -> Event:
        row = Event(
            event_id=event_id,
            revision=revision,
            event_type=proposed.event_type,
            title=proposed.canonical_title,
            description=proposed.description,
            occurred_at=proposed.timestamp,
            entities=[entity.model_dump(mode="json") for entity in proposed.entities],
            independent_source_count=max(independence.independent_source_count, 1),
            novelty=novelty,
            materiality=materiality,
            confidence=proposed.confidence,
            # An Event inferred from reporting is observed, not hypothesized;
            # the Claims' own epistemic types carry the finer distinction.
            epistemic_status=EpistemicStatus.OBSERVED,
            contradictions=list(proposed.contradictions),
            agent_run_id=agent_run_id,
        )
        if valid_from is not None:
            row.valid_from = valid_from
        return row

    async def mark_propagated(self, event_id: uuid.UUID, at: datetime | None = None) -> None:
        """Record that the current revision has been handed downstream."""
        async with self.session_factory() as session:
            await session.execute(
                update(Event)
                .where(Event.event_id == event_id, Event.valid_to.is_(None))
                .values(propagated_at=at or utcnow())
            )
            await session.commit()

    async def _current_revision(self, session: AsyncSession, event_id: uuid.UUID) -> Event | None:
        result = await session.execute(
            select(Event).where(Event.event_id == event_id, Event.valid_to.is_(None))
        )
        return result.scalar_one_or_none()

    async def _claim_ids(self, session: AsyncSession, event_id: uuid.UUID) -> set[uuid.UUID]:
        result = await session.execute(
            select(EventClaim.claim_id).where(
                EventClaim.event_id == event_id, EventClaim.removed_at.is_(None)
            )
        )
        return set(result.scalars().all())

    async def _source_documents(
        self, session: AsyncSession, claim_ids: list[uuid.UUID]
    ) -> list[SourceDocument]:
        """The documents behind a set of Claims, deduplicated by document.

        Independence is a property of documents, not Claims: three Claims
        extracted from one article are one source.
        """
        if not claim_ids:
            return []
        result = await session.execute(
            select(Document.document_id, Document.publisher, Document.raw_content, Document.title)
            .join(Claim, Claim.document_id == Document.document_id)
            .where(Claim.claim_id.in_(claim_ids))
            .distinct()
        )
        return [
            SourceDocument(
                document_id=str(row.document_id),
                publisher=row.publisher,
                text=row.raw_content or row.title,
            )
            for row in result.all()
        ]
