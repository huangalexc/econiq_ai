"""The dispatcher, the worker and the reconciler (issue #14).

Three loops, each doing one thing:

``Dispatcher`` turns domain events into scheduled work — the fast path, giving
latency between a document arriving and the graph moving.

``Worker`` claims work, runs the stage handler, and stages whatever events the
handler produced *in the same transaction as marking the work done*. That is
what stops a stage completing without its successor being scheduled.

``Reconciler`` sweeps ontology state for work the event path missed and enqueues
it at low priority. This is the correctness backstop: because every stage can
derive its own pending work from the database, a lost event costs latency and
nothing else. It is also what makes the whole design safe to run without a
broker — see ``docs/orchestration.md``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from econiq_ontology import utcnow
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_orchestration.events import Emitted, Outbox, StoredEvent
from econiq_orchestration.queue import ClaimedWork, Enqueued, Priority, Trigger, WorkQueue
from econiq_orchestration.stages import BY_NAME, PIPELINE, StageRegistry, stages_for

logger = logging.getLogger("econiq.orchestration")

#: Returns the subject ids that a stage currently has outstanding work for,
#: derived from ontology state rather than from any queue.
PendingFinder = Callable[[], Awaitable[Sequence[uuid.UUID]]]


@dataclass(frozen=True, slots=True)
class DispatchResult:
    events_processed: int = 0
    work_enqueued: int = 0
    work_deduplicated: int = 0
    """Events whose work was already queued — the idempotency key doing its job."""


@dataclass(frozen=True, slots=True)
class WorkResult:
    work_item_id: uuid.UUID
    stage: str
    ok: bool
    events_emitted: int = 0
    error: str | None = None
    dead: bool = False


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    enqueued: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.enqueued.values())


class Dispatcher:
    """Domain events → scheduled work."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.outbox = Outbox(session_factory)
        self.queue = WorkQueue(session_factory)

    async def dispatch_pending(self, *, limit: int = 100) -> DispatchResult:
        events = await self.outbox.pending(limit=limit)
        if not events:
            return DispatchResult()

        enqueued = deduplicated = 0
        for event in events:
            for result in await self._schedule(event):
                if result.created:
                    enqueued += 1
                else:
                    deduplicated += 1
        await self.outbox.mark_dispatched([e.outbox_event_id for e in events])
        return DispatchResult(
            events_processed=len(events),
            work_enqueued=enqueued,
            work_deduplicated=deduplicated,
        )

    async def _schedule(self, event: StoredEvent) -> list[Enqueued]:
        results: list[Enqueued] = []
        for stage in stages_for(event.name):
            subject = event.subject_id if stage.subject_from_payload else None
            results.append(
                await self.queue.enqueue(
                    stage.name,
                    idempotency_key=stage.key_for(subject),
                    subject_id=subject,
                    payload={"source_event": event.name.value, **event.payload},
                    priority=stage.priority,
                    max_attempts=stage.max_attempts,
                    trigger=Trigger.EVENT,
                    source_event_id=event.outbox_event_id,
                )
            )
        return results


class Worker:
    """Claims work, runs it, and schedules what follows."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: StageRegistry,
        *,
        name: str = "worker",
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.name = name
        self.queue = WorkQueue(session_factory)
        self.outbox = Outbox(session_factory)

    async def run_once(self, *, stages: Sequence[str] = (), limit: int = 1) -> list[WorkResult]:
        """Claim and execute up to ``limit`` units of work."""
        claimed = await self.queue.claim(worker=self.name, stages=stages, limit=limit)
        return [await self._execute(item) for item in claimed]

    async def drain(self, *, stages: Sequence[str] = (), max_items: int = 100) -> list[WorkResult]:
        """Run until the queue is empty or ``max_items`` is reached.

        Used by tests and batch runs. A long-lived worker calls ``run_once`` on
        a poll interval instead.
        """
        results: list[WorkResult] = []
        while len(results) < max_items:
            batch = await self.run_once(stages=stages, limit=1)
            if not batch:
                break
            results.extend(batch)
        return results

    async def _execute(self, item: ClaimedWork) -> WorkResult:
        handler = self.registry.handler_for(item.stage)
        if handler is None:
            # An unregistered stage is a deployment error, not a data error, so
            # it fails loudly rather than being retried forever.
            await self.queue.fail(item.work_item_id, f"no handler for stage {item.stage!r}")
            return WorkResult(
                work_item_id=item.work_item_id,
                stage=item.stage,
                ok=False,
                error="no handler",
            )

        try:
            emitted = await handler(item.subject_id, item.payload)
        except Exception as exc:  # a failing stage must not take the worker down
            logger.exception("stage %s failed for %s", item.stage, item.subject_id)
            status = await self.queue.fail(item.work_item_id, f"{type(exc).__name__}: {exc}")
            return WorkResult(
                work_item_id=item.work_item_id,
                stage=item.stage,
                ok=False,
                error=str(exc),
                dead=status.value == "dead",
            )

        events = [event for event in emitted if isinstance(event, Emitted)]
        await self._complete(item.work_item_id, events)
        return WorkResult(
            work_item_id=item.work_item_id,
            stage=item.stage,
            ok=True,
            events_emitted=len(events),
        )

    async def _complete(self, work_item_id: uuid.UUID, events: Sequence[Emitted]) -> None:
        """Mark the work done and stage its events atomically.

        Both in one transaction on purpose: completing the work without
        recording its events would strand the next stage, and recording events
        without completing the work would re-run it.
        """
        from econiq_data_models import WorkItem, WorkStatus

        async with self.session_factory() as session:
            item = await session.get(WorkItem, work_item_id)
            if item is None:
                raise LookupError(f"unknown work item {work_item_id}")
            item.status = WorkStatus.SUCCEEDED
            item.finished_at = utcnow()
            item.claimed_by = None
            if events:
                self.outbox.stage(session, *events)
            await session.commit()


class Reconciler:
    """Sweeps ontology state for work the event path missed.

    Registered finders are the stages' own ``run_pending``-style queries: they
    ask the database what is outstanding rather than trusting a queue. Enqueued
    at low priority so a sweep never delays live evidence, and idempotently, so
    a sweep that races the event path is a no-op.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.queue = WorkQueue(session_factory)
        self._finders: dict[str, PendingFinder] = {}

    def register(self, stage: str, finder: PendingFinder) -> None:
        if stage not in BY_NAME:
            raise KeyError(f"unknown stage {stage!r}")
        self._finders[stage] = finder

    async def reconcile(self, *, limit_per_stage: int = 50) -> ReconcileResult:
        enqueued: dict[str, int] = {}
        for stage_name, finder in self._finders.items():
            stage = BY_NAME[stage_name]
            subjects = list(await finder())[:limit_per_stage]
            count = 0
            for subject_id in subjects:
                result = await self.queue.enqueue(
                    stage_name,
                    idempotency_key=stage.key_for(subject_id),
                    subject_id=subject_id,
                    priority=Priority.RECONCILED,
                    max_attempts=stage.max_attempts,
                    trigger=Trigger.RECONCILER,
                )
                if result.created:
                    count += 1
            if count:
                logger.info("reconciler enqueued %d items for %s", count, stage_name)
            enqueued[stage_name] = count
        return ReconcileResult(enqueued=enqueued)

    @property
    def covered_stages(self) -> tuple[str, ...]:
        return tuple(sorted(self._finders))

    @property
    def uncovered_stages(self) -> tuple[str, ...]:
        """Stages with no reconciler.

        Worth watching: a stage reachable only through the event path has no
        backstop, so a dropped event there is a real gap rather than a delay.
        """
        return tuple(sorted(set(BY_NAME) - set(self._finders)))


@dataclass
class Orchestrator:
    """Dispatcher, worker and reconciler in one object.

    Convenience for single-process runs — the Phase 0 shape. In deployment these
    are separate processes scaled independently; nothing about the design
    depends on them sharing one.
    """

    session_factory: async_sessionmaker[AsyncSession]
    registry: StageRegistry
    worker_name: str = "orchestrator"

    def __post_init__(self) -> None:
        self.dispatcher = Dispatcher(self.session_factory)
        self.worker = Worker(self.session_factory, self.registry, name=self.worker_name)
        self.reconciler = Reconciler(self.session_factory)
        self.queue = WorkQueue(self.session_factory)

    async def tick(self, *, max_items: int = 25) -> tuple[DispatchResult, list[WorkResult]]:
        """Dispatch pending events, then run the work they scheduled."""
        dispatched = await self.dispatcher.dispatch_pending()
        results = await self.worker.drain(max_items=max_items)
        return dispatched, results

    async def run_until_idle(self, *, max_ticks: int = 20) -> list[WorkResult]:
        """Drive the pipeline to quiescence.

        Each tick's work emits the events the next tick dispatches, so the
        cascade — document to instrument — unfolds over several passes rather
        than in one synchronous call. That is the staged architecture working,
        not an inefficiency.
        """
        results: list[WorkResult] = []
        for _ in range(max_ticks):
            dispatched, batch = await self.tick()
            results.extend(batch)
            if not batch and dispatched.events_processed == 0:
                break
        return results

    async def poll_forever(
        self, *, interval: float = 1.0, reconcile_every: int = 60
    ) -> None:  # pragma: no cover - long-running loop
        """The deployment loop.

        The reconciler runs on a slower cadence than dispatch: it is a backstop,
        and sweeping the whole graph every second would be pointless load.
        """
        ticks = 0
        while True:
            await self.tick()
            ticks += 1
            if ticks % reconcile_every == 0:
                await self.reconciler.reconcile()
            await asyncio.sleep(interval)


def pipeline_summary() -> str:
    """The declared pipeline, for logs and documentation."""
    lines = ["stage                 priority  conc  triggered by"]
    for stage in PIPELINE:
        triggers = ", ".join(event.value for event in stage.triggered_by)
        lines.append(f"{stage.name:<21} {stage.priority:>8}  {stage.concurrency:>4}  {triggers}")
    return "\n".join(lines)


def now() -> datetime:
    return utcnow()
