"""Persisting Processes and the journal that explains them.

Two things are written for every change:

* the **revision**, which is what the system now believes, and
* the **journal entry**, which is why it changed its mind (PRD §21).

The first can be queried; the second can be read. A graph that can be
reconstructed but not explained fails the transparency the PRD asks for, so
neither is optional.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from econiq_data_models import JournalEntry, JournalEntryKind, Node, Process
from econiq_ontology import EntityType, ProcessStatus, utcnow
from econiq_schemas import ProcessUpdateOutput, ProposedProcess
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SLUG_SUFFIX = re.compile(r"-(\d+)$")


@dataclass(frozen=True, slots=True)
class PersistedProcess:
    process_id: uuid.UUID
    revision: int
    slug: str
    created: bool
    requires_review: bool = False


@dataclass(frozen=True, slots=True)
class AppliedUpdate:
    """What an update actually changed."""

    process_id: uuid.UUID
    revision: int
    confidence_before: float | None
    confidence_after: float
    belief_changes: int
    feature_deltas: dict[str, float] = field(default_factory=dict)
    state_change_recommended: bool = False
    journal_entry_id: uuid.UUID | None = None

    @property
    def changed(self) -> bool:
        return bool(self.belief_changes or self.feature_deltas)


class ProcessWriter:
    """Creates Processes, applies deltas, and journals both."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def create(
        self,
        proposed: ProposedProcess,
        *,
        agent_run_id: uuid.UUID,
        observed_at: datetime,
        triggering_event_id: uuid.UUID | None = None,
    ) -> PersistedProcess:
        """Create a Process as a review-flagged candidate.

        New Processes start as ``candidate`` and flagged for review: a false
        Process contaminates everything downstream of it (agent doc §23). The
        flag is a signal, not a gate — Phase 0 has no reviewer, and blocking on
        one nobody has assigned would just stop the pipeline.
        """
        async with self.session_factory() as session:
            slug = await self._unique_slug(session, proposed.slug)

        process_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(Node(node_id=process_id, node_type=EntityType.PROCESS, slug=slug))
            await session.flush()
            session.add(
                Process(
                    process_id=process_id,
                    revision=1,
                    name=proposed.name,
                    slug=slug,
                    description=proposed.description,
                    archetype=None,  # classification is the Archetype agent's job (#9)
                    status=ProcessStatus.CANDIDATE,
                    requires_review=True,
                    agent_run_id=agent_run_id,
                )
            )
            session.add(
                JournalEntry(
                    subject_id=process_id,
                    subject_type=EntityType.PROCESS,
                    kind=JournalEntryKind.CREATED,
                    observed_at=observed_at,
                    summary=f"Process created from evidence: {proposed.causal_mechanism}",
                    confidence_after=proposed.confidence,
                    changes=[
                        {
                            "direction": "created",
                            "statement": proposed.name,
                            "rationale": proposed.causal_mechanism,
                        }
                    ],
                    triggering_event_id=triggering_event_id,
                    agent_run_id=agent_run_id,
                )
            )
            session.add(
                JournalEntry(
                    subject_id=process_id,
                    subject_type=EntityType.PROCESS,
                    kind=JournalEntryKind.REVIEW_REQUESTED,
                    observed_at=observed_at,
                    summary="Awaiting human review of a newly discovered Process.",
                    changes=[],
                    triggering_event_id=triggering_event_id,
                    agent_run_id=agent_run_id,
                )
            )
            await session.commit()

        return PersistedProcess(
            process_id=process_id, revision=1, slug=slug, created=True, requires_review=True
        )

    async def apply_update(
        self,
        process_id: uuid.UUID,
        output: ProcessUpdateOutput,
        *,
        agent_run_id: uuid.UUID,
        observed_at: datetime,
        triggering_event_id: uuid.UUID | None = None,
    ) -> AppliedUpdate:
        """Apply a delta as a new revision plus a journal entry.

        Feature deltas and any recommended State change are *not* applied here.
        They are carried in the journal and in the agent run for the Process
        State agent (#9), which owns the State layer. Writing a State from this
        agent would put the same object under two owners.
        """
        deltas = {delta.name: delta.delta for delta in output.feature_deltas}

        async with self.session_factory() as session:
            current = await self._current(session, process_id)
            if current is None:
                raise LookupError(f"cannot update unknown process {process_id}")

            previous_confidence = await self._last_confidence(session, process_id)

            if not (output.belief_changes or deltas or output.state_change_recommended):
                # Nothing changed. Recording a revision anyway would inflate the
                # history and make "how often did this Process actually move?"
                # unanswerable.
                entry = JournalEntry(
                    subject_id=process_id,
                    subject_type=EntityType.PROCESS,
                    kind=JournalEntryKind.EVIDENCE_ADDED,
                    observed_at=observed_at,
                    summary="Evidence accumulated; no belief changed.",
                    confidence_before=previous_confidence,
                    confidence_after=output.confidence_after,
                    changes=[],
                    triggering_event_id=triggering_event_id,
                    agent_run_id=agent_run_id,
                )
                session.add(entry)
                await session.commit()
                return AppliedUpdate(
                    process_id=process_id,
                    revision=current.revision,
                    confidence_before=previous_confidence,
                    confidence_after=output.confidence_after,
                    belief_changes=0,
                    journal_entry_id=entry.journal_entry_id,
                )

            closed_at = utcnow()
            await session.execute(
                update(Process)
                .where(Process.process_id == process_id, Process.valid_to.is_(None))
                .values(valid_to=closed_at)
            )
            revision = current.revision + 1
            row = Process(
                process_id=process_id,
                revision=revision,
                name=current.name,
                slug=current.slug,
                description=current.description,
                archetype=current.archetype,
                archetype_confidence=current.archetype_confidence,
                # Evidence that changes beliefs promotes a candidate to active:
                # the development is real enough to have moved twice.
                status=(
                    ProcessStatus.ACTIVE
                    if current.status is ProcessStatus.CANDIDATE
                    else current.status
                ),
                merged_into=current.merged_into,
                requires_review=current.requires_review,
                agent_run_id=agent_run_id,
            )
            row.valid_from = closed_at
            session.add(row)

            entry = JournalEntry(
                subject_id=process_id,
                subject_type=EntityType.PROCESS,
                kind=JournalEntryKind.BELIEF_CHANGE,
                observed_at=observed_at,
                summary=_summarize(output),
                confidence_before=previous_confidence,
                confidence_after=output.confidence_after,
                changes=[
                    *(
                        {
                            "direction": change.direction,
                            "statement": change.statement,
                            "rationale": change.rationale,
                        }
                        for change in output.belief_changes
                    ),
                    *(
                        {
                            "direction": "feature",
                            "statement": f"{name} {value:+.2f}",
                            "rationale": next(
                                d.rationale for d in output.feature_deltas if d.name == name
                            ),
                        }
                        for name, value in deltas.items()
                    ),
                ],
                triggering_event_id=triggering_event_id,
                agent_run_id=agent_run_id,
            )
            session.add(entry)
            await session.commit()

        return AppliedUpdate(
            process_id=process_id,
            revision=revision,
            confidence_before=previous_confidence,
            confidence_after=output.confidence_after,
            belief_changes=len(output.belief_changes),
            feature_deltas=deltas,
            state_change_recommended=output.state_change_recommended,
            journal_entry_id=entry.journal_entry_id,
        )

    async def journal(self, process_id: uuid.UUID) -> list[JournalEntry]:
        """The chronological record for a Process, oldest first."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(JournalEntry)
                .where(JournalEntry.subject_id == process_id)
                .order_by(JournalEntry.observed_at, JournalEntry.recorded_at)
            )
            return list(result.scalars().all())

    async def _current(self, session: AsyncSession, process_id: uuid.UUID) -> Process | None:
        result = await session.execute(
            select(Process).where(Process.process_id == process_id, Process.valid_to.is_(None))
        )
        return result.scalar_one_or_none()

    async def _last_confidence(self, session: AsyncSession, process_id: uuid.UUID) -> float | None:
        result = await session.execute(
            select(JournalEntry.confidence_after)
            .where(
                JournalEntry.subject_id == process_id,
                JournalEntry.confidence_after.is_not(None),
            )
            .order_by(JournalEntry.recorded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _unique_slug(self, session: AsyncSession, slug: str) -> str:
        """Slugs identify a Process to humans, so collisions get a suffix.

        A collision usually means the agent proposed a Process that already
        exists — the caller checks that first. This is the backstop that keeps a
        race from failing the write.
        """
        taken = set(
            (
                await session.execute(
                    select(Node.slug).where(
                        Node.node_type == EntityType.PROCESS, Node.slug.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        if slug not in taken:
            return slug
        base = _SLUG_SUFFIX.sub("", slug)
        suffix = 2
        while f"{base}-{suffix}" in taken:
            suffix += 1
        return f"{base}-{suffix}"


def _summarize(output: ProcessUpdateOutput) -> str:
    """A one-line summary in the shape PRD §21 shows."""
    strengthened = sum(1 for c in output.belief_changes if c.direction == "strengthened")
    weakened = sum(1 for c in output.belief_changes if c.direction == "weakened")
    parts: list[str] = []
    if strengthened:
        parts.append(f"+{strengthened} strengthened")
    if weakened:
        parts.append(f"−{weakened} weakened")
    if output.feature_deltas:
        parts.append(
            ", ".join(
                f"{d.name} {d.delta:+.2f}"
                for d in sorted(output.feature_deltas, key=lambda d: d.name)
            )
        )
    if output.state_change_recommended and output.proposed_state:
        parts.append(f"state change proposed → {output.proposed_state.value}")
    if output.contradicts_existing_beliefs:
        parts.append("contradicts existing beliefs")
    return "; ".join(parts) if parts else "no change"
