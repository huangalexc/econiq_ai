"""The work queue (issue #14).

Postgres is the queue, claimed with ``SELECT … FOR UPDATE SKIP LOCKED``. At the
volumes this system will see — a few thousand agent calls a day — orchestration
throughput is not close to being the constraint; LLM spend is. A broker would
add an operational dependency and a second place for state to live, in exchange
for headroom nothing needs. ``docs/orchestration.md`` records what would have to
change for that to stop being true.

Three properties are load-bearing:

**Idempotency.** Both the event path and the reconciler enqueue work. A partial
unique index over open items means the second one is a no-op rather than a
duplicate agent run — which matters because agent runs cost money.

**Visible failure.** Retries back off, and an item that exhausts them becomes
``dead`` rather than disappearing. Work that vanished silently is indistinguishable
from work that was never needed.

**Priority.** Live material evidence should not queue behind a historical
backfill, so priority is a column and the claim query orders by it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from econiq_data_models import WorkItem, WorkStatus
from econiq_ontology import utcnow
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class Priority:
    """Lower runs first.

    The ordering that matters: a material Event that just cleared the gate
    should reach the Process layer before a reconciler sweep or a backfill.
    """

    URGENT = 10
    LIVE = 50
    DEFAULT = 100
    RECONCILED = 150
    BACKFILL = 500


class Trigger:
    """How a unit of work came to be scheduled (agent doc §13 trigger types)."""

    EVENT = "event"
    """A domain event fired — delta-triggered."""

    RECONCILER = "reconciler"
    """A sweep found work the event path missed."""

    SCHEDULE = "schedule"
    """Time-based, for accumulation windows."""

    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Enqueued:
    work_item_id: uuid.UUID | None
    created: bool
    """False when an open item with the same key already existed."""


@dataclass(frozen=True, slots=True)
class ClaimedWork:
    work_item_id: uuid.UUID
    stage: str
    subject_id: uuid.UUID | None
    payload: dict[str, object]
    attempts: int
    max_attempts: int
    trigger: str

    @property
    def is_final_attempt(self) -> bool:
        return self.attempts >= self.max_attempts


@dataclass(frozen=True, slots=True)
class QueueDepth:
    pending: int = 0
    running: int = 0
    failed: int = 0
    dead: int = 0

    @property
    def outstanding(self) -> int:
        return self.pending + self.running + self.failed


#: How long a claimed item may run before another worker may take it. A
#: reasoning-tier call at high effort can legitimately take minutes, so this is
#: generous — reclaiming live work is worse than waiting for a dead worker.
DEFAULT_LEASE = timedelta(minutes=30)

#: Retry backoff, in seconds, indexed by attempt number.
_BACKOFF = (30, 300, 1800)


def backoff_for(attempt: int) -> timedelta:
    index = min(max(attempt - 1, 0), len(_BACKOFF) - 1)
    return timedelta(seconds=_BACKOFF[index])


class WorkQueue:
    """Durable, idempotent, priority-ordered work over Postgres."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease: timedelta = DEFAULT_LEASE,
    ) -> None:
        self.session_factory = session_factory
        self.lease = lease

    async def enqueue(
        self,
        stage: str,
        *,
        idempotency_key: str,
        subject_id: uuid.UUID | None = None,
        payload: dict[str, object] | None = None,
        priority: int = Priority.DEFAULT,
        run_after: datetime | None = None,
        max_attempts: int = 3,
        trigger: str = Trigger.EVENT,
        source_event_id: uuid.UUID | None = None,
    ) -> Enqueued:
        """Schedule work, unless the same work is already open.

        The dedup is by ``idempotency_key`` over pending and running items only:
        a completed item stays for audit, so the same stage can legitimately run
        again later when new evidence arrives.
        """
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(WorkItem.work_item_id).where(
                        WorkItem.idempotency_key == idempotency_key,
                        WorkItem.status.in_([WorkStatus.PENDING, WorkStatus.RUNNING]),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return Enqueued(work_item_id=existing, created=False)

            work_item_id = uuid.uuid4()
            session.add(
                WorkItem(
                    work_item_id=work_item_id,
                    stage=stage,
                    subject_id=subject_id,
                    idempotency_key=idempotency_key,
                    payload=payload or {},
                    status=WorkStatus.PENDING,
                    priority=priority,
                    run_after=run_after or utcnow(),
                    max_attempts=max_attempts,
                    trigger=trigger,
                    source_event_id=source_event_id,
                )
            )
            await session.commit()
        return Enqueued(work_item_id=work_item_id, created=True)

    async def claim(
        self,
        *,
        worker: str,
        stages: Sequence[str] = (),
        limit: int = 1,
        now: datetime | None = None,
    ) -> list[ClaimedWork]:
        """Take work, skipping anything another worker holds.

        ``FOR UPDATE SKIP LOCKED`` is what makes several workers safe without a
        broker: each transaction locks the rows it takes and steps over the
        rest, so there is no contention and no double-processing.
        """
        moment = now or utcnow()
        async with self.session_factory() as session:
            await self._reclaim_expired(session, moment)

            query = (
                select(WorkItem)
                .where(
                    WorkItem.status.in_([WorkStatus.PENDING, WorkStatus.FAILED]),
                    WorkItem.run_after <= moment,
                )
                .order_by(WorkItem.priority, WorkItem.run_after)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            if stages:
                query = query.where(WorkItem.stage.in_(list(stages)))

            rows = list((await session.execute(query)).scalars().all())
            claimed: list[ClaimedWork] = []
            for row in rows:
                row.status = WorkStatus.RUNNING
                row.attempts += 1
                row.claimed_at = moment
                row.claimed_by = worker
                claimed.append(
                    ClaimedWork(
                        work_item_id=row.work_item_id,
                        stage=row.stage,
                        subject_id=row.subject_id,
                        payload=dict(row.payload),
                        attempts=row.attempts,
                        max_attempts=row.max_attempts,
                        trigger=row.trigger,
                    )
                )
            await session.commit()
        return claimed

    async def succeed(self, work_item_id: uuid.UUID) -> None:
        await self._finish(work_item_id, WorkStatus.SUCCEEDED)

    async def fail(self, work_item_id: uuid.UUID, error: str) -> WorkStatus:
        """Record a failure, retrying with backoff or dead-lettering.

        The distinction matters operationally: ``failed`` will be tried again,
        ``dead`` will not and needs a human. Neither disappears.
        """
        async with self.session_factory() as session:
            item = await session.get(WorkItem, work_item_id)
            if item is None:
                raise LookupError(f"unknown work item {work_item_id}")

            exhausted = item.attempts >= item.max_attempts
            item.status = WorkStatus.DEAD if exhausted else WorkStatus.FAILED
            item.last_error = error[:2000]
            item.claimed_by = None
            item.claimed_at = None
            if exhausted:
                item.finished_at = utcnow()
            else:
                item.run_after = utcnow() + backoff_for(item.attempts)
            status = item.status
            await session.commit()
        return status

    async def supersede(self, stage: str, idempotency_key: str) -> int:
        """Cancel open work that a newer state change has made redundant."""
        async with self.session_factory() as session:
            result = await session.execute(
                update(WorkItem)
                .where(
                    WorkItem.stage == stage,
                    WorkItem.idempotency_key == idempotency_key,
                    WorkItem.status == WorkStatus.PENDING,
                )
                .values(status=WorkStatus.SUPERSEDED, finished_at=utcnow())
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0) or 0)

    async def depth(self, stage: str | None = None) -> QueueDepth:
        query = select(WorkItem.status, func.count()).group_by(WorkItem.status)
        if stage is not None:
            query = query.where(WorkItem.stage == stage)
        async with self.session_factory() as session:
            rows = (await session.execute(query)).all()
        counts: dict[WorkStatus, int] = {row[0]: row[1] for row in rows}
        return QueueDepth(
            pending=counts.get(WorkStatus.PENDING, 0),
            running=counts.get(WorkStatus.RUNNING, 0),
            failed=counts.get(WorkStatus.FAILED, 0),
            dead=counts.get(WorkStatus.DEAD, 0),
        )

    async def dead_letters(self, *, limit: int = 50) -> list[ClaimedWork]:
        """Work that exhausted its retries. Nothing reads this but a human."""
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(WorkItem)
                        .where(WorkItem.status == WorkStatus.DEAD)
                        .order_by(WorkItem.finished_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            ClaimedWork(
                work_item_id=row.work_item_id,
                stage=row.stage,
                subject_id=row.subject_id,
                payload=dict(row.payload),
                attempts=row.attempts,
                max_attempts=row.max_attempts,
                trigger=row.trigger,
            )
            for row in rows
        ]

    async def _finish(self, work_item_id: uuid.UUID, status: WorkStatus) -> None:
        async with self.session_factory() as session:
            item = await session.get(WorkItem, work_item_id)
            if item is None:
                raise LookupError(f"unknown work item {work_item_id}")
            item.status = status
            item.finished_at = utcnow()
            item.claimed_by = None
            await session.commit()

    async def _reclaim_expired(self, session: AsyncSession, now: datetime) -> None:
        """Return work held by a worker that died to the pending pool.

        Without this a crashed worker's items stay ``running`` forever, which is
        the failure mode that makes people distrust a database-backed queue.
        """
        await session.execute(
            update(WorkItem)
            .where(
                WorkItem.status == WorkStatus.RUNNING,
                WorkItem.claimed_at.is_not(None),
                WorkItem.claimed_at < now - self.lease,
            )
            .values(status=WorkStatus.PENDING, claimed_by=None, claimed_at=None)
        )
