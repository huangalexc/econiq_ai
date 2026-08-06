"""The Process → Archetype → State stage (issue #9).

Ordered, because the order is the point: a Process without an Archetype has no
State vocabulary, so classification runs first and State estimation is skipped
entirely rather than guessed at.

::

    Process
      → Archetype agent (once, or on reclassification)
      → State agent, constrained to that Archetype's machine
      → append-only ProcessState + features + journal entry

The work is triggered by the signal issue #8 carries: a Process whose beliefs
moved since its last State observation is stale, and nothing else is re-estimated
(ontology §46).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from econiq_data_models import (
    Claim,
    Event,
    EventClaim,
    EvidenceLink,
    JournalEntry,
    JournalEntryKind,
    Process,
    ProcessState,
)
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import ProcessArchetype, ProcessStateLabel, ProcessStatus, states_for
from econiq_schemas import (
    ProcessArchetypeInput,
    ProcessStateInput,
    ProcessSummary,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.prompts import PROCESS_ARCHETYPE_V1, PROCESS_STATE_V1
from econiq_agents.state_agents import ProcessArchetypeAgent, ProcessStateAgent
from econiq_agents.state_persistence import AppliedArchetype, RecordedState, StateWriter

logger = logging.getLogger("econiq.agents.state")

#: How much evidence to put in front of the classifier and the State agent.
#: Both judge a developmental pattern, which needs several Events to be visible
#: at all, but not the whole history.
MAX_EVIDENCE_EVENTS = 12


@dataclass(frozen=True, slots=True)
class StateOutcome:
    process_id: uuid.UUID
    archetype: AppliedArchetype | None = None
    state: RecordedState | None = None
    archetype_run_id: uuid.UUID | None = None
    state_run_id: uuid.UUID | None = None
    skipped_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def state_changed(self) -> bool:
        return self.state is not None and self.state.transition.changed

    @property
    def requires_review(self) -> bool:
        """Major transitions and reclassifications go back to a human."""
        return (self.state is not None and self.state.requires_review) or (
            self.archetype is not None and self.archetype.reclassified
        )


class ProcessStateStage:
    """Classifies Processes and estimates where they sit in their lifecycle."""

    def __init__(
        self,
        service: LLMService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.classifier = ProcessArchetypeAgent(service)
        self.estimator = ProcessStateAgent(service)
        self.writer = StateWriter(session_factory)
        self.runs = AgentRunRecorder(session_factory)

    async def run_pending(self, *, limit: int = 10) -> list[StateOutcome]:
        """Classify and re-estimate every Process that needs it."""
        outcomes: list[StateOutcome] = []
        for process_id in await self._pending_process_ids(limit):
            outcomes.append(await self.run(process_id))
        return outcomes

    async def run(
        self, process_id: uuid.UUID, *, triggering_event_id: uuid.UUID | None = None
    ) -> StateOutcome:
        process = await self._load(process_id)
        if process is None:
            return StateOutcome(process_id=process_id, skipped_reason="process not found")

        evidence, claim_texts = await self._evidence(process_id)
        as_of = await self._as_of(process_id) or process.created_at
        notes: list[str] = []

        applied: AppliedArchetype | None = None
        archetype_run_id: uuid.UUID | None = None
        if process.archetype is None:
            applied, archetype_run_id = await self._classify(
                process, evidence, claim_texts, as_of=as_of
            )
            if applied is None:
                return StateOutcome(
                    process_id=process_id,
                    skipped_reason="archetype classification failed",
                    archetype_run_id=archetype_run_id,
                )
            archetype = applied.archetype
        else:
            archetype = process.archetype

        summary = ProcessSummary(
            process_id=str(process_id),
            name=process.name,
            description=process.description,
            archetype=archetype,
        )
        prior = await self._prior_state(process_id, archetype, notes)
        measured = await self.writer.latest_features(process_id)

        payload = ProcessStateInput(
            as_of=as_of,
            process=summary,
            archetype=archetype,
            permitted_states=list(states_for(archetype)),
            measured_features=measured,
            claim_texts=claim_texts,
            prior_state=prior,
        )
        try:
            estimate = await self.estimator.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("state estimation failed for %s: %s", process_id, exc)
            return StateOutcome(
                process_id=process_id,
                archetype=applied,
                archetype_run_id=archetype_run_id,
                skipped_reason=str(exc),
                notes=notes,
            )

        state_run_id = await self.runs.record(
            estimate,
            payload=payload,
            prompt=PROCESS_STATE_V1,
            ontology_layer=self.estimator.ontology_layer,
            provider=self.service.provider.name,
            trigger_event_id=triggering_event_id,
        )
        if not estimate.evaluation.passed:
            # An illegal transition or a contradicted measurement is not a State
            # the graph should hold. The run is kept as the record of what was
            # proposed and why it was refused.
            failures = "; ".join(
                check.detail or check.name for check in estimate.evaluation.failures
            )
            logger.warning("refusing state estimate for %s: %s", process_id, failures)
            return StateOutcome(
                process_id=process_id,
                archetype=applied,
                archetype_run_id=archetype_run_id,
                state_run_id=state_run_id,
                skipped_reason=f"state estimate rejected: {failures}",
                notes=notes,
            )

        recorded = await self.writer.record_state(
            process_id,
            estimate.output,
            agent_run_id=state_run_id,
            observed_at=as_of,
            measured_features=measured,
            triggering_event_id=triggering_event_id,
        )
        return StateOutcome(
            process_id=process_id,
            archetype=applied,
            state=recorded,
            archetype_run_id=archetype_run_id,
            state_run_id=state_run_id,
            notes=notes,
        )

    async def _classify(
        self,
        process: Process,
        evidence: list[str],
        claim_texts: dict[str, str],
        *,
        as_of: datetime,
    ) -> tuple[AppliedArchetype | None, uuid.UUID | None]:
        payload = ProcessArchetypeInput(
            as_of=as_of,
            process=ProcessSummary(
                process_id=str(process.process_id),
                name=process.name,
                description=process.description,
            ),
            recent_event_summaries=evidence,
            claim_texts=claim_texts,
        )
        try:
            classification = await self.classifier.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("archetype classification failed for %s: %s", process.process_id, exc)
            return None, None

        run_id = await self.runs.record(
            classification,
            payload=payload,
            prompt=PROCESS_ARCHETYPE_V1,
            ontology_layer=self.classifier.ontology_layer,
            provider=self.service.provider.name,
        )
        applied = await self.writer.apply_archetype(
            process.process_id,
            classification.output,
            agent_run_id=run_id,
            observed_at=payload.as_of,
        )
        return applied, run_id

    async def _prior_state(
        self, process_id: uuid.UUID, archetype: ProcessArchetype, notes: list[str]
    ) -> ProcessStateLabel | None:
        """The last State, but only if it belongs to the current Archetype.

        After a reclassification the recorded history uses a vocabulary the new
        machine does not contain. Carrying it forward as a prior would either
        crash the transition check or, worse, anchor the estimate to a label
        that no longer means anything.
        """
        history = await self.writer.state_history(process_id)
        if not history:
            return None
        latest = history[-1]
        if latest.archetype is not archetype:
            notes.append(
                f"prior State {latest.categorical_state.value!r} dropped: it belongs to "
                f"the superseded archetype {latest.archetype.value!r}"
            )
            return None
        return latest.categorical_state

    async def _pending_process_ids(self, limit: int) -> list[uuid.UUID]:
        """Processes needing classification or a fresh State estimate.

        Stale means: no State yet, or beliefs changed after the last State was
        recorded. Re-estimating a Process nothing has happened to would burn a
        reasoning-tier call to produce the same answer.
        """
        latest_state = (
            select(
                ProcessState.process_id.label("process_id"),
                func.max(ProcessState.recorded_at).label("state_at"),
            )
            .group_by(ProcessState.process_id)
            .subquery()
        )
        latest_belief = (
            select(
                JournalEntry.subject_id.label("subject_id"),
                func.max(JournalEntry.recorded_at).label("belief_at"),
            )
            .where(
                JournalEntry.kind.in_([JournalEntryKind.BELIEF_CHANGE, JournalEntryKind.CREATED])
            )
            .group_by(JournalEntry.subject_id)
            .subquery()
        )

        query = (
            select(Process.process_id)
            .outerjoin(latest_state, latest_state.c.process_id == Process.process_id)
            .outerjoin(latest_belief, latest_belief.c.subject_id == Process.process_id)
            .where(
                Process.valid_to.is_(None),
                Process.status.in_([ProcessStatus.ACTIVE, ProcessStatus.CANDIDATE]),
                or_(
                    Process.archetype.is_(None),
                    latest_state.c.state_at.is_(None),
                    latest_state.c.state_at < latest_belief.c.belief_at,
                ),
            )
            .order_by(Process.created_at)
            .limit(limit)
        )
        async with self.session_factory() as session:
            return list((await session.execute(query)).scalars())

    async def _load(self, process_id: uuid.UUID) -> Process | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Process).where(Process.process_id == process_id, Process.valid_to.is_(None))
            )
            return result.scalar_one_or_none()

    async def _evidence(self, process_id: uuid.UUID) -> tuple[list[str], dict[str, str]]:
        """Events supporting the Process, and the Claims behind them."""
        async with self.session_factory() as session:
            events = (
                (
                    await session.execute(
                        select(Event)
                        .join(EvidenceLink, EvidenceLink.evidence_id == Event.event_id)
                        .where(
                            EvidenceLink.subject_id == process_id,
                            EvidenceLink.retracted_at.is_(None),
                            Event.valid_to.is_(None),
                        )
                        .order_by(Event.occurred_at.desc())
                        .limit(MAX_EVIDENCE_EVENTS)
                    )
                )
                .scalars()
                .all()
            )
            if not events:
                return [], {}
            claims = (
                await session.execute(
                    select(Claim.claim_id, Claim.text)
                    .join(EventClaim, EventClaim.claim_id == Claim.claim_id)
                    .where(
                        EventClaim.event_id.in_([event.event_id for event in events]),
                        EventClaim.removed_at.is_(None),
                    )
                )
            ).all()

        summaries = [
            f"{event.occurred_at.date().isoformat()}: {event.title} — {event.description}"
            for event in sorted(events, key=lambda e: e.occurred_at)
        ]
        return summaries, {str(row.claim_id): row.text for row in claims}

    async def _as_of(self, process_id: uuid.UUID) -> datetime | None:
        """The date the estimate describes: the newest evidence the Process has.

        Not "now". A State estimated from evidence that ends in July is a July
        observation, and dating it today would quietly corrupt every
        point-in-time query that reads it (ontology §33).
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(func.max(Event.occurred_at))
                .join(EvidenceLink, EvidenceLink.evidence_id == Event.event_id)
                .where(EvidenceLink.subject_id == process_id, Event.valid_to.is_(None))
            )
            return result.scalar_one_or_none()
