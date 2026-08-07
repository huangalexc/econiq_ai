"""The work queue, against a real Postgres."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from econiq_data_models import WorkItem, WorkStatus
from econiq_ontology import utcnow
from econiq_orchestration import Priority, Trigger, WorkQueue
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

STAGE = "discover_processes"


async def test_work_is_claimed_once_and_only_once(session_factory):
    """SKIP LOCKED is what makes several workers safe without a broker."""
    queue = WorkQueue(session_factory)
    subject = uuid.uuid4()
    await queue.enqueue(STAGE, idempotency_key=f"{STAGE}:{subject}", subject_id=subject)

    first, second = await asyncio.gather(
        queue.claim(worker="a", limit=5), queue.claim(worker="b", limit=5)
    )

    claimed = [*first, *second]
    assert len(claimed) == 1
    assert claimed[0].subject_id == subject


async def test_the_same_work_is_not_queued_twice(session_factory):
    """The event path and the reconciler both enqueue; agent runs cost money."""
    queue = WorkQueue(session_factory)
    subject = uuid.uuid4()
    key = f"{STAGE}:{subject}"

    first = await queue.enqueue(STAGE, idempotency_key=key, subject_id=subject)
    second = await queue.enqueue(
        STAGE, idempotency_key=key, subject_id=subject, trigger=Trigger.RECONCILER
    )

    assert first.created is True
    assert second.created is False
    assert second.work_item_id == first.work_item_id

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(WorkItem))).scalar_one()
    assert count == 1


async def test_completed_work_does_not_block_a_later_run(session_factory):
    """New evidence must be able to re-run a stage for the same subject."""
    queue = WorkQueue(session_factory)
    subject = uuid.uuid4()
    key = f"{STAGE}:{subject}"

    first = await queue.enqueue(STAGE, idempotency_key=key, subject_id=subject)
    assert first.work_item_id is not None
    await queue.succeed(first.work_item_id)

    second = await queue.enqueue(STAGE, idempotency_key=key, subject_id=subject)
    assert second.created is True
    assert second.work_item_id != first.work_item_id


async def test_priority_puts_live_evidence_ahead_of_backfill(session_factory):
    queue = WorkQueue(session_factory)
    await queue.enqueue(
        STAGE, idempotency_key="backfill", priority=Priority.BACKFILL, subject_id=uuid.uuid4()
    )
    live_subject = uuid.uuid4()
    await queue.enqueue(
        STAGE, idempotency_key="live", priority=Priority.LIVE, subject_id=live_subject
    )

    claimed = await queue.claim(worker="w", limit=1)

    assert claimed[0].subject_id == live_subject


async def test_a_failure_backs_off_before_being_retried(session_factory):
    queue = WorkQueue(session_factory)
    await queue.enqueue(STAGE, idempotency_key="k", subject_id=uuid.uuid4())

    item = (await queue.claim(worker="w"))[0]
    status = await queue.fail(item.work_item_id, "provider timeout")

    assert status is WorkStatus.FAILED
    # Not immediately claimable — the backoff is in run_after.
    assert await queue.claim(worker="w") == []
    later = await queue.claim(worker="w", now=utcnow() + timedelta(minutes=1))
    assert later[0].attempts == 2


async def test_exhausted_retries_become_dead_letters_not_silence(session_factory):
    """Work that vanished is indistinguishable from work never needed."""
    queue = WorkQueue(session_factory)
    await queue.enqueue(STAGE, idempotency_key="k", subject_id=uuid.uuid4(), max_attempts=2)

    now = utcnow()
    for attempt in range(2):
        item = (await queue.claim(worker="w", now=now + timedelta(hours=attempt)))[0]
        status = await queue.fail(item.work_item_id, f"failure {attempt}")

    assert status is WorkStatus.DEAD
    assert await queue.claim(worker="w", now=now + timedelta(days=1)) == []

    dead = await queue.dead_letters()
    assert len(dead) == 1
    assert dead[0].stage == STAGE

    depth = await queue.depth()
    assert depth.dead == 1
    assert depth.pending == 0


async def test_work_held_by_a_dead_worker_is_reclaimed(session_factory):
    """The failure mode that makes people distrust database-backed queues."""
    queue = WorkQueue(session_factory, lease=timedelta(minutes=5))
    await queue.enqueue(STAGE, idempotency_key="k", subject_id=uuid.uuid4())

    held = (await queue.claim(worker="crashed"))[0]
    assert await queue.claim(worker="healthy") == []

    later = await queue.claim(worker="healthy", now=utcnow() + timedelta(minutes=10))

    assert len(later) == 1
    assert later[0].work_item_id == held.work_item_id
    assert later[0].attempts == 2


async def test_scheduled_work_waits_for_its_time(session_factory):
    """Time-based triggers are just a future run_after."""
    queue = WorkQueue(session_factory)
    await queue.enqueue(
        STAGE,
        idempotency_key="k",
        subject_id=uuid.uuid4(),
        run_after=utcnow() + timedelta(hours=1),
        trigger=Trigger.SCHEDULE,
    )

    assert await queue.claim(worker="w") == []
    assert len(await queue.claim(worker="w", now=utcnow() + timedelta(hours=2))) == 1


async def test_work_can_be_claimed_per_stage(session_factory):
    queue = WorkQueue(session_factory)
    await queue.enqueue("critique_process", idempotency_key="c", subject_id=uuid.uuid4())
    await queue.enqueue(STAGE, idempotency_key="d", subject_id=uuid.uuid4())

    claimed = await queue.claim(worker="w", stages=["critique_process"], limit=5)

    assert [item.stage for item in claimed] == ["critique_process"]


async def test_superseded_work_is_cancelled_not_run(session_factory):
    queue = WorkQueue(session_factory)
    subject = uuid.uuid4()
    await queue.enqueue(STAGE, idempotency_key=f"{STAGE}:{subject}", subject_id=subject)

    cancelled = await queue.supersede(STAGE, f"{STAGE}:{subject}")

    assert cancelled == 1
    assert await queue.claim(worker="w") == []
