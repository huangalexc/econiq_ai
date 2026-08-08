"""Confluence search, the journal feed and semantic alerts (#27, #31, #32).

Three screens' worth of reads that share one property: they are all *cross-
subject*. The existing endpoints answer questions about one Process or one
Capability; these answer questions about the set, which is where the ontology
starts paying for itself.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated

from econiq_data_models import AssetExposure, JournalEntry, Relationship
from econiq_ontology import EntityType, RelationshipType
from fastapi import APIRouter, Query
from sqlalchemy import Select, distinct, func, select

from econiq_api import alerts as alert_engine
from econiq_api import provenance
from econiq_api.deps import AsOfDep, GraphDep, PageDep, SessionDep
from econiq_api.schemas import (
    AlertOut,
    ConfluenceHitOut,
    ConfluenceResultOut,
    JournalEntryOut,
    NodeRef,
)
from econiq_api.temporal import current_revision, recorded_by

router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/confluence", response_model=ConfluenceResultOut)
async def confluence(
    session: SessionDep,
    graph: GraphDep,
    as_of: AsOfDep,
    process_id: Annotated[list[uuid.UUID], Query(min_length=1)],
    require_all: Annotated[
        bool,
        Query(
            description=(
                "AND semantics (ui_concept §11). False returns the union, which is usually noise."
            )
        ),
    ] = True,
) -> ConfluenceResultOut:
    """Capabilities the selected Processes share.

    §11's picture is two Processes converging on one Capability, and the AND is
    the point: a Capability that several *independent* theses all require is
    more interesting than one a single thesis needs badly. Confluence is a
    structural fact, so it is read from the graph rather than judged.
    """
    creates_query: Select[tuple[uuid.UUID, uuid.UUID]] = current_revision(
        select(Relationship.source_id, Relationship.target_id).where(
            Relationship.relationship_type == RelationshipType.CREATES,
            Relationship.source_id.in_(process_id),
        ),
        Relationship,
        as_of,
    )
    creates = creates_query.subquery("creates")
    requires = current_revision(
        select(Relationship.source_id, Relationship.target_id).where(
            Relationship.relationship_type == RelationshipType.REQUIRES
        ),
        Relationship,
        as_of,
    ).subquery("requires")

    rows = (
        await session.execute(
            select(
                requires.c.target_id.label("capability_id"),
                func.array_agg(distinct(creates.c.source_id)).label("processes"),
            )
            .join(requires, requires.c.source_id == creates.c.target_id)
            .group_by(requires.c.target_id)
        )
    ).all()

    wanted = set(process_id)
    hits: list[ConfluenceHitOut] = []
    for capability_id, reaching in rows:
        reached = [pid for pid in reaching if pid in wanted]
        if require_all and len(reached) < len(wanted):
            continue
        hits.append(
            ConfluenceHitOut(
                capability=NodeRef(id=capability_id, type=EntityType.CAPABILITY, label=""),
                process_ids=sorted(reached),
                reached_by=len(reached),
                # Two hops: Process → Bottleneck → Capability. Fixed by the
                # ontology, so it is stated rather than measured.
                shortest_hops=2,
                asset_count=0,
            )
        )

    if not hits:
        return ConfluenceResultOut(
            process_ids=list(process_id), require_all=require_all, capabilities=[]
        )

    # Labels and Asset counts in one pass each, rather than per hit.
    labels = await graph.nodes([hit.capability.id for hit in hits])
    counts: dict[uuid.UUID, int] = {
        target_id: count
        for target_id, count in (
            await session.execute(
                select(
                    AssetExposure.target_id,
                    func.count(distinct(AssetExposure.asset_id)),
                )
                .where(
                    AssetExposure.target_id.in_([hit.capability.id for hit in hits]),
                    AssetExposure.target_type == EntityType.CAPABILITY,
                )
                .group_by(AssetExposure.target_id)
            )
        ).all()
    }

    resolved = [
        ConfluenceHitOut(
            capability=(
                NodeRef(
                    id=node.node_id,
                    type=node.node_type,
                    label=node.label,
                    slug=node.slug,
                )
                if (node := labels.get(hit.capability.id)) is not None
                else hit.capability
            ),
            process_ids=hit.process_ids,
            reached_by=hit.reached_by,
            shortest_hops=hit.shortest_hops,
            asset_count=counts.get(hit.capability.id, 0),
        )
        for hit in hits
    ]
    # Most-shared first, then by where the confluence is actually investable.
    resolved.sort(key=lambda hit: (-hit.reached_by, -hit.asset_count))
    return ConfluenceResultOut(
        process_ids=list(process_id), require_all=require_all, capabilities=resolved
    )


@router.get("/journal", response_model=list[JournalEntryOut])
async def journal_feed(
    session: SessionDep,
    page: PageDep,
    as_of: AsOfDep,
    subject_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    subject_type: Annotated[EntityType | None, Query()] = None,
) -> list[JournalEntryOut]:
    """Every belief change, across subjects (#31, ui_concept §20).

    The per-Process journal already exists; this is the same record read as a
    feed, which is how someone asks "what has the system changed its mind about
    lately" rather than "about this".
    """
    query: Select[tuple[JournalEntry]] = select(JournalEntry)
    if subject_id:
        query = query.where(JournalEntry.subject_id.in_(subject_id))
    if subject_type is not None:
        query = query.where(JournalEntry.subject_type == subject_type)

    rows = list(
        (
            await session.execute(
                recorded_by(query, JournalEntry, as_of)
                .order_by(JournalEntry.observed_at.desc(), JournalEntry.recorded_at.desc())
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    attribution = await provenance.load(session, (row.agent_run_id for row in rows))
    return [
        JournalEntryOut(
            id=row.journal_entry_id,
            kind=row.kind.value,
            summary=row.summary,
            subject_id=row.subject_id,
            subject_type=row.subject_type,
            observed_at=row.observed_at,
            recorded_at=row.recorded_at,
            confidence_before=row.confidence_before,
            confidence_after=row.confidence_after,
            changes=list(row.changes),
            triggering_event_id=row.triggering_event_id,
            provenance=attribution.get(row.agent_run_id) if row.agent_run_id else None,
        )
        for row in rows
    ]


@router.get("/alerts", response_model=list[AlertOut])
async def alert_feed(
    session: SessionDep,
    page: PageDep,
    as_of: AsOfDep,
    process_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    window_days: Annotated[int, Query(ge=1, le=365)] = 14,
    severity: Annotated[list[str] | None, Query()] = None,
) -> list[AlertOut]:
    """Thesis changes worth reading (#32, PRD §20).

    Derived at read time rather than stored. Point-in-time comes free — asking
    as of July returns the alerts that existed in July — and an alert whose
    underlying change was later superseded stops existing rather than lingering
    as a notification about something no longer true.

    `process_id` is where a watchlist plugs in once users exist (#19). Until
    then the feed is the whole graph, which is the right default for one analyst.
    """
    found = await alert_engine.generate(
        session,
        as_of=as_of,
        process_ids=process_id,
        window=timedelta(days=window_days),
    )
    if severity:
        wanted = set(severity)
        found = [alert for alert in found if alert.severity in wanted]
    return found[page.offset : page.offset + page.limit]
