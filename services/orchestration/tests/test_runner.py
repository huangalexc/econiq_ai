"""Dispatcher, worker and reconciler against a real database."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
from econiq_data_models import OutboxEvent, OutboxStatus, WorkItem, WorkStatus
from econiq_ontology import EntityType
from econiq_orchestration import (
    DomainEvent,
    Emitted,
    Orchestrator,
    Outbox,
    Stage,
    StageRegistry,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


def _registry(**handlers) -> StageRegistry:
    registry = StageRegistry()
    for stage, handler in handlers.items():
        registry.register(stage, handler)
    return registry


async def test_an_event_schedules_the_stage_that_declared_it(session_factory):
    outbox = Outbox(session_factory)
    process_id = uuid.uuid4()
    await outbox.publish(
        Emitted(
            name=DomainEvent.EVENT_PROPAGATED,
            subject_id=process_id,
            subject_type=EntityType.EVENT,
        )
    )

    orchestrator = Orchestrator(session_factory, _registry())
    result = await orchestrator.dispatcher.dispatch_pending()

    assert result.events_processed == 1
    assert result.work_enqueued == 1

    async with session_factory() as session:
        item = (await session.execute(select(WorkItem))).scalar_one()
        event = (await session.execute(select(OutboxEvent))).scalar_one()
    assert item.stage == Stage.DISCOVER_PROCESSES
    assert item.subject_id == process_id
    assert event.status is OutboxStatus.DISPATCHED


async def test_an_ungated_event_schedules_nothing(session_factory):
    """event.created is not event.propagated — the gate is structural."""
    await Outbox(session_factory).publish(
        Emitted(
            name=DomainEvent.EVENT_CREATED,
            subject_id=uuid.uuid4(),
            subject_type=EntityType.EVENT,
        )
    )

    result = await Orchestrator(session_factory, _registry()).dispatcher.dispatch_pending()

    assert result.events_processed == 1
    assert result.work_enqueued == 0


async def test_a_stage_completing_schedules_what_follows(session_factory):
    """The cascade: one event in, the whole chain unfolds over several ticks."""
    process_id, capability_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ran: list[str] = []

    async def discover(subject: uuid.UUID | None, _p: dict) -> Sequence[Emitted]:
        ran.append(Stage.DISCOVER_PROCESSES)
        return [
            Emitted(DomainEvent.PROCESS_CREATED, process_id, EntityType.PROCESS),
        ]

    async def state(subject: uuid.UUID | None, _p: dict) -> Sequence[Emitted]:
        ran.append(Stage.ESTIMATE_STATE)
        return [Emitted(DomainEvent.STATE_RECORDED, subject, EntityType.PROCESS)]

    async def capabilities(subject: uuid.UUID | None, _p: dict) -> Sequence[Emitted]:
        ran.append(Stage.MAP_CAPABILITIES)
        return [Emitted(DomainEvent.CAPABILITY_UPDATED, capability_id, EntityType.CAPABILITY)]

    async def critique(subject: uuid.UUID | None, _p: dict) -> Sequence[Emitted]:
        ran.append(Stage.CRITIQUE_PROCESS)
        return []

    async def assets(subject: uuid.UUID | None, _p: dict) -> Sequence[Emitted]:
        ran.append(Stage.DISCOVER_ASSETS)
        return [Emitted(DomainEvent.ASSET_UPDATED, asset_id, EntityType.ASSET)]

    registry = _registry(
        **{
            Stage.DISCOVER_PROCESSES: discover,
            Stage.ESTIMATE_STATE: state,
            Stage.MAP_CAPABILITIES: capabilities,
            Stage.CRITIQUE_PROCESS: critique,
            Stage.DISCOVER_ASSETS: assets,
        }
    )
    orchestrator = Orchestrator(session_factory, registry)
    await Outbox(session_factory).publish(
        Emitted(DomainEvent.EVENT_PROPAGATED, uuid.uuid4(), EntityType.EVENT)
    )

    results = await orchestrator.run_until_idle()

    assert all(result.ok for result in results)
    assert ran == [
        Stage.DISCOVER_PROCESSES,
        Stage.ESTIMATE_STATE,
        # Capabilities before critique: critique is the lowest-priority stage.
        Stage.MAP_CAPABILITIES,
        Stage.CRITIQUE_PROCESS,
        Stage.DISCOVER_ASSETS,
    ]


async def test_completion_and_its_events_are_one_transaction(session_factory):
    """A stage cannot finish without its successor being scheduled."""

    async def discover(subject: uuid.UUID | None, _p: dict) -> Sequence[Emitted]:
        return [Emitted(DomainEvent.PROCESS_CREATED, uuid.uuid4(), EntityType.PROCESS)]

    orchestrator = Orchestrator(session_factory, _registry(**{Stage.DISCOVER_PROCESSES: discover}))
    await Outbox(session_factory).publish(
        Emitted(DomainEvent.EVENT_PROPAGATED, uuid.uuid4(), EntityType.EVENT)
    )
    await orchestrator.dispatcher.dispatch_pending()
    await orchestrator.worker.run_once()

    async with session_factory() as session:
        item = (await session.execute(select(WorkItem))).scalar_one()
        pending = (
            await session.execute(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.status == OutboxStatus.PENDING)
            )
        ).scalar_one()
    assert item.status is WorkStatus.SUCCEEDED
    assert pending == 1


async def test_a_failing_stage_does_not_take_the_worker_down(session_factory):
    async def broken(_subject: uuid.UUID | None, _p: dict) -> Sequence[Emitted]:
        raise RuntimeError("provider unavailable")

    orchestrator = Orchestrator(session_factory, _registry(**{Stage.DISCOVER_PROCESSES: broken}))
    await Outbox(session_factory).publish(
        Emitted(DomainEvent.EVENT_PROPAGATED, uuid.uuid4(), EntityType.EVENT)
    )
    await orchestrator.dispatcher.dispatch_pending()

    results = await orchestrator.worker.run_once()

    assert results[0].ok is False
    assert "provider unavailable" in (results[0].error or "")

    async with session_factory() as session:
        item = (await session.execute(select(WorkItem))).scalar_one()
    assert item.status is WorkStatus.FAILED
    assert item.attempts == 1
    assert "RuntimeError" in (item.last_error or "")


async def test_an_unregistered_stage_fails_loudly(session_factory):
    orchestrator = Orchestrator(session_factory, _registry())
    await Outbox(session_factory).publish(
        Emitted(DomainEvent.EVENT_PROPAGATED, uuid.uuid4(), EntityType.EVENT)
    )
    await orchestrator.dispatcher.dispatch_pending()

    results = await orchestrator.worker.run_once()

    assert results[0].ok is False
    assert results[0].error == "no handler"


async def test_the_reconciler_finds_work_the_event_path_missed(session_factory):
    """A dropped event is a latency problem, never a correctness one."""
    stranded = uuid.uuid4()

    async def finder() -> Sequence[uuid.UUID]:
        return [stranded]

    orchestrator = Orchestrator(session_factory, _registry())
    orchestrator.reconciler.register(Stage.DISCOVER_PROCESSES, finder)

    result = await orchestrator.reconciler.reconcile()

    assert result.enqueued[Stage.DISCOVER_PROCESSES] == 1
    async with session_factory() as session:
        item = (await session.execute(select(WorkItem))).scalar_one()
    assert item.subject_id == stranded
    assert item.trigger == "reconciler"
    # Behind live work, because it is a backstop rather than the fast path.
    assert item.priority > 100


async def test_the_reconciler_does_not_duplicate_queued_work(session_factory):
    subject = uuid.uuid4()

    async def finder() -> Sequence[uuid.UUID]:
        return [subject]

    orchestrator = Orchestrator(session_factory, _registry())
    orchestrator.reconciler.register(Stage.DISCOVER_PROCESSES, finder)
    await Outbox(session_factory).publish(
        Emitted(DomainEvent.EVENT_PROPAGATED, subject, EntityType.EVENT)
    )
    await orchestrator.dispatcher.dispatch_pending()

    result = await orchestrator.reconciler.reconcile()

    assert result.total == 0
    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(WorkItem))).scalar_one()
    assert count == 1


async def test_uncovered_stages_are_visible(session_factory):
    """A stage with no backstop has a real gap if its event is lost."""
    orchestrator = Orchestrator(session_factory, _registry())
    orchestrator.reconciler.register(Stage.DISCOVER_PROCESSES, lambda: _none())

    assert orchestrator.reconciler.covered_stages == (Stage.DISCOVER_PROCESSES,)
    assert Stage.RESOLVE_EVENTS in orchestrator.reconciler.uncovered_stages


async def _none() -> Sequence[uuid.UUID]:
    return []


async def test_the_outbox_rolls_back_with_its_transaction(session_factory):
    """The whole point: no window where the state exists and the event does not."""
    outbox = Outbox(session_factory)
    try:
        async with session_factory() as session:
            outbox.stage(
                session, Emitted(DomainEvent.PROCESS_UPDATED, uuid.uuid4(), EntityType.PROCESS)
            )
            await session.flush()
            raise RuntimeError("the state change failed")
    except RuntimeError:
        pass

    assert await outbox.pending() == []
