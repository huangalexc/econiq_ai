"""The Discover feed and the Process screener (issue #20, ui_concept §5, §25).

Both answer the same question at different resolutions — *what is changing?* —
so they share the ranking in :mod:`econiq_api.discover`. The feed is the ranking
truncated; the screener is the ranking filtered. Keeping them on one computation
means a Process cannot be hot on one screen and absent from the other.

The frontend never calls a model (ui_concept §30). Everything here is SQL and
arithmetic over rows the agents already wrote.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from econiq_data_models import Process, ProcessState
from econiq_ontology import ProcessArchetype, ProcessStateLabel, ProcessStatus
from fastapi import APIRouter, Query
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from econiq_api.deps import AsOfDep, PageDep, SessionDep
from econiq_api.discover import (
    UNAVAILABLE_INPUTS,
    WEIGHTS,
    WINDOW,
    RankedProcess,
    rank_processes,
)
from econiq_api.schemas import (
    DiscoverFeedOut,
    EmergingProcessOut,
    RankComponentOut,
    UnavailableInputOut,
)
from econiq_api.temporal import current_revision, recorded_by

router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("", response_model=DiscoverFeedOut)
async def discover(
    session: SessionDep,
    page: PageDep,
    as_of: AsOfDep,
    archetype: Annotated[list[ProcessArchetype] | None, Query()] = None,
    state: Annotated[list[ProcessStateLabel] | None, Query()] = None,
    min_state_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    min_assets: Annotated[int | None, Query(ge=0)] = None,
    min_capabilities: Annotated[int | None, Query(ge=0)] = None,
    accelerating_only: Annotated[
        bool,
        Query(
            description=(
                "Only Processes whose evidence in the trailing window exceeds the window before it."
            )
        ),
    ] = False,
    requires_review: Annotated[bool | None, Query()] = None,
) -> DiscoverFeedOut:
    """Processes ranked by how much their evidence has moved.

    The filters are the screener of §25. They are applied *before* ranking where
    they are cheap row predicates and after where they depend on the ranking's
    own measurements, but either way the ordering within a filtered set is the
    same ordering the unfiltered feed would give — a screener that reranked its
    results would answer a different question from the one the user asked.
    """
    now = datetime.now(UTC)

    candidates = await _candidate_processes(
        session,
        as_of=as_of,
        archetype=archetype,
        state=state,
        requires_review=requires_review,
    )
    if not candidates:
        return _empty_feed()

    ranked = await rank_processes(session, as_of=as_of, now=now, process_ids=list(candidates))
    ranked = [
        item
        for item in ranked
        if _passes(
            item,
            min_assets=min_assets,
            min_capabilities=min_capabilities,
            accelerating_only=accelerating_only,
        )
    ]

    states = await _latest_states(session, [item.process_id for item in ranked], as_of)
    if min_state_confidence is not None:
        ranked = [
            item
            for item in ranked
            if (state_row := states.get(item.process_id)) is not None
            and state_row.state_confidence >= min_state_confidence
        ]

    window = ranked[page.offset : page.offset + page.limit]
    return DiscoverFeedOut(
        processes=[
            _row(item, candidates[item.process_id], states.get(item.process_id)) for item in window
        ],
        weights=dict(WEIGHTS),
        window_days=WINDOW.days,
        unavailable_inputs=[
            UnavailableInputOut(name=name, reason=reason) for name, reason in UNAVAILABLE_INPUTS
        ],
    )


# --------------------------------------------------------------------------- #


def _empty_feed() -> DiscoverFeedOut:
    return DiscoverFeedOut(
        processes=[],
        weights=dict(WEIGHTS),
        window_days=WINDOW.days,
        unavailable_inputs=[
            UnavailableInputOut(name=name, reason=reason) for name, reason in UNAVAILABLE_INPUTS
        ],
    )


async def _candidate_processes(
    session: AsyncSession,
    *,
    as_of: datetime | None,
    archetype: list[ProcessArchetype] | None,
    state: list[ProcessStateLabel] | None,
    requires_review: bool | None,
) -> dict[uuid.UUID, Process]:
    query: Select[tuple[Process]] = select(Process)
    query = current_revision(query, Process, as_of)
    # Merged and invalidated Processes are excluded, for different reasons. A
    # merged Process is now another Process, so listing both double-counts the
    # same thesis. An invalidated one is a finished conclusion, and calling it
    # "emerging" would be the opposite of what happened to it. Dormant
    # Processes stay in: the ranking already pushes them down through evidence
    # acceleration and state recency, which is more honest than hiding them —
    # a dormant Process waking up is exactly what this screen exists to catch.
    query = query.where(Process.status.not_in([ProcessStatus.MERGED, ProcessStatus.INVALIDATED]))
    if archetype:
        query = query.where(Process.archetype.in_(archetype))
    if requires_review is not None:
        query = query.where(Process.requires_review.is_(requires_review))

    rows = (await session.execute(query)).scalars().all()
    candidates = {row.process_id: row for row in rows}

    if state:
        current = await _latest_states(session, list(candidates), as_of)
        wanted = set(state)
        candidates = {
            pid: row
            for pid, row in candidates.items()
            if (found := current.get(pid)) is not None and found.categorical_state in wanted
        }
    return candidates


async def _latest_states(
    session: AsyncSession, process_ids: list[uuid.UUID], as_of: datetime | None
) -> dict[uuid.UUID, ProcessState]:
    if not process_ids:
        return {}
    query: Select[tuple[ProcessState]] = select(ProcessState).where(
        ProcessState.process_id.in_(process_ids)
    )
    rows = (
        (
            await session.execute(
                recorded_by(query, ProcessState, as_of).order_by(
                    ProcessState.observed_at.desc(), ProcessState.recorded_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[uuid.UUID, ProcessState] = {}
    for row in rows:
        latest.setdefault(row.process_id, row)
    return latest


def _passes(
    item: RankedProcess,
    *,
    min_assets: int | None,
    min_capabilities: int | None,
    accelerating_only: bool,
) -> bool:
    if min_assets is not None and item.asset_count < min_assets:
        return False
    if min_capabilities is not None and item.capability_count < min_capabilities:
        return False
    return not (accelerating_only and item.evidence_recent <= item.evidence_prior)


def _row(item: RankedProcess, process: Process, state: ProcessState | None) -> EmergingProcessOut:
    return EmergingProcessOut(
        id=process.process_id,
        name=process.name,
        slug=process.slug,
        description=process.description,
        archetype=process.archetype,
        archetype_confidence=process.archetype_confidence,
        status=process.status,
        requires_review=process.requires_review,
        revision=process.revision,
        current_state=state.categorical_state if state else None,
        state_confidence=state.state_confidence if state else None,
        state_observed_at=state.observed_at if state else None,
        rank_score=item.score,
        components=[
            RankComponentOut(
                name=component.name,
                raw=component.raw,
                normalised=round(component.normalised, 4),
                weight=component.weight,
                contribution=round(component.contribution, 4),
            )
            for component in item.components
        ],
        evidence_recent=item.evidence_recent,
        evidence_prior=item.evidence_prior,
        evidence_delta=item.evidence_recent - item.evidence_prior,
        contradiction_count=item.contradiction_count,
        source_breadth=item.source_breadth,
        capability_count=item.capability_count,
        asset_count=item.asset_count,
        binding_bottlenecks=list(item.bottleneck_names),
    )
