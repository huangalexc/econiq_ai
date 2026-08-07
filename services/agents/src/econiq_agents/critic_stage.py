"""The Process critique stage (issue #10).

Runs against the *evidence*, not against the reasoning built on it: the critic
is given the Process's thesis and the Claims behind it, and deliberately not the
update agent's rationales or the journal. Feeding it the prior reasoning would
invite agreement, which is the one thing a critic must not supply.

Findings are stored against the Process and are what the Thesis Scoring agent
(issue #65) reads. Critiques are never deleted: a superseded finding becomes
``addressed``, so "this thesis survived four attacks" stays visible.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from econiq_data_models import (
    AgentRun,
    Claim,
    Critique,
    Event,
    EventClaim,
    EvidenceLink,
    Process,
    ProcessState,
)
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import (
    CritiqueStatus,
    EntityType,
    ProcessStateLabel,
    ProcessStatus,
    ScoreFamily,
    ThesisQualityDimension,
    utcnow,
)
from econiq_schemas import ProcessCriticInput, ProcessCriticOutput, ProcessSummary
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.critic_agent import (
    CoverageReport,
    Independence,
    ProcessCriticAgent,
    coverage_of,
)
from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.prompts import PROCESS_CRITIC_V1
from econiq_agents.scoring import ScorecardWriter

logger = logging.getLogger("econiq.agents.critic")

MAX_EVIDENCE_EVENTS = 12


@dataclass(frozen=True, slots=True)
class CritiqueOutcome:
    process_id: uuid.UUID
    critique_ids: list[uuid.UUID] = field(default_factory=list)
    superseded: int = 0
    falsification_risk: float | None = None
    coverage: CoverageReport | None = None
    independence: Independence = Independence.PROMPT_ONLY
    critic_run_id: uuid.UUID | None = None
    scorecard_id: uuid.UUID | None = None
    rejected_reason: str | None = None
    skipped_reason: str | None = None

    @property
    def found(self) -> int:
        return len(self.critique_ids)


class ProcessCritiqueStage:
    """Runs adversarial critique over Processes and stores what it finds."""

    def __init__(
        self,
        service: LLMService,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        critic_model: str | None = None,
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.critic_model = critic_model or service.settings.resolved_critic_model
        self.critic = ProcessCriticAgent(service, model=self.critic_model)
        self.runs = AgentRunRecorder(session_factory)
        self.scores = ScorecardWriter(session_factory)

    async def run_pending(self, *, limit: int = 10) -> list[CritiqueOutcome]:
        outcomes: list[CritiqueOutcome] = []
        for process_id in await self._pending_process_ids(limit):
            outcomes.append(await self.run(process_id))
        return outcomes

    async def run(self, process_id: uuid.UUID) -> CritiqueOutcome:
        process = await self._load(process_id)
        if process is None:
            return CritiqueOutcome(process_id=process_id, skipped_reason="process not found")

        summaries, claim_texts, as_of = await self._evidence(process_id)
        if not claim_texts:
            # Critiquing a thesis with no evidence in front of you produces
            # speculation, which is the opposite of what this agent is for.
            return CritiqueOutcome(
                process_id=process_id, skipped_reason="no evidence to critique against"
            )

        independence = await self._independence(process_id)
        payload = ProcessCriticInput(
            as_of=as_of or process.created_at,
            process=ProcessSummary(
                process_id=str(process_id),
                name=process.name,
                description=process.description,
                archetype=process.archetype,
                current_state=await self._current_state(process_id),
            ),
            thesis_statement=process.description,
            supporting_event_summaries=summaries,
            claim_texts=claim_texts,
        )

        try:
            critique = await self.critic.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("critique failed for %s: %s", process_id, exc)
            return CritiqueOutcome(process_id=process_id, skipped_reason=str(exc))

        run_id = await self.runs.record(
            critique,
            payload=payload,
            prompt=PROCESS_CRITIC_V1,
            ontology_layer=self.critic.ontology_layer,
            provider=self.service.provider.name,
        )
        coverage = coverage_of(critique.output)

        if not critique.evaluation.passed:
            # A critic that rescued the thesis, mislabelled its worst finding or
            # gave an untestable falsifying indicator has produced something the
            # scorer would read wrongly. The run is kept; the findings are not.
            reason = "; ".join(check.detail or check.name for check in critique.evaluation.failures)
            logger.warning("refusing critique output for %s: %s", process_id, reason)
            return CritiqueOutcome(
                process_id=process_id,
                critic_run_id=run_id,
                coverage=coverage,
                independence=independence,
                rejected_reason=reason,
            )

        superseded = await self._supersede_open(process_id, run_id)
        critique_ids = await self._store(
            process_id, critique.output, agent_run_id=run_id, observed_at=payload.as_of
        )
        scorecard_id = await self.scores.record(
            subject_id=process_id,
            subject_type=EntityType.PROCESS,
            family=ScoreFamily.THESIS_QUALITY,
            observed_at=payload.as_of,
            agent_run_id=run_id,
            dimensions=[
                (
                    ThesisQualityDimension.CONTRADICTION,
                    critique.output.falsification_risk,
                    {
                        "critique_count": float(len(critique.output.critiques)),
                        "max_severity": max(
                            (c.severity for c in critique.output.critiques), default=0.0
                        ),
                        "coverage_ratio": coverage.ratio,
                    },
                )
            ],
        )

        return CritiqueOutcome(
            process_id=process_id,
            critique_ids=critique_ids,
            superseded=superseded,
            falsification_risk=critique.output.falsification_risk,
            coverage=coverage,
            independence=independence,
            critic_run_id=run_id,
            scorecard_id=scorecard_id,
        )

    async def _store(
        self,
        process_id: uuid.UUID,
        output: ProcessCriticOutput,
        *,
        agent_run_id: uuid.UUID,
        observed_at: datetime,
    ) -> list[uuid.UUID]:
        ids: list[uuid.UUID] = []
        async with self.session_factory() as session:
            for index, critique in enumerate(output.critiques):
                critique_id = uuid.uuid4()
                ids.append(critique_id)
                session.add(
                    Critique(
                        critique_id=critique_id,
                        subject_id=process_id,
                        subject_type=EntityType.PROCESS,
                        kind=critique.kind,
                        statement=critique.statement,
                        severity=critique.severity,
                        rationale=critique.rationale,
                        testable_with=critique.testable_with,
                        is_most_damaging=index == output.most_damaging_critique_index,
                        status=CritiqueStatus.OPEN,
                        observed_at=observed_at,
                        supporting_claim_ids=list(critique.supporting_claim_ids),
                        agent_run_id=agent_run_id,
                    )
                )
            await session.commit()
        return ids

    async def _supersede_open(self, process_id: uuid.UUID, run_id: uuid.UUID) -> int:
        """Mark the previous pass's open findings as addressed.

        Not deleted: the count of attacks a thesis has survived is a Thesis
        Quality signal, and deleting the old findings would erase it.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                update(Critique)
                .where(
                    Critique.subject_id == process_id,
                    Critique.status == CritiqueStatus.OPEN,
                    Critique.agent_run_id != run_id,
                )
                .values(
                    status=CritiqueStatus.ADDRESSED,
                    resolved_at=utcnow(),
                    resolution_note="superseded by a later critique pass",
                )
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0) or 0)

    async def _independence(self, process_id: uuid.UUID) -> Independence:
        """Whether the critic ran on a different model from the thesis.

        Prompt-level independence is what we have until a second provider
        exists. Recording which one applied keeps the claim honest and gives
        issue #57 something to measure.
        """
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(AgentRun.model_version_id)
                    .where(
                        AgentRun.trigger_event_id.is_not(None),
                        AgentRun.agent_name.in_(["process_update", "process_discovery"]),
                    )
                    .limit(5)
                )
            ).scalars()
            model_ids = {row for row in rows if row is not None}
            if not model_ids:
                return Independence.PROMPT_ONLY
            from econiq_data_models import ModelVersion

            models = (
                await session.execute(
                    select(ModelVersion.model).where(ModelVersion.model_version_id.in_(model_ids))
                )
            ).scalars()
            thesis_models = set(models)
        return (
            Independence.DISTINCT_MODEL
            if self.critic.model not in thesis_models
            else Independence.PROMPT_ONLY
        )

    async def _pending_process_ids(self, limit: int) -> list[uuid.UUID]:
        """Processes whose thesis has moved since it was last attacked.

        Re-critiquing an unchanged Process would spend a reasoning-tier call to
        rediscover the same objections.
        """
        latest_critique = (
            select(
                Critique.subject_id.label("subject_id"),
                func.max(Critique.recorded_at).label("critiqued_at"),
            )
            .group_by(Critique.subject_id)
            .subquery()
        )
        latest_state = (
            select(
                ProcessState.process_id.label("process_id"),
                func.max(ProcessState.recorded_at).label("state_at"),
            )
            .group_by(ProcessState.process_id)
            .subquery()
        )
        query = (
            select(Process.process_id)
            .outerjoin(latest_critique, latest_critique.c.subject_id == Process.process_id)
            .outerjoin(latest_state, latest_state.c.process_id == Process.process_id)
            .where(
                Process.valid_to.is_(None),
                Process.status.in_([ProcessStatus.ACTIVE, ProcessStatus.CANDIDATE]),
                or_(
                    latest_critique.c.critiqued_at.is_(None),
                    latest_critique.c.critiqued_at < latest_state.c.state_at,
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

    async def _current_state(self, process_id: uuid.UUID) -> ProcessStateLabel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ProcessState.categorical_state)
                .where(ProcessState.process_id == process_id)
                .order_by(ProcessState.observed_at.desc(), ProcessState.recorded_at.desc())
                .limit(1)
            )
            state: ProcessStateLabel | None = result.scalar_one_or_none()
            return state

    async def _evidence(
        self, process_id: uuid.UUID
    ) -> tuple[list[str], dict[str, str], datetime | None]:
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
                return [], {}, None
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

        ordered = sorted(events, key=lambda event: event.occurred_at)
        summaries = [
            f"{event.occurred_at.date().isoformat()}: {event.title} — {event.description}"
            for event in ordered
        ]
        return (
            summaries,
            {str(row.claim_id): row.text for row in claims},
            ordered[-1].occurred_at,
        )
