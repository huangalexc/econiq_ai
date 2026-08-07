"""Typed domain events and the transactional outbox (tech rec §11).

An event is written in the same transaction as the state change that produced
it. Writing to a queue and to Postgres separately means one can succeed while
the other fails, and the gap is invisible in both directions: an Event nothing
acts on, or work scheduled for a state change that rolled back. Here the event
is a row in the same commit, and a dispatcher moves it outward afterwards.

The names are the ones tech rec §11 lists. They are the pipeline's vocabulary
for "something happened that something else may care about" — deliberately
descriptive of the past rather than imperative, so a publisher never has to know
who is listening.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from econiq_data_models import OutboxEvent, OutboxStatus
from econiq_ontology import EntityType, utcnow
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class DomainEvent(StrEnum):
    """What happened. Past tense, no instruction implied."""

    DOCUMENT_INGESTED = "document.ingested"
    CLAIMS_EXTRACTED = "claims.extracted"
    EVENT_CREATED = "event.created"
    EVENT_UPDATED = "event.updated"
    EVENT_PROPAGATED = "event.propagated"
    """Cleared the significance gate — the trigger for Process work."""

    PROCESS_CREATED = "process.created"
    PROCESS_UPDATED = "process.updated"
    STATE_TRANSITION_CANDIDATE = "state.transition_candidate"
    STATE_RECORDED = "state.recorded"
    BOTTLENECK_UPDATED = "bottleneck.updated"
    CAPABILITY_UPDATED = "capability.updated"
    ASSET_UPDATED = "asset.updated"
    THESIS_CRITIQUED = "thesis.critiqued"


@dataclass(frozen=True, slots=True)
class Emitted:
    """An event to be written alongside a state change."""

    name: DomainEvent
    subject_id: uuid.UUID | None = None
    subject_type: EntityType | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredEvent:
    outbox_event_id: uuid.UUID
    name: DomainEvent
    subject_id: uuid.UUID | None
    subject_type: EntityType | None
    payload: dict[str, Any]
    occurred_at: datetime


class Outbox:
    """Writes and drains domain events."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    def stage(self, session: AsyncSession, *events: Emitted) -> list[uuid.UUID]:
        """Add events to an *open* session.

        Takes the caller's session rather than opening its own: that is the
        whole point of an outbox. If the surrounding transaction rolls back, so
        does the event.
        """
        ids: list[uuid.UUID] = []
        for event in events:
            event_id = uuid.uuid4()
            ids.append(event_id)
            session.add(
                OutboxEvent(
                    outbox_event_id=event_id,
                    event_name=event.name.value,
                    subject_id=event.subject_id,
                    subject_type=event.subject_type,
                    payload=event.payload,
                    occurred_at=event.occurred_at or utcnow(),
                    status=OutboxStatus.PENDING,
                )
            )
        return ids

    async def publish(self, *events: Emitted) -> list[uuid.UUID]:
        """Write events in their own transaction.

        For callers whose state change already committed. Weaker than
        :meth:`stage` — there is a window in which the state exists and the
        event does not — which the reconciler exists to close.
        """
        async with self.session_factory() as session:
            ids = self.stage(session, *events)
            await session.commit()
        return ids

    async def pending(self, *, limit: int = 100) -> list[StoredEvent]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OutboxEvent)
                        .where(OutboxEvent.status == OutboxStatus.PENDING)
                        .order_by(OutboxEvent.occurred_at)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredEvent(
                outbox_event_id=row.outbox_event_id,
                name=DomainEvent(row.event_name),
                subject_id=row.subject_id,
                subject_type=row.subject_type,
                payload=row.payload,
                occurred_at=row.occurred_at,
            )
            for row in rows
        ]

    async def mark_dispatched(self, event_ids: Sequence[uuid.UUID]) -> None:
        if not event_ids:
            return
        async with self.session_factory() as session:
            await session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.outbox_event_id.in_(list(event_ids)))
                .values(status=OutboxStatus.DISPATCHED, dispatched_at=utcnow())
            )
            await session.commit()
