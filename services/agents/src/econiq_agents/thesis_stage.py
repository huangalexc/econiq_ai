"""Counterfactuals and Thesis Quality scoring (issues #65, #66).

Two agents in one stage because they are one act: constructing the alternative
worlds and then scoring the thesis that has to survive them. Running them apart
would mean the robustness axis was computed from whatever counterfactuals
happened to exist at the time, which is a scorecard that changes for reasons
nobody can see.

The order is fixed and the reason is the whole design. Counterfactuals are
constructed first, robustness is *computed* from them by code, and the scoring
agent is then told not to score that axis. An agent that both writes the attacks
and grades how well the thesis survived them has no reason to write good
attacks — the same argument that keeps the Process Critic away from its own
severity scores.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from econiq_data_models import (
    Claim,
    Counterfactual,
    Critique,
    Document,
    Event,
    EventClaim,
    EvidenceDependence,
    EvidenceLink,
    Process,
    ProcessState,
    Scorecard,
)
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import (
    CritiqueStatus,
    EntityType,
    ScoreFamily,
    utcnow,
)
from econiq_ontology import (
    ThesisQualityDimension as Axis,
)
from econiq_schemas import (
    AxisScore,
    CounterfactualInput,
    ProcessSummary,
    ThesisScoringInput,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents import thesis_measures
from econiq_agents.counterfactual_agent import CounterfactualAgent
from econiq_agents.dependence import Dependence, EvidenceItem, effective_sources
from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.prompts import COUNTERFACTUAL_V1, THESIS_SCORING_V1
from econiq_agents.scoring import ScorecardWriter
from econiq_agents.thesis_measures import Measure
from econiq_agents.thesis_scorer import JUDGED_AXES, ThesisScoringAgent

logger = logging.getLogger("econiq.agents.thesis")

#: Window for the "recent evidence" input to accumulated_evidence.
RECENT_WINDOW = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class ThesisOutcome:
    process_id: uuid.UUID
    counterfactual_ids: list[uuid.UUID] = field(default_factory=list)
    superseded: int = 0
    scorecard_id: uuid.UUID | None = None
    computed: list[Measure] = field(default_factory=list)
    judged_axes: int = 0
    counterfactual_run_id: uuid.UUID | None = None
    scoring_run_id: uuid.UUID | None = None
    skipped_reason: str | None = None

    @property
    def axes_written(self) -> int:
        return len(self.computed) + self.judged_axes


class ThesisStage:
    """Counterfactual construction and multidimensional scoring."""

    def __init__(
        self,
        service: LLMService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.counterfactual = CounterfactualAgent(service)
        self.scorer = ThesisScoringAgent(service)
        self.scores = ScorecardWriter(session_factory)
        self.runs = AgentRunRecorder(session_factory)

    async def run_pending(self, *, limit: int = 10) -> list[ThesisOutcome]:
        """Score Processes that have none, or whose evidence moved since."""
        async with self.session_factory() as session:
            pending = await self._unscored(session, limit)
        return [await self.run(process_id) for process_id in pending]

    async def run(self, process_id: uuid.UUID, *, as_of: datetime | None = None) -> ThesisOutcome:
        moment = as_of or datetime.now(UTC)

        async with self.session_factory() as session:
            context = await self._context(session, process_id, moment)
        if context is None:
            return ThesisOutcome(process_id=process_id, skipped_reason="no such Process")

        counterfactual_ids, superseded, cf_run_id, worlds = await self._counterfactuals(
            context, moment
        )

        computed = self._measure(context, worlds, moment)
        scoring_run_id, judged = await self._score(context, computed, moment)

        scorecard_id = None
        if computed or judged:
            scorecard_id = await self.scores.record(
                subject_id=process_id,
                subject_type=EntityType.PROCESS,
                family=ScoreFamily.THESIS_QUALITY,
                observed_at=moment,
                # Attributed to the scoring run where there is one, so the
                # scorecard's provenance points at the agent that judged most of
                # it rather than at whichever ran last.
                agent_run_id=scoring_run_id or cf_run_id,
                dimensions=[(measure.axis, measure.value, measure.inputs) for measure in computed]
                + [(axis.dimension, axis.value, {}) for axis in judged],
            )
            await self._annotate(scorecard_id, computed, judged)

        return ThesisOutcome(
            process_id=process_id,
            counterfactual_ids=counterfactual_ids,
            superseded=superseded,
            scorecard_id=scorecard_id,
            computed=computed,
            judged_axes=len(judged),
            counterfactual_run_id=cf_run_id,
            scoring_run_id=scoring_run_id,
        )

    # ------------------------------------------------------------------ #

    async def _counterfactuals(
        self, context: _Context, moment: datetime
    ) -> tuple[list[uuid.UUID], int, uuid.UUID | None, list[tuple[float, float, int]]]:
        payload = CounterfactualInput(
            as_of=moment,
            process=context.summary,
            thesis_statement=context.thesis,
            causal_mechanism=context.causal_mechanism,
            supporting_event_summaries=context.supporting,
            claim_texts=context.claims,
            known_critiques=context.critiques,
        )
        try:
            result = await self.counterfactual.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("counterfactual construction failed: %s", exc)
            return [], 0, None, []

        run_id = await self.runs.record(
            result,
            payload=payload,
            prompt=COUNTERFACTUAL_V1,
            ontology_layer="Process",
            provider=self.service.provider.name,
        )
        if not result.evaluation.passed:
            # Rejected output does not reach the ontology. A set of straw men
            # would inflate robustness precisely because it is easy to survive.
            logger.warning(
                "counterfactuals rejected for %s: %s",
                context.process_id,
                [c.name for c in result.evaluation.failures],
            )
            return [], 0, run_id, []

        ids: list[uuid.UUID] = []
        async with self.session_factory() as session:
            # Supersede rather than delete: an alternative world the thesis has
            # already outlived is part of its record (ontology §32).
            # Counted with a select rather than read off rowcount: the async
            # Result type does not expose it, and the number ends up in the
            # outcome that tests assert on.
            superseded = len(
                (
                    await session.execute(
                        select(Counterfactual.counterfactual_id).where(
                            Counterfactual.process_id == context.process_id,
                            Counterfactual.superseded_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            await session.execute(
                update(Counterfactual)
                .where(
                    Counterfactual.process_id == context.process_id,
                    Counterfactual.superseded_at.is_(None),
                )
                .values(superseded_at=moment)
            )

            for index, world in enumerate(result.output.counterfactuals):
                counterfactual_id = uuid.uuid4()
                ids.append(counterfactual_id)
                session.add(
                    Counterfactual(
                        counterfactual_id=counterfactual_id,
                        process_id=context.process_id,
                        challenged_assumption=world.challenged_assumption,
                        alternative_world=world.alternative_world,
                        affected_links=list(world.affected_links),
                        assets_harmed=list(world.assets_harmed),
                        observable_indicators=list(world.observable_indicators),
                        plausibility=world.plausibility,
                        severity_if_true=world.severity_if_true,
                        is_most_dangerous=index == result.output.most_dangerous_index,
                        observed_at=moment,
                        supporting_claim_ids=list(world.supporting_claim_ids),
                        agent_run_id=run_id,
                    )
                )
            await session.commit()

        worlds = [
            (w.plausibility, w.severity_if_true, len(w.observable_indicators))
            for w in result.output.counterfactuals
        ]
        return ids, superseded, run_id, worlds

    def _measure(
        self,
        context: _Context,
        worlds: list[tuple[float, float, int]],
        moment: datetime,
    ) -> list[Measure]:
        candidates = [
            thesis_measures.state_confidence(
                context.state_confidence,
                observed_at=context.state_observed_at,
                now=moment,
            ),
            thesis_measures.accumulated_evidence(
                supporting=context.supporting_count, recent=context.recent_count
            ),
            thesis_measures.evidence_independence(
                independent_sources=context.independent_sources,
                documents=context.document_count,
            ),
            thesis_measures.contradiction(
                falsification_risk=context.falsification_risk,
                contradicting_events=context.contradicting_count,
            ),
            thesis_measures.counterfactual_robustness(worlds),
        ]
        return [measure for measure in candidates if measure is not None]

    async def _score(
        self, context: _Context, computed: Sequence[Measure], moment: datetime
    ) -> tuple[uuid.UUID | None, list[AxisScore]]:
        payload = ThesisScoringInput(
            as_of=moment,
            process=context.summary,
            thesis_statement=context.thesis,
            causal_mechanism=context.causal_mechanism,
            supporting_event_summaries=context.supporting,
            contradicting_event_summaries=context.contradicting,
            claim_texts=context.claims,
            open_critiques=context.critiques,
            computed_axes={m.axis.value: m.value for m in computed},
        )
        try:
            result = await self.scorer.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("thesis scoring failed: %s", exc)
            return None, []

        run_id = await self.runs.record(
            result,
            payload=payload,
            prompt=THESIS_SCORING_V1,
            ontology_layer="Process",
            provider=self.service.provider.name,
        )
        if not result.evaluation.passed:
            logger.warning(
                "thesis scoring rejected for %s: %s",
                context.process_id,
                [c.name for c in result.evaluation.failures],
            )
            return run_id, []
        return run_id, list(result.output.axes)

    async def _annotate(
        self,
        scorecard_id: uuid.UUID,
        computed: Sequence[Measure],
        judged: Sequence[AxisScore],
    ) -> None:
        """Attach each axis's rationale after the write.

        `ScorecardWriter.record` takes dimensions as (axis, value, inputs) and
        has no rationale slot. Rather than widen a signature every other caller
        is happy with, the reasoning is written here — and it must be written,
        because §11.1's "why it is not higher" is the part of a score a reader
        actually uses.
        """
        from econiq_data_models import ScoreDimension

        rationales: dict[str, str] = {m.axis.value: m.rationale for m in computed}
        for axis in judged:
            facts = "; ".join(axis.facts) or "no observation cited"
            rationales[axis.dimension.value] = (
                f"Not higher because: {axis.why_not_higher} "
                f"Facts: {facts}."
                + (f" Inferred: {'; '.join(axis.inferences)}." if axis.inferences else "")
            )

        async with self.session_factory() as session:
            for dimension, rationale in rationales.items():
                await session.execute(
                    update(ScoreDimension)
                    .where(
                        ScoreDimension.scorecard_id == scorecard_id,
                        ScoreDimension.dimension == dimension,
                    )
                    .values(rationale=rationale)
                )
            await session.commit()

    async def _unscored(self, session: AsyncSession, limit: int) -> list[uuid.UUID]:
        scored = select(Scorecard.subject_id).where(Scorecard.family == ScoreFamily.THESIS_QUALITY)
        rows = await session.execute(
            select(Process.process_id)
            .where(Process.valid_to.is_(None), Process.process_id.not_in(scored))
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def _context(
        self, session: AsyncSession, process_id: uuid.UUID, moment: datetime
    ) -> _Context | None:
        process = (
            await session.execute(
                select(Process).where(Process.process_id == process_id, Process.valid_to.is_(None))
            )
        ).scalar_one_or_none()
        if process is None:
            return None

        state = (
            await session.execute(
                select(ProcessState)
                .where(ProcessState.process_id == process_id)
                .order_by(ProcessState.observed_at.desc(), ProcessState.recorded_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        links = (
            await session.execute(
                select(EvidenceLink, Event)
                .join(Event, Event.event_id == EvidenceLink.evidence_id)
                .where(
                    EvidenceLink.subject_id == process_id,
                    EvidenceLink.retracted_at.is_(None),
                    Event.valid_to.is_(None),
                )
            )
        ).all()
        supporting = [(link, event) for link, event in links if link.supports]
        contradicting = [(link, event) for link, event in links if not link.supports]

        event_ids = [event.event_id for _, event in supporting]
        documents = 0
        claims: dict[str, str] = {}
        if event_ids:
            documents = (
                await session.execute(
                    select(func.count(func.distinct(Claim.document_id)))
                    .select_from(Claim)
                    .join(EventClaim, EventClaim.claim_id == Claim.claim_id)
                    .join(Document, Document.document_id == Claim.document_id)
                    .where(EventClaim.event_id.in_(event_ids))
                )
            ).scalar_one()
            claim_rows = (
                (
                    await session.execute(
                        select(Claim)
                        .join(EventClaim, EventClaim.claim_id == Claim.claim_id)
                        .where(EventClaim.event_id.in_(event_ids))
                        .limit(40)
                    )
                )
                .scalars()
                .all()
            )
            claims = {str(claim.claim_id): claim.text for claim in claim_rows}

        critiques = (
            (
                await session.execute(
                    select(Critique)
                    .where(
                        Critique.subject_id == process_id,
                        Critique.status == CritiqueStatus.OPEN,
                    )
                    .order_by(Critique.severity.desc())
                )
            )
            .scalars()
            .all()
        )

        return _Context(
            process_id=process_id,
            summary=ProcessSummary(
                process_id=str(process_id),
                name=process.name,
                description=process.description,
                archetype=process.archetype,
                current_state=state.categorical_state if state else None,
            ),
            thesis=process.description,
            # The discovery agent produces a causal mechanism but nothing
            # persists it as a column — it survives only inside the creating
            # journal entry's summary. Passed as absent rather than parsed back
            # out of prose; both agents work from the description, and a
            # mechanism field on Process is a small gap worth filing separately.
            causal_mechanism=None,
            supporting=[event.title for _, event in supporting],
            contradicting=[event.title for _, event in contradicting],
            claims=claims,
            critiques=[critique.statement for critique in critiques],
            state_confidence=state.state_confidence if state else None,
            state_observed_at=state.observed_at if state else None,
            supporting_count=len(supporting),
            contradicting_count=len(contradicting),
            recent_count=sum(
                1 for link, _ in supporting if moment - link.created_at <= RECENT_WINDOW
            ),
            # The effective count where a dependence graph exists (#67),
            # falling back to the naive sum. Four Events all citing one filing
            # are one source, and summing per-Event counts would say four.
            independent_sources=await self._independent_sources(
                session, process_id, [event for _, event in supporting]
            ),
            document_count=documents,
            falsification_risk=await self._falsification_risk(session, process_id),
        )

    async def _independent_sources(
        self, session: AsyncSession, process_id: uuid.UUID, events: Sequence[Event]
    ) -> int:
        """Effective independent sources, collapsing the dependence graph."""
        naive = sum(event.independent_source_count for event in events)
        dependencies = (
            (
                await session.execute(
                    select(EvidenceDependence).where(
                        EvidenceDependence.process_id == process_id,
                        EvidenceDependence.superseded_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not dependencies:
            return naive

        items = [
            EvidenceItem(
                event_id=event.event_id,
                title=event.title,
                independent_source_count=event.independent_source_count,
            )
            for event in events
        ]
        edges = [
            Dependence(
                source_event_id=row.source_event_id,
                dependent_event_id=row.dependent_event_id,
                kind=row.kind,
                rationale=row.rationale,
                confidence=row.confidence,
                detected_by=row.detected_by,
            )
            for row in dependencies
        ]
        total, _ = effective_sources(items, edges)
        return total

    async def _falsification_risk(
        self, session: AsyncSession, process_id: uuid.UUID
    ) -> float | None:
        """The Critic's own number, not a re-judgement of it."""
        from econiq_data_models import ScoreDimension

        row = await session.execute(
            select(ScoreDimension.value)
            .join(Scorecard, Scorecard.scorecard_id == ScoreDimension.scorecard_id)
            .where(
                Scorecard.subject_id == process_id,
                Scorecard.family == ScoreFamily.THESIS_QUALITY,
                ScoreDimension.dimension == Axis.CONTRADICTION.value,
            )
            .order_by(Scorecard.observed_at.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class _Context:
    """Everything both agents need, read once."""

    process_id: uuid.UUID
    summary: ProcessSummary
    thesis: str
    causal_mechanism: str | None
    supporting: list[str]
    contradicting: list[str]
    claims: dict[str, str]
    critiques: list[str]
    state_confidence: float | None
    state_observed_at: datetime | None
    supporting_count: int
    contradicting_count: int
    recent_count: int
    independent_sources: int
    document_count: int
    falsification_risk: float | None


__all__ = ["JUDGED_AXES", "ThesisOutcome", "ThesisStage", "utcnow"]
