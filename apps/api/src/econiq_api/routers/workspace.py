"""Watchlists and workspace reads (issues #19, #32).

The only endpoints in this API that require a session, and the only ones that
write. PRD §23's line holds: the graph is shared and these are not.

Writes are permitted here for the reason they are forbidden everywhere else. A
Process written by hand would have no agent run, no prompt version and no
evaluation behind it — indistinguishable afterwards from an evidenced one. A
watchlist entry is not a claim about the world; it is a person saying they care.
Nothing downstream reasons from it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from econiq_data_models import WatchlistItem
from econiq_ontology import EntityType, utcnow
from fastapi import APIRouter, Query
from sqlalchemy import select, update

from econiq_api import alerts as alert_engine
from econiq_api.auth import MemberDep, WorkspaceDep
from econiq_api.deps import AsOfDep, GraphDep, PageDep, SessionDep
from econiq_api.errors import not_found
from econiq_api.schemas import (
    AlertOut,
    NodeRef,
    WatchlistItemOut,
    WorkspaceOut,
)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("", response_model=WorkspaceOut)
async def current(workspace: WorkspaceDep, principal: MemberDep) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.workspace_id,
        name=workspace.name,
        kind=workspace.kind,
        external_id=workspace.external_id,
        user_id=principal.user_id,
    )


@router.get("/watchlist", response_model=list[WatchlistItemOut])
async def watchlist(
    session: SessionDep,
    graph: GraphDep,
    workspace: WorkspaceDep,
    page: PageDep,
    node_type: Annotated[EntityType | None, Query()] = None,
) -> list[WatchlistItemOut]:
    query = select(WatchlistItem).where(
        WatchlistItem.workspace_id == workspace.workspace_id,
        WatchlistItem.removed_at.is_(None),
    )
    if node_type is not None:
        query = query.where(WatchlistItem.node_type == node_type)

    rows = list(
        (
            await session.execute(
                query.order_by(WatchlistItem.created_at.desc())
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    labels = await graph.nodes([row.node_id for row in rows])
    return [
        WatchlistItemOut(
            id=row.watchlist_item_id,
            node=(
                NodeRef(id=node.node_id, type=node.node_type, label=node.label, slug=node.slug)
                if (node := labels.get(row.node_id)) is not None
                else NodeRef(id=row.node_id, type=row.node_type, label="(unknown)")
            ),
            note=row.note,
            added_by=row.added_by,
            added_at=row.created_at,
        )
        for row in rows
    ]


@router.put("/watchlist/{node_id}", response_model=WatchlistItemOut)
async def watch(
    node_id: uuid.UUID,
    session: SessionDep,
    graph: GraphDep,
    workspace: WorkspaceDep,
    principal: MemberDep,
    note: Annotated[str | None, Query(max_length=500)] = None,
) -> WatchlistItemOut:
    """Watch a node. Idempotent — watching twice is watching once."""
    node = await graph.node(node_id)
    if node is None:
        raise not_found("node", node_id)

    existing = (
        await session.execute(
            select(WatchlistItem).where(
                WatchlistItem.workspace_id == workspace.workspace_id,
                WatchlistItem.node_id == node_id,
                WatchlistItem.removed_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = WatchlistItem(
            watchlist_item_id=uuid.uuid4(),
            workspace_id=workspace.workspace_id,
            node_id=node_id,
            node_type=node.node_type,
            note=note,
            added_by=principal.user_id,
        )
        session.add(existing)
    elif note is not None:
        existing.note = note
    await session.commit()

    return WatchlistItemOut(
        id=existing.watchlist_item_id,
        node=NodeRef(id=node.node_id, type=node.node_type, label=node.label, slug=node.slug),
        note=existing.note,
        added_by=existing.added_by,
        added_at=existing.created_at,
    )


@router.delete("/watchlist/{node_id}", status_code=204)
async def unwatch(node_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep) -> None:
    """Stop watching. Dated rather than deleted.

    When someone stopped caring about a thesis is part of the research record —
    it is often the moment worth revisiting.
    """
    await session.execute(
        update(WatchlistItem)
        .where(
            WatchlistItem.workspace_id == workspace.workspace_id,
            WatchlistItem.node_id == node_id,
            WatchlistItem.removed_at.is_(None),
        )
        .values(removed_at=utcnow())
    )
    await session.commit()


@router.get("/alerts", response_model=list[AlertOut])
async def watched_alerts(
    session: SessionDep,
    workspace: WorkspaceDep,
    as_of: AsOfDep,
    window_days: Annotated[int, Query(ge=1, le=365)] = 14,
) -> list[AlertOut]:
    """Alerts about watched Processes only (#32).

    The same derivation the public feed uses, narrowed to what this workspace
    watches — which is the filter #32 always wanted and could not have until
    there was a workspace to hang it on.
    """
    watched = (
        (
            await session.execute(
                select(WatchlistItem.node_id).where(
                    WatchlistItem.workspace_id == workspace.workspace_id,
                    WatchlistItem.removed_at.is_(None),
                    WatchlistItem.node_type == EntityType.PROCESS,
                )
            )
        )
        .scalars()
        .all()
    )
    if not watched:
        return []
    from datetime import timedelta

    return await alert_engine.generate(
        session,
        as_of=as_of,
        process_ids=list(watched),
        window=timedelta(days=window_days),
    )
