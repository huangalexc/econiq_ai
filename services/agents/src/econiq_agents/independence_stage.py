"""Building and storing the evidence-dependence graph (issue #67).

Runs the structural pass, sends only what it could not settle to the agent, and
stores both — tagged with which found each, so a measured dependence and a
judged one are never indistinguishable on screen.

The output that matters downstream is :attr:`IndependenceOutcome.effective_sources`.
Before this, ``evidence_independence`` summed each Event's own source count,
which double-counts anything two Events share: four Events all citing one filing
scored four independent sources. Collapsing the dependence graph into components
fixes that, and the groups travel with the number so a scorecard can explain it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from econiq_data_models import (
    Claim,
    Document,
    Event,
    EventClaim,
    EvidenceDependence,
    EvidenceLink,
    Process,
)
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_schemas import EvidenceIndependenceInput, EvidencePair
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.dependence import (
    Dependence,
    EvidenceItem,
    effective_sources,
    structural_dependencies,
    undecided_pairs,
)
from econiq_agents.independence_agent import EvidenceIndependenceAgent
from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.prompts import EVIDENCE_INDEPENDENCE_V1

logger = logging.getLogger("econiq.agents.independence")

#: Above this many Events, every pair is too many pairs. The undecided set grows
#: quadratically, and a Process with forty Events would send 780 pairs to a
#: model. Capped at the most recent, because dependence between old evidence has
#: already been priced into the score and is not going to change.
MAX_EVENTS = 20


@dataclass(frozen=True, slots=True)
class IndependenceOutcome:
    process_id: uuid.UUID
    dependencies: list[Dependence] = field(default_factory=list)
    groups: list[frozenset[uuid.UUID]] = field(default_factory=list)
    effective_sources: int = 0
    naive_sources: int = 0
    superseded: int = 0
    agent_run_id: uuid.UUID | None = None
    skipped_reason: str | None = None

    @property
    def collapsed(self) -> int:
        """Sources the analysis removed. The number §10.2 asks to be measured."""
        return max(self.naive_sources - self.effective_sources, 0)

    @property
    def computed_count(self) -> int:
        return sum(1 for d in self.dependencies if d.detected_by == "computed")

    @property
    def judged_count(self) -> int:
        return sum(1 for d in self.dependencies if d.detected_by == "judged")


class IndependenceStage:
    """Cross-Event dependence analysis for one Process."""

    def __init__(
        self, service: LLMService, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.agent = EvidenceIndependenceAgent(service)
        self.runs = AgentRunRecorder(session_factory)

    async def run(
        self, process_id: uuid.UUID, *, as_of: datetime | None = None
    ) -> IndependenceOutcome:
        moment = as_of or datetime.now(UTC)

        async with self.session_factory() as session:
            process = (
                await session.execute(
                    select(Process.name).where(
                        Process.process_id == process_id, Process.valid_to.is_(None)
                    )
                )
            ).scalar_one_or_none()
            if process is None:
                return IndependenceOutcome(process_id=process_id, skipped_reason="no such Process")
            items = await self._items(session, process_id)

        naive = sum(item.independent_source_count for item in items)
        if len(items) < 2:
            # One Event cannot depend on another. The naive count is already
            # correct and running the agent would cost a call to confirm it.
            return IndependenceOutcome(
                process_id=process_id,
                effective_sources=naive,
                naive_sources=naive,
                groups=[frozenset({item.event_id}) for item in items],
                skipped_reason="fewer than two Events" if not items else None,
            )

        structural = structural_dependencies(items)
        undecided = undecided_pairs(items, structural)

        judged, run_id = await self._judge(process, items, undecided, moment)
        dependencies = structural + judged

        total, groups = effective_sources(items, dependencies)
        superseded = await self._store(process_id, dependencies, moment, run_id)

        return IndependenceOutcome(
            process_id=process_id,
            dependencies=dependencies,
            groups=groups,
            effective_sources=total,
            naive_sources=naive,
            superseded=superseded,
            agent_run_id=run_id,
        )

    # ------------------------------------------------------------------ #

    async def _judge(
        self,
        process_name: str,
        items: list[EvidenceItem],
        undecided: list[tuple[uuid.UUID, uuid.UUID]],
        moment: datetime,
    ) -> tuple[list[Dependence], uuid.UUID | None]:
        if not undecided:
            return [], None

        by_id = {item.event_id: item for item in items}
        payload = EvidenceIndependenceInput(
            as_of=moment,
            process_name=process_name,
            events={str(item.event_id): item.title for item in items},
            event_claims={str(item.event_id): list(item.claim_texts) for item in items},
            event_publishers={str(item.event_id): sorted(item.publishers) for item in items},
            undecided=[
                EvidencePair(source_event_id=str(a), dependent_event_id=str(b))
                for a, b in undecided
            ],
        )

        try:
            result = await self.agent.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("independence analysis failed: %s", exc)
            return [], None

        run_id = await self.runs.record(
            result,
            payload=payload,
            prompt=EVIDENCE_INDEPENDENCE_V1,
            ontology_layer="Event",
            provider=self.service.provider.name,
        )
        if not result.evaluation.passed:
            # The structural findings still stand — they were never the agent's
            # to get wrong.
            logger.warning(
                "independence judgement rejected: %s",
                [c.name for c in result.evaluation.failures],
            )
            return [], run_id

        judged: list[Dependence] = []
        for found in result.output.dependencies:
            try:
                source = uuid.UUID(found.source_event_id)
                dependent = uuid.UUID(found.dependent_event_id)
            except ValueError:
                continue
            if source not in by_id or dependent not in by_id or source == dependent:
                continue
            judged.append(
                Dependence(
                    source_event_id=source,
                    dependent_event_id=dependent,
                    kind=found.kind,
                    rationale=found.rationale,
                    confidence=found.confidence,
                    detected_by="judged",
                )
            )
        return judged, run_id

    async def _store(
        self,
        process_id: uuid.UUID,
        dependencies: list[Dependence],
        moment: datetime,
        run_id: uuid.UUID | None,
    ) -> int:
        async with self.session_factory() as session:
            existing = (
                (
                    await session.execute(
                        select(EvidenceDependence.evidence_dependence_id).where(
                            EvidenceDependence.process_id == process_id,
                            EvidenceDependence.superseded_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if existing:
                # Superseded, not deleted: a dependence the evidence later
                # disproved is part of how the score moved.
                await session.execute(
                    update(EvidenceDependence)
                    .where(EvidenceDependence.evidence_dependence_id.in_(existing))
                    .values(superseded_at=moment)
                )

            for dependence in dependencies:
                session.add(
                    EvidenceDependence(
                        evidence_dependence_id=uuid.uuid4(),
                        process_id=process_id,
                        source_event_id=dependence.source_event_id,
                        dependent_event_id=dependence.dependent_event_id,
                        kind=dependence.kind,
                        rationale=dependence.rationale,
                        confidence=dependence.confidence,
                        detected_by=dependence.detected_by,
                        observed_at=moment,
                        # Structural findings have no run: code found them, and
                        # attributing them to the agent's run would credit a
                        # model with a set intersection.
                        agent_run_id=run_id if dependence.detected_by == "judged" else None,
                    )
                )
            await session.commit()
        return len(existing)

    async def _items(self, session: AsyncSession, process_id: uuid.UUID) -> list[EvidenceItem]:
        rows = (
            (
                await session.execute(
                    select(Event)
                    .join(EvidenceLink, EvidenceLink.evidence_id == Event.event_id)
                    .where(
                        EvidenceLink.subject_id == process_id,
                        EvidenceLink.retracted_at.is_(None),
                        EvidenceLink.supports.is_(True),
                        Event.valid_to.is_(None),
                    )
                    .order_by(Event.occurred_at)
                    .limit(MAX_EVENTS)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return []

        sources = (
            await session.execute(
                select(
                    EventClaim.event_id,
                    Claim.text,
                    Document.document_id,
                    Document.publisher,
                )
                .join(Claim, Claim.claim_id == EventClaim.claim_id)
                .join(Document, Document.document_id == Claim.document_id)
                .where(EventClaim.event_id.in_([row.event_id for row in rows]))
            )
        ).all()

        documents: dict[uuid.UUID, set[uuid.UUID]] = {}
        publishers: dict[uuid.UUID, set[str]] = {}
        claims: dict[uuid.UUID, list[str]] = {}
        for event_id, text, document_id, publisher in sources:
            documents.setdefault(event_id, set()).add(document_id)
            if publisher:
                publishers.setdefault(event_id, set()).add(publisher)
            claims.setdefault(event_id, []).append(text)

        return [
            EvidenceItem(
                event_id=row.event_id,
                title=row.title,
                document_ids=frozenset(documents.get(row.event_id, set())),
                publishers=frozenset(publishers.get(row.event_id, set())),
                claim_texts=tuple(claims.get(row.event_id, [])[:6]),
                independent_source_count=row.independent_source_count,
            )
            for row in rows
        ]
