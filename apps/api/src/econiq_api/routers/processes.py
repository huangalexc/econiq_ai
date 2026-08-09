"""Process endpoints — the unit of research.

The detail response deliberately assembles the whole picture: current State with
its features, open Bottlenecks, open critiques, and evidence counts on both
sides. A Process screen that had to make five calls to show one thing would
invite callers to skip the inconvenient ones, and the inconvenient one here is
the critique list.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from econiq_data_models import (
    Bottleneck,
    Critique,
    Event,
    EvidenceLink,
    JournalEntry,
    Process,
    ProcessState,
    ProcessStateFeature,
)
from econiq_ontology import CritiqueStatus, EntityType, ProcessStatus
from fastapi import APIRouter, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from econiq_api import provenance
from econiq_api.deps import AsOfDep, PageDep, SessionDep
from econiq_api.errors import not_found
from econiq_api.schemas import (
    BottleneckOut,
    CritiqueOut,
    JournalEntryOut,
    ProcessDetailOut,
    ProcessStateOut,
    ProcessSummaryOut,
    ProcessTimelineOut,
    ProvenanceOut,
    StateFeatureOut,
    TimelineEntryOut,
)
from econiq_api.temporal import current_revision, recorded_by

router = APIRouter(prefix="/api/processes", tags=["processes"])


@router.get("", response_model=list[ProcessSummaryOut])
async def list_processes(
    session: SessionDep,
    page: PageDep,
    as_of: AsOfDep,
    status: Annotated[list[ProcessStatus] | None, Query()] = None,
    requires_review: Annotated[bool | None, Query()] = None,
) -> list[ProcessSummaryOut]:
    query: Select[tuple[Process]] = select(Process)
    query = current_revision(query, Process, as_of)
    if status:
        query = query.where(Process.status.in_(status))
    if requires_review is not None:
        query = query.where(Process.requires_review.is_(requires_review))

    rows = list(
        (
            await session.execute(
                query.order_by(Process.created_at.desc()).limit(page.limit).offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    states = await _latest_states(session, [row.process_id for row in rows], as_of)
    return [_summary(row, states.get(row.process_id)) for row in rows]


@router.get("/{process_id}", response_model=ProcessDetailOut)
async def get_process(
    process_id: uuid.UUID, session: SessionDep, as_of: AsOfDep
) -> ProcessDetailOut:
    process = await _load(session, process_id, as_of)
    if process is None:
        raise not_found("process", process_id)

    states = await _latest_states(session, [process_id], as_of)
    state = states.get(process_id)

    bottleneck_query: Select[tuple[Bottleneck]] = select(Bottleneck).where(
        Bottleneck.process_id == process_id, Bottleneck.resolved.is_(False)
    )
    bottlenecks = list(
        (await session.execute(current_revision(bottleneck_query, Bottleneck, as_of)))
        .scalars()
        .all()
    )

    critique_query: Select[tuple[Critique]] = select(Critique).where(
        Critique.subject_id == process_id, Critique.status == CritiqueStatus.OPEN
    )
    critiques = list(
        (
            await session.execute(
                recorded_by(critique_query, Critique, as_of).order_by(Critique.severity.desc())
            )
        )
        .scalars()
        .all()
    )

    supporting, contradicting = await _evidence_counts(session, process_id, as_of)

    # Features come along with the State rather than behind another call: a
    # state_confidence of 0.82 with no visible basis is exactly the unexplained
    # number this API is not supposed to return.
    features = await _features(session, [state.process_state_id] if state else [])
    attribution = await provenance.load(session, [state.agent_run_id] if state is not None else [])

    detail = _summary(process, state)
    return ProcessDetailOut(
        **detail.model_dump(),
        state=(
            _state_out(
                state,
                features.get(state.process_state_id, []),
                attribution.get(state.agent_run_id) if state.agent_run_id else None,
            )
            if state
            else None
        ),
        open_bottlenecks=[BottleneckOut.from_row(b) for b in bottlenecks],
        open_critiques=[CritiqueOut.from_row(c) for c in critiques],
        evidence_event_count=supporting,
        contradicting_event_count=contradicting,
    )


@router.get("/{process_id}/states", response_model=list[ProcessStateOut])
async def state_history(
    process_id: uuid.UUID, session: SessionDep, as_of: AsOfDep, page: PageDep
) -> list[ProcessStateOut]:
    """Append-only State history — the sequence *is* the record (ui_concept §32)."""
    query: Select[tuple[ProcessState]] = select(ProcessState).where(
        ProcessState.process_id == process_id
    )
    rows = list(
        (
            await session.execute(
                recorded_by(query, ProcessState, as_of)
                .order_by(ProcessState.observed_at.desc())
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    features = await _features(session, [row.process_state_id for row in rows])
    attribution = await provenance.load(session, (row.agent_run_id for row in rows))
    return [
        _state_out(
            row,
            features.get(row.process_state_id, []),
            attribution.get(row.agent_run_id) if row.agent_run_id else None,
        )
        for row in rows
    ]


@router.get("/{process_id}/timeline", response_model=ProcessTimelineOut)
async def timeline(
    process_id: uuid.UUID, session: SessionDep, as_of: AsOfDep, page: PageDep
) -> ProcessTimelineOut:
    """State changes, belief changes, evidence and critiques on one axis (#20).

    Three separate lists would leave the reader joining them by eye, and the
    join is the point: a belief change is only defensible next to the evidence
    that arrived just before it. The entries carry both dates — when the thing
    happened and when the system learned it — because a document published in
    July and ingested in August belongs in two different places depending on
    which question is being asked.
    """
    entries: list[TimelineEntryOut] = []

    state_query: Select[tuple[ProcessState]] = select(ProcessState).where(
        ProcessState.process_id == process_id
    )
    for row in (
        (await session.execute(recorded_by(state_query, ProcessState, as_of))).scalars().all()
    ):
        entries.append(
            TimelineEntryOut(
                kind="state",
                occurred_at=row.observed_at,
                recorded_at=row.recorded_at,
                title=row.categorical_state.value,
                detail=f"{row.archetype.value} at confidence {row.state_confidence:.2f}",
                subject_id=row.process_state_id,
                state_label=row.categorical_state,
            )
        )

    journal_query: Select[tuple[JournalEntry]] = select(JournalEntry).where(
        JournalEntry.subject_id == process_id
    )
    for row in (
        (await session.execute(recorded_by(journal_query, JournalEntry, as_of))).scalars().all()
    ):
        entries.append(
            TimelineEntryOut(
                kind="journal",
                occurred_at=row.observed_at,
                recorded_at=row.recorded_at,
                title=row.summary,
                detail=row.kind.value,
                subject_id=row.triggering_event_id,
                confidence_before=row.confidence_before,
                confidence_after=row.confidence_after,
            )
        )

    critique_query: Select[tuple[Critique]] = select(Critique).where(
        Critique.subject_id == process_id
    )
    for row in (
        (await session.execute(recorded_by(critique_query, Critique, as_of))).scalars().all()
    ):
        entries.append(
            TimelineEntryOut(
                kind="critique",
                occurred_at=row.observed_at,
                recorded_at=row.recorded_at,
                title=row.statement,
                detail=f"{row.kind.value}, severity {row.severity:.1f}",
                subject_id=row.critique_id,
                # A critique is evidence against the thesis surviving unchanged.
                supports=False,
            )
        )

    evidence_query = (
        select(EvidenceLink, Event)
        .join(Event, Event.event_id == EvidenceLink.evidence_id)
        .where(
            EvidenceLink.subject_id == process_id,
            EvidenceLink.retracted_at.is_(None),
            Event.valid_to.is_(None),
        )
    )
    if as_of is not None:
        evidence_query = evidence_query.where(EvidenceLink.created_at <= as_of)
    for link, event in (await session.execute(evidence_query)).all():
        entries.append(
            TimelineEntryOut(
                kind="evidence",
                occurred_at=event.occurred_at,
                recorded_at=link.created_at,
                title=event.title,
                detail=(
                    f"{event.independent_source_count} independent source(s), "
                    f"materiality {event.materiality:.1f}"
                ),
                subject_id=event.event_id,
                supports=link.supports,
            )
        )

    # Sorted by when it happened, not when it was learned: the axis the reader
    # is looking at is the world's, and `recorded_at` rides along so a replay
    # can still tell the difference.
    entries.sort(key=lambda entry: (entry.occurred_at, entry.recorded_at), reverse=True)
    return ProcessTimelineOut(
        process_id=process_id,
        entries=entries[page.offset : page.offset + page.limit],
    )


@router.get("/{process_id}/journal", response_model=list[JournalEntryOut])
async def journal(
    process_id: uuid.UUID, session: SessionDep, as_of: AsOfDep, page: PageDep
) -> list[JournalEntryOut]:
    """Why the system changed its mind, chronologically (PRD §21)."""
    query: Select[tuple[JournalEntry]] = select(JournalEntry).where(
        JournalEntry.subject_id == process_id
    )
    rows = (
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


@router.get("/{process_id}/critiques", response_model=list[CritiqueOut])
async def critiques(
    process_id: uuid.UUID,
    session: SessionDep,
    as_of: AsOfDep,
    status: Annotated[list[CritiqueStatus] | None, Query()] = None,
) -> list[CritiqueOut]:
    """Adversarial findings, including superseded ones.

    Addressed critiques are returned rather than hidden: a thesis that survived
    four attacks is stronger than one never attacked, and that is only visible
    if the attacks remain on the record.
    """
    query: Select[tuple[Critique]] = select(Critique).where(Critique.subject_id == process_id)
    if status:
        query = query.where(Critique.status.in_(status))
    rows = (
        (
            await session.execute(
                recorded_by(query, Critique, as_of).order_by(
                    Critique.observed_at.desc(), Critique.severity.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [CritiqueOut.from_row(row) for row in rows]


# --------------------------------------------------------------------------- #


async def _load(session: AsyncSession, process_id: uuid.UUID, as_of: object) -> Process | None:
    query: Select[tuple[Process]] = select(Process).where(Process.process_id == process_id)
    return (
        await session.execute(current_revision(query, Process, as_of))  # type: ignore[arg-type]
    ).scalar_one_or_none()


async def _latest_states(
    session: AsyncSession, process_ids: list[uuid.UUID], as_of: object
) -> dict[uuid.UUID, ProcessState]:
    """The State current as of the cut-off, per Process."""
    if not process_ids:
        return {}
    query: Select[tuple[ProcessState]] = select(ProcessState).where(
        ProcessState.process_id.in_(process_ids)
    )
    rows = (
        (
            await session.execute(
                recorded_by(query, ProcessState, as_of).order_by(  # type: ignore[arg-type]
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


async def _features(
    session: AsyncSession, state_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ProcessStateFeature]]:
    if not state_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(ProcessStateFeature).where(
                    ProcessStateFeature.process_state_id.in_(state_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[ProcessStateFeature]] = {}
    for row in rows:
        grouped.setdefault(row.process_state_id, []).append(row)
    return grouped


async def _evidence_counts(
    session: AsyncSession, process_id: uuid.UUID, as_of: object
) -> tuple[int, int]:
    query = (
        select(EvidenceLink.supports, func.count())
        .where(EvidenceLink.subject_id == process_id, EvidenceLink.retracted_at.is_(None))
        .group_by(EvidenceLink.supports)
    )
    if as_of is not None:
        query = query.where(EvidenceLink.created_at <= as_of)
    counts = {row[0]: row[1] for row in (await session.execute(query)).all()}
    return counts.get(True, 0), counts.get(False, 0)


def _summary(process: Process, state: ProcessState | None) -> ProcessSummaryOut:
    return ProcessSummaryOut(
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
    )


def _state_out(
    state: ProcessState,
    features: list[ProcessStateFeature] | None = None,
    attribution: ProvenanceOut | None = None,
) -> ProcessStateOut:
    return ProcessStateOut(
        id=state.process_state_id,
        archetype=state.archetype,
        categorical_state=state.categorical_state,
        state_confidence=state.state_confidence,
        observed_at=state.observed_at,
        recorded_at=state.recorded_at,
        features=[
            StateFeatureOut(name=f.name, value=f.value, basis=f.basis.value, rationale=f.rationale)
            for f in (features or [])
        ],
        transition_beliefs=dict(state.transition_beliefs),
        transition_indicators=list(state.transition_indicators),
        reversal_indicators=list(state.reversal_indicators),
        provenance=attribution,
    )


ENTITY = EntityType.PROCESS
