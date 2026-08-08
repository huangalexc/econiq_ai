"""Live updates (issue #34, ui_concept §31).

Server-sent events rather than WebSockets. The traffic is one-directional —
the backend tells the terminal something changed and the terminal refetches —
and SSE gives that with automatic reconnection, ordinary HTTP semantics and no
second protocol to authenticate. A WebSocket would buy bidirectionality nothing
here needs.

**The stream carries notifications, not data.** Each event says *what kind of
thing changed and which node*, and the client invalidates the matching query.
Pushing the changed rows themselves would mean two paths to every value — the
push and the fetch — and they diverge the first time one is filtered differently
or read at a different `as_of`. A cache invalidation cannot go stale.

Driven off `outbox_events`, which the pipeline already writes in the same
transaction as the state change (#14). So the stream inherits that guarantee:
there is no window in which a Process changed and the terminal was not told.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from econiq_data_models import OutboxEvent
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from econiq_api.deps import SessionFactoryDep

logger = logging.getLogger("econiq.api.stream")

router = APIRouter(prefix="/api", tags=["stream"])

#: How often the outbox is polled. Postgres LISTEN/NOTIFY would remove the
#: poll, but it needs a dedicated connection per subscriber and the pipeline
#: writes at human speed — a two-second delay on a screen nobody is staring at
#: is not the bottleneck, and this has no operational surface.
POLL_SECONDS = 2.0

#: Sent when the outbox is quiet. Without it, proxies close an idle connection
#: at thirty seconds and the client reconnects in a loop that looks like churn.
HEARTBEAT_SECONDS = 20.0

#: Domain events worth waking a screen for, mapped to what the client should
#: consider stale. Anything not listed is deliberately not pushed: a stream that
#: fires on every internal step trains people to ignore it.
INVALIDATES: dict[str, tuple[str, ...]] = {
    "document.ingested": ("pipeline",),
    "event.propagated": ("discover", "process", "alerts"),
    "process.created": ("discover", "processes"),
    "process.updated": ("discover", "process", "journal", "alerts"),
    "state.recorded": ("process", "discover", "alerts"),
    "capability.updated": ("capabilities", "confluence"),
    "asset.updated": ("assets", "comparison"),
    "critique.recorded": ("process", "alerts"),
}


@router.get("/stream")
async def stream(
    request: Request,
    factory: SessionFactoryDep,
    since: Annotated[str | None, Query(description="Resume from this event id.")] = None,
) -> StreamingResponse:
    """An SSE feed of what changed.

    Resumable. The browser sends `Last-Event-ID` on reconnect and the cursor
    picks up from there, so a laptop closing its lid does not silently miss the
    State transition it was open to watch.
    """
    resume = request.headers.get("last-event-id") or since

    async def events() -> AsyncIterator[str]:
        cursor = await _start(factory, resume)
        last_beat = datetime.now(UTC)

        # Told immediately so a client knows the stream is live rather than
        # merely connected.
        yield _frame("ready", {"from": str(cursor) if cursor else None})

        while True:
            if await request.is_disconnected():
                return
            try:
                rows = await _drain(factory, cursor)
            except Exception:  # a transient database error must not end the stream
                logger.exception("stream poll failed")
                await asyncio.sleep(POLL_SECONDS)
                continue

            for row in rows:
                cursor = row.created_at
                targets = INVALIDATES.get(row.event_name)
                if not targets:
                    continue
                yield _frame(
                    "change",
                    {
                        "name": row.event_name,
                        "subject_id": str(row.subject_id) if row.subject_id else None,
                        "subject_type": row.subject_type.value if row.subject_type else None,
                        "invalidates": list(targets),
                        "at": row.created_at.isoformat(),
                    },
                    event_id=str(row.outbox_event_id),
                )
                last_beat = datetime.now(UTC)

            now = datetime.now(UTC)
            if (now - last_beat).total_seconds() >= HEARTBEAT_SECONDS:
                yield ": keep-alive\n\n"
                last_beat = now
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Nginx buffers by default, which turns a live stream into a batch
            # delivered when the connection closes.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _frame(event: str, data: dict[str, object], *, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


async def _start(factory: SessionFactoryDep, resume: str | None) -> datetime | None:
    """Where to read from.

    A fresh connection starts at *now*, not at the beginning of the outbox.
    Replaying weeks of history into a page that just opened would flood the
    cache with invalidations for screens nobody is looking at.
    """
    async with factory() as session:
        if resume:
            row = await session.execute(
                select(OutboxEvent.created_at).where(OutboxEvent.outbox_event_id == resume)
            )
            found = row.scalar_one_or_none()
            if found is not None:
                return found
        latest = await session.execute(
            select(OutboxEvent.created_at).order_by(OutboxEvent.created_at.desc()).limit(1)
        )
        return latest.scalar_one_or_none() or datetime.now(UTC)


async def _drain(factory: SessionFactoryDep, cursor: datetime | None) -> list[OutboxEvent]:
    async with factory() as session:
        query = select(OutboxEvent).order_by(OutboxEvent.created_at).limit(100)
        if cursor is not None:
            query = query.where(OutboxEvent.created_at > cursor)
        return list((await session.execute(query)).scalars().all())
