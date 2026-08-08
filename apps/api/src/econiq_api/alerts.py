"""Semantic alerts (issue #32, PRD §20; ui_concept §19, §26).

Monitoring that watches the thesis rather than the price. The system already
records every change worth alerting on — a State moved, a Bottleneck stopped
binding, evidence arrived against a Process, a critique opened — so alerts are
*derived* from those rows rather than emitted at write time and stored.

Derived rather than stored, for two reasons. Point-in-time reads come free: ask
for alerts as of July and you get the alerts that existed in July, because the
rows they are computed from are versioned. And an alert whose underlying change
was later superseded stops existing rather than lingering as a notification
about something that is no longer true.

The identifier is deterministic — derived from the change, not generated — so
the same State transition never alerts twice however often this runs. That is
what makes a read-time derivation safe to poll.

**No price alerts, by construction.** There is no market data in the system yet
(#77), but the rule outlives that: PRD §20 asks for monitoring of thesis
integrity, and a feed that mixes "the binding constraint may be resolving" with
"XYZ fell 5%" trains the reader to skim both.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from econiq_data_models import (
    Bottleneck,
    Critique,
    EvidenceLink,
    JournalEntry,
    Process,
    ProcessState,
)
from econiq_ontology import CritiqueStatus, EntityType, utcnow
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from econiq_api.schemas import AlertOut, NodeRef
from econiq_api.temporal import current_revision, recorded_by

#: How far back a "recent change" reaches. Longer than the pipeline's cadence so
#: nothing is missed between runs, short enough that the feed is about now.
DEFAULT_WINDOW = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class AlertKind:
    """One class of thesis change, with the copy that describes it."""

    name: str
    severity: str


#: The classes PRD §20 lists, as far as Phase 0's graph can detect them.
STATE_TRANSITION = AlertKind("state_transition", "notable")
THESIS_WEAKENED = AlertKind("thesis_weakened", "urgent")
THESIS_STRENGTHENED = AlertKind("thesis_strengthened", "informational")
CONTRADICTING_EVIDENCE = AlertKind("contradicting_evidence", "urgent")
BOTTLENECK_RESOLVING = AlertKind("bottleneck_resolving", "notable")
BOTTLENECK_EMERGED = AlertKind("bottleneck_emerged", "notable")
CRITIQUE_OPENED = AlertKind("critique_opened", "notable")

#: Named because a caller should be able to render "not monitored yet" rather
#: than infer from an empty feed that nothing happened.
UNAVAILABLE_KINDS: tuple[tuple[str, str], ...] = (
    (
        "exposure_change",
        "Needs Asset exposure revisions to be diffed over time; the rows exist "
        "but nothing compares them yet.",
    ),
    (
        "price_or_positioning",
        "Deliberately absent. PRD §20 asks for thesis monitoring, and mixing "
        "price moves into this feed teaches the reader to skim it.",
    ),
)


def _identifier(*parts: object) -> str:
    """Deterministic id, so the same change never alerts twice."""
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()
    return digest[:24]


async def generate(
    session: AsyncSession,
    *,
    as_of: datetime | None = None,
    process_ids: Sequence[uuid.UUID] | None = None,
    window: timedelta = DEFAULT_WINDOW,
) -> list[AlertOut]:
    """Every thesis change in the window, newest first."""
    cut = as_of or utcnow()
    since = cut - window

    query: Select[tuple[Process]] = select(Process)
    query = current_revision(query, Process, as_of)
    if process_ids:
        query = query.where(Process.process_id.in_(process_ids))
    processes = {row.process_id: row for row in (await session.execute(query)).scalars().all()}
    if not processes:
        return []

    alerts: list[AlertOut] = []
    alerts += await _state_transitions(session, processes, as_of, since, cut)
    alerts += await _belief_changes(session, processes, as_of, since, cut)
    alerts += await _contradicting_evidence(session, processes, since, cut)
    alerts += await _bottleneck_changes(session, processes, as_of, since, cut)
    alerts += await _critiques(session, processes, as_of, since, cut)

    alerts.sort(key=lambda alert: alert.observed_at, reverse=True)
    return alerts


def _ref(process: Process) -> NodeRef:
    return NodeRef(
        id=process.process_id,
        type=EntityType.PROCESS,
        label=process.name,
        slug=process.slug,
    )


async def _state_transitions(
    session: AsyncSession,
    processes: dict[uuid.UUID, Process],
    as_of: datetime | None,
    since: datetime,
    cut: datetime,
) -> list[AlertOut]:
    """A State that moved — the change the whole model is organised around."""
    query: Select[tuple[ProcessState]] = select(ProcessState).where(
        ProcessState.process_id.in_(processes)
    )
    rows = (
        (
            await session.execute(
                recorded_by(query, ProcessState, as_of).order_by(
                    ProcessState.process_id,
                    ProcessState.observed_at.desc(),
                    ProcessState.recorded_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )

    latest: dict[uuid.UUID, list[ProcessState]] = {}
    for row in rows:
        latest.setdefault(row.process_id, []).append(row)

    alerts: list[AlertOut] = []
    for process_id, history in latest.items():
        # A transition needs two observations with different labels. One
        # observation is a Process being classified, which is not a transition
        # and would fire on every new Process.
        if len(history) < 2:
            continue
        current, previous = history[0], history[1]
        if current.categorical_state == previous.categorical_state:
            continue
        if not (since <= current.recorded_at <= cut):
            continue
        process = processes[process_id]
        alerts.append(
            AlertOut(
                id=_identifier("state", process_id, current.process_state_id),
                kind=STATE_TRANSITION.name,
                severity=STATE_TRANSITION.severity,
                subject=_ref(process),
                headline=(
                    f"{process.name} moved to {current.categorical_state.value.replace('_', ' ')}"
                ),
                detail=(
                    f"From {previous.categorical_state.value.replace('_', ' ')}, "
                    f"at confidence {current.state_confidence:.2f} on the "
                    f"{current.archetype.value.replace('_', ' ')} machine."
                ),
                observed_at=current.observed_at,
                confidence_before=previous.state_confidence,
                confidence_after=current.state_confidence,
            )
        )
    return alerts


async def _belief_changes(
    session: AsyncSession,
    processes: dict[uuid.UUID, Process],
    as_of: datetime | None,
    since: datetime,
    cut: datetime,
) -> list[AlertOut]:
    """Journal entries where confidence moved, in either direction.

    Strengthening is informational and weakening is urgent, which is the whole
    asymmetry: a thesis getting better is something to read on Friday, and a
    thesis losing support is something to read now.
    """
    query: Select[tuple[JournalEntry]] = select(JournalEntry).where(
        JournalEntry.subject_id.in_(processes),
        JournalEntry.confidence_before.is_not(None),
        JournalEntry.confidence_after.is_not(None),
    )
    rows = (await session.execute(recorded_by(query, JournalEntry, as_of))).scalars().all()

    alerts: list[AlertOut] = []
    for row in rows:
        if not (since <= row.recorded_at <= cut):
            continue
        before, after = row.confidence_before, row.confidence_after
        assert before is not None and after is not None
        delta = after - before
        # A rounding-sized move is not a change of mind.
        if abs(delta) < 0.02:
            continue
        weakened = delta < 0
        kind = THESIS_WEAKENED if weakened else THESIS_STRENGTHENED
        process = processes[row.subject_id]
        alerts.append(
            AlertOut(
                id=_identifier("belief", row.journal_entry_id),
                kind=kind.name,
                severity=kind.severity,
                subject=_ref(process),
                headline=(
                    f"{process.name} {'weakened' if weakened else 'strengthened'} "
                    f"({before:.2f} → {after:.2f})"
                ),
                detail=row.summary,
                observed_at=row.observed_at,
                evidence_id=row.triggering_event_id,
                confidence_before=before,
                confidence_after=after,
            )
        )
    return alerts


async def _contradicting_evidence(
    session: AsyncSession,
    processes: dict[uuid.UUID, Process],
    since: datetime,
    cut: datetime,
) -> list[AlertOut]:
    """Evidence arriving *against* a thesis.

    Urgent regardless of how much supporting evidence exists. Contradiction is a
    scored dimension rather than a deduction (ontology §17), and the reader is
    the one who decides whether it outweighs.
    """
    rows = (
        (
            await session.execute(
                select(EvidenceLink).where(
                    EvidenceLink.subject_id.in_(processes),
                    EvidenceLink.supports.is_(False),
                    EvidenceLink.retracted_at.is_(None),
                    EvidenceLink.created_at >= since,
                    EvidenceLink.created_at <= cut,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        AlertOut(
            id=_identifier("against", row.evidence_link_id),
            kind=CONTRADICTING_EVIDENCE.name,
            severity=CONTRADICTING_EVIDENCE.severity,
            subject=_ref(processes[row.subject_id]),
            headline=f"Evidence recorded against {processes[row.subject_id].name}",
            detail=(
                "Contradicting evidence is kept and scored rather than netted "
                "off the supporting count."
            ),
            observed_at=row.created_at,
            evidence_id=row.evidence_id,
        )
        for row in rows
    ]


async def _bottleneck_changes(
    session: AsyncSession,
    processes: dict[uuid.UUID, Process],
    as_of: datetime | None,
    since: datetime,
    cut: datetime,
) -> list[AlertOut]:
    """A constraint that stopped binding, or a new one that started.

    "Potentially resolving" rather than "resolved": the system observes that a
    Bottleneck stopped binding, which is a change in the model's belief, not a
    fact about the world.
    """
    query: Select[tuple[Bottleneck]] = select(Bottleneck).where(
        Bottleneck.process_id.in_(processes)
    )
    rows = (await session.execute(current_revision(query, Bottleneck, as_of))).scalars().all()

    alerts: list[AlertOut] = []
    for row in rows:
        if not (since <= row.created_at <= cut):
            continue
        process = processes[row.process_id]
        if row.resolved or not row.currently_binding:
            kind, headline = (
                BOTTLENECK_RESOLVING,
                f"Bottleneck potentially resolving: {row.name}",
            )
            detail = (
                "It is no longer recorded as binding. That is a change in the "
                "model's reading, not a fact about the world."
            )
        elif row.revision == 1:
            kind, headline = (
                BOTTLENECK_EMERGED,
                f"New binding constraint on {process.name}: {row.name}",
            )
            detail = row.description
        else:
            continue
        alerts.append(
            AlertOut(
                id=_identifier("bottleneck", row.bottleneck_id, row.revision),
                kind=kind.name,
                severity=kind.severity,
                subject=_ref(process),
                headline=headline,
                detail=detail,
                observed_at=row.created_at,
            )
        )
    return alerts


async def _critiques(
    session: AsyncSession,
    processes: dict[uuid.UUID, Process],
    as_of: datetime | None,
    since: datetime,
    cut: datetime,
) -> list[AlertOut]:
    """A new open critique, weighted by how damaging the Critic thought it was."""
    query: Select[tuple[Critique]] = select(Critique).where(
        Critique.subject_id.in_(processes), Critique.status == CritiqueStatus.OPEN
    )
    rows = (await session.execute(recorded_by(query, Critique, as_of))).scalars().all()
    return [
        AlertOut(
            id=_identifier("critique", row.critique_id),
            kind=CRITIQUE_OPENED.name,
            severity="urgent" if row.is_most_damaging else CRITIQUE_OPENED.severity,
            subject=_ref(processes[row.subject_id]),
            headline=f"New critique of {processes[row.subject_id].name}",
            detail=row.statement,
            observed_at=row.observed_at,
        )
        for row in rows
        if since <= row.recorded_at <= cut
    ]
