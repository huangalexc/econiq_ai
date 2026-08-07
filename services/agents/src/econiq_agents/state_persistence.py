"""Persisting Archetype classifications and Process States.

A State estimate is an observation, so it is appended, never updated: the
sequence of rows *is* the State history, which is what makes "why did the system
believe this on July 14?" answerable (ui_concept §32) and what Phase 2's
historical State snapshots read.

An Archetype classification is a property of the Process, so it writes a Process
revision — and reclassifying a Process that already has State history is treated
as the serious event it is, because every past State label was drawn from the
old machine's vocabulary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from econiq_data_models import (
    JournalEntry,
    JournalEntryKind,
    Process,
    ProcessState,
    ProcessStateFeature,
    ValueBasis,
)
from econiq_ontology import EntityType, ProcessArchetype, ProcessStateLabel, states_for, utcnow
from econiq_schemas import ProcessArchetypeOutput, ProcessStateOutput
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.state_agents import TransitionSignificance, classify_transition


@dataclass(frozen=True, slots=True)
class AppliedArchetype:
    process_id: uuid.UUID
    revision: int
    archetype: ProcessArchetype
    reclassified: bool = False
    invalidated_states: int = 0
    """State observations whose vocabulary the reclassification orphaned."""


@dataclass(frozen=True, slots=True)
class RecordedState:
    process_state_id: uuid.UUID
    process_id: uuid.UUID
    categorical_state: ProcessStateLabel
    confidence: float
    transition: TransitionSignificance
    features: dict[str, float] = field(default_factory=dict)
    measured: tuple[str, ...] = ()
    requires_review: bool = False


class StateWriter:
    """Writes Archetype classifications and State observations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def apply_archetype(
        self,
        process_id: uuid.UUID,
        output: ProcessArchetypeOutput,
        *,
        agent_run_id: uuid.UUID,
        observed_at: datetime,
    ) -> AppliedArchetype:
        async with self.session_factory() as session:
            current = await self._current_process(session, process_id)
            if current is None:
                raise LookupError(f"cannot classify unknown process {process_id}")

            previous = current.archetype
            reclassified = previous is not None and previous is not output.primary_archetype
            orphaned = await self._state_count(session, process_id) if reclassified else 0

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
                archetype=output.primary_archetype,
                archetype_confidence=output.confidence,
                status=current.status,
                merged_into=current.merged_into,
                # Reclassification invalidates every State label already
                # recorded, so it goes back in front of a human (agent doc §23).
                requires_review=current.requires_review or reclassified,
                agent_run_id=agent_run_id,
            )
            row.valid_from = closed_at
            session.add(row)

            summary = (
                f"Archetype classified as {output.primary_archetype.value}"
                if not reclassified
                else (
                    f"Archetype reclassified {previous.value if previous else 'none'} → "
                    f"{output.primary_archetype.value}; {orphaned} prior State "
                    "observation(s) use the old vocabulary"
                )
            )
            session.add(
                JournalEntry(
                    subject_id=process_id,
                    subject_type=EntityType.PROCESS,
                    kind=JournalEntryKind.BELIEF_CHANGE,
                    observed_at=observed_at,
                    summary=summary,
                    confidence_after=output.confidence,
                    changes=[
                        {
                            "direction": "classified",
                            "statement": output.primary_archetype.value,
                            "rationale": output.reasons,
                        },
                        *(
                            {
                                "direction": "rejected",
                                "statement": rejected.archetype.value,
                                "rationale": rejected.reason,
                            }
                            for rejected in output.rejected
                        ),
                    ],
                    agent_run_id=agent_run_id,
                )
            )
            await session.commit()

        return AppliedArchetype(
            process_id=process_id,
            revision=revision,
            archetype=output.primary_archetype,
            reclassified=reclassified,
            invalidated_states=orphaned,
        )

    async def record_state(
        self,
        process_id: uuid.UUID,
        output: ProcessStateOutput,
        *,
        agent_run_id: uuid.UUID,
        observed_at: datetime,
        measured_features: dict[str, float] | None = None,
        triggering_event_id: uuid.UUID | None = None,
    ) -> RecordedState:
        """Append a State observation and journal any transition.

        ``basis`` is assigned here rather than taken from the agent: a feature
        the agent was given a measurement for is ``measured``, everything else
        is ``estimated``. Letting the model label its own estimates as
        measurements would erase the distinction ontology §2.4 rests on.
        """
        measured = measured_features or {}

        async with self.session_factory() as session:
            previous = await self._latest_state(session, process_id)
            # Only a State from the *same* Archetype is comparable. After a
            # reclassification the recorded label belongs to a machine the new
            # one does not contain, so there is no transition to measure — the
            # chain is still linked through `previous_state_id` for audit.
            comparable = (
                previous
                if previous is not None and previous.archetype is output.archetype
                else None
            )
            prior_label = comparable.categorical_state if comparable else None
            transition = classify_transition(
                states_for(output.archetype), prior_label, output.categorical_state
            )

            state_id = uuid.uuid4()
            session.add(
                ProcessState(
                    process_state_id=state_id,
                    process_id=process_id,
                    observed_at=observed_at,
                    archetype=output.archetype,
                    categorical_state=output.categorical_state,
                    state_confidence=output.state_confidence,
                    transition_beliefs={
                        label.value: belief for label, belief in output.transition_beliefs.items()
                    },
                    transition_indicators=list(output.transition_indicators),
                    reversal_indicators=list(output.reversal_indicators),
                    previous_state_id=previous.process_state_id if previous else None,
                    agent_run_id=agent_run_id,
                )
            )
            await session.flush()
            for feature in output.features:
                session.add(
                    ProcessStateFeature(
                        process_state_id=state_id,
                        name=feature.name,
                        value=feature.value,
                        basis=(
                            ValueBasis.MEASURED
                            if feature.name in measured
                            else ValueBasis.ESTIMATED
                        ),
                        rationale=feature.rationale,
                    )
                )

            if transition.changed:
                session.add(
                    JournalEntry(
                        subject_id=process_id,
                        subject_type=EntityType.PROCESS,
                        kind=JournalEntryKind.STATE_CHANGE,
                        observed_at=observed_at,
                        summary=(
                            f"State {prior_label.value if prior_label else 'none'} → "
                            f"{output.categorical_state.value}"
                            + (" (reversal)" if transition.backwards else "")
                        ),
                        confidence_before=comparable.state_confidence if comparable else None,
                        confidence_after=output.state_confidence,
                        changes=[
                            {
                                "direction": "state",
                                "statement": output.categorical_state.value,
                                "rationale": "; ".join(output.transition_indicators)
                                or "no transition indicators given",
                            }
                        ],
                        triggering_event_id=triggering_event_id,
                        agent_run_id=agent_run_id,
                    )
                )
                if transition.major:
                    await session.execute(
                        update(Process)
                        .where(Process.process_id == process_id, Process.valid_to.is_(None))
                        .values(requires_review=True)
                    )
            await session.commit()

        return RecordedState(
            process_state_id=state_id,
            process_id=process_id,
            categorical_state=output.categorical_state,
            confidence=output.state_confidence,
            transition=transition,
            features={feature.name: feature.value for feature in output.features},
            measured=tuple(feature.name for feature in output.features if feature.name in measured),
            requires_review=transition.major,
        )

    async def state_history(self, process_id: uuid.UUID) -> list[ProcessState]:
        """State observations for a Process, oldest first."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ProcessState)
                .where(ProcessState.process_id == process_id)
                .order_by(ProcessState.observed_at, ProcessState.recorded_at)
            )
            return list(result.scalars().all())

    async def latest_features(self, process_id: uuid.UUID) -> dict[str, float]:
        """Feature values from the most recent State observation."""
        async with self.session_factory() as session:
            latest = await self._latest_state(session, process_id)
            if latest is None:
                return {}
            rows = (
                await session.execute(
                    select(ProcessStateFeature.name, ProcessStateFeature.value).where(
                        ProcessStateFeature.process_state_id == latest.process_state_id
                    )
                )
            ).all()
        return {row.name: row.value for row in rows}

    async def _current_process(
        self, session: AsyncSession, process_id: uuid.UUID
    ) -> Process | None:
        result = await session.execute(
            select(Process).where(Process.process_id == process_id, Process.valid_to.is_(None))
        )
        return result.scalar_one_or_none()

    async def _latest_state(
        self, session: AsyncSession, process_id: uuid.UUID
    ) -> ProcessState | None:
        result = await session.execute(
            select(ProcessState)
            .where(ProcessState.process_id == process_id)
            .order_by(ProcessState.observed_at.desc(), ProcessState.recorded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _state_count(self, session: AsyncSession, process_id: uuid.UUID) -> int:
        result = await session.execute(
            select(ProcessState.process_state_id).where(ProcessState.process_id == process_id)
        )
        return len(result.scalars().all())
