"""The Process → Bottleneck → Capability stage (issue #11).

::

    Process (with a State)
      → Bottleneck Identification
      → the binding constraint, plus any that only bind later
      → Capability Mapping, on the binding one
      → Capabilities resolved against existing nodes, requirement tree stored
      → Confluence, wherever several Processes now need the same Capability

Only the binding Bottleneck is mapped. Mapping a constraint that will not bite
for three years produces a Capability set — and eventually an Asset universe —
for a problem nobody has yet, which is the specific way a research system talks
itself into positions early.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from econiq_data_models import (
    Bottleneck,
    Capability,
    CapabilityRequirement,
    Claim,
    Event,
    EventClaim,
    EvidenceLink,
    Process,
    ProcessState,
    ProcessStateFeature,
    Relationship,
)
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import ProcessStatus, RelationshipType
from econiq_schemas import (
    BottleneckIdentificationInput,
    CapabilityConfluenceInput,
    CapabilityMappingInput,
    ProcessContext,
    ProposedBottleneck,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.capability_agents import (
    BottleneckIdentificationAgent,
    CapabilityConfluenceAgent,
    CapabilityMappingAgent,
    independent_support,
)
from econiq_agents.capability_persistence import (
    BottleneckWriter,
    CapabilityWriter,
    PersistedBottleneck,
    PersistedRequirement,
)
from econiq_agents.embeddings import Embedder, EmbeddingStore, HashingEmbedder
from econiq_agents.graph_writer import GraphWriter, IllegalEdgeError
from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.prompts import (
    BOTTLENECK_IDENTIFICATION_V1,
    CAPABILITY_CONFLUENCE_V1,
    CAPABILITY_MAPPING_V1,
)

logger = logging.getLogger("econiq.agents.capability")

MAX_EVIDENCE_EVENTS = 8


@dataclass(frozen=True, slots=True)
class ConfluenceResult:
    capability_id: uuid.UUID
    independent_support: int
    upstream_process_ids: tuple[str, ...] = ()
    run_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CapabilityOutcome:
    process_id: uuid.UUID
    bottlenecks: list[PersistedBottleneck] = field(default_factory=list)
    binding: PersistedBottleneck | None = None
    requirement: PersistedRequirement | None = None
    confluence: list[ConfluenceResult] = field(default_factory=list)
    bottleneck_run_id: uuid.UUID | None = None
    mapping_run_id: uuid.UUID | None = None
    skipped_reason: str | None = None
    rejected_reason: str | None = None

    @property
    def reused_capabilities(self) -> int:
        return self.requirement.reused if self.requirement else 0


class CapabilityStage:
    """Turns a Process's State into constraints and the abilities that resolve them."""

    def __init__(
        self,
        service: LLMService,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        embeddings = EmbeddingStore(session_factory, embedder or HashingEmbedder())
        self.identifier = BottleneckIdentificationAgent(service)
        self.mapper = CapabilityMappingAgent(service)
        self.confluence = CapabilityConfluenceAgent(service)
        self.bottlenecks = BottleneckWriter(session_factory)
        self.capabilities = CapabilityWriter(session_factory, embeddings)
        self.graph = GraphWriter(session_factory)
        self.runs = AgentRunRecorder(session_factory)

    async def run_pending(self, *, limit: int = 10) -> list[CapabilityOutcome]:
        outcomes: list[CapabilityOutcome] = []
        for process_id in await self._pending_process_ids(limit):
            outcomes.append(await self.run(process_id))
        return outcomes

    async def run(self, process_id: uuid.UUID) -> CapabilityOutcome:
        context = await self._context(process_id)
        if context is None:
            return CapabilityOutcome(process_id=process_id, skipped_reason="process not found")
        process, state, features, as_of = context

        claim_texts = await self._claims(process_id)
        known = [b.name for b in await self.bottlenecks.open_for_process(process_id)]

        payload = BottleneckIdentificationInput(
            as_of=as_of,
            process=ProcessContext(
                process_id=str(process_id),
                name=process.name,
                description=process.description,
                archetype=process.archetype,
                current_state=state,
            ),
            state_features=features,
            claim_texts=claim_texts,
            known_bottleneck_names=known,
        )
        try:
            identification = await self.identifier.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("bottleneck identification failed for %s: %s", process_id, exc)
            return CapabilityOutcome(process_id=process_id, skipped_reason=str(exc))

        bottleneck_run_id = await self.runs.record(
            identification,
            payload=payload,
            prompt=BOTTLENECK_IDENTIFICATION_V1,
            ontology_layer=self.identifier.ontology_layer,
            provider=self.service.provider.name,
        )
        if not identification.evaluation.passed:
            reason = "; ".join(
                check.detail or check.name for check in identification.evaluation.failures
            )
            logger.warning("refusing bottleneck output for %s: %s", process_id, reason)
            return CapabilityOutcome(
                process_id=process_id,
                bottleneck_run_id=bottleneck_run_id,
                rejected_reason=reason,
            )

        persisted: list[PersistedBottleneck] = []
        binding: tuple[PersistedBottleneck, ProposedBottleneck] | None = None
        for index, candidate in enumerate(identification.output.candidates):
            written = await self.bottlenecks.persist(
                process_id, candidate, agent_run_id=bottleneck_run_id
            )
            persisted.append(written)
            await self._link(
                process_id,
                written.bottleneck_id,
                RelationshipType.CREATES,
                confidence=candidate.confidence,
                rationale=candidate.why_limiting,
                agent_run_id=bottleneck_run_id,
            )
            if index == identification.output.binding_candidate_index:
                binding = (written, candidate)

        if binding is None:
            # No binding constraint is a real answer: the Process is not
            # currently constrained, and mapping Capabilities for a constraint
            # that does not bite yet would invent a problem.
            return CapabilityOutcome(
                process_id=process_id,
                bottlenecks=persisted,
                bottleneck_run_id=bottleneck_run_id,
                skipped_reason="no currently binding bottleneck",
            )

        written_binding, candidate = binding
        requirement, mapping_run_id = await self._map(
            process, written_binding, candidate, claim_texts, as_of=as_of
        )
        confluence: list[ConfluenceResult] = []
        if requirement is not None:
            for resolved in requirement.capabilities:
                result = await self._confluence(resolved.capability_id, as_of=as_of)
                if result is not None:
                    confluence.append(result)

        return CapabilityOutcome(
            process_id=process_id,
            bottlenecks=persisted,
            binding=written_binding,
            requirement=requirement,
            confluence=confluence,
            bottleneck_run_id=bottleneck_run_id,
            mapping_run_id=mapping_run_id,
        )

    async def _map(
        self,
        process: Process,
        written: PersistedBottleneck,
        candidate: ProposedBottleneck,
        claim_texts: dict[str, str],
        *,
        as_of: datetime,
    ) -> tuple[PersistedRequirement | None, uuid.UUID | None]:
        payload = CapabilityMappingInput(
            as_of=as_of,
            process=ProcessContext(
                process_id=str(process.process_id),
                name=process.name,
                description=process.description,
                archetype=process.archetype,
            ),
            bottleneck_name=candidate.name,
            bottleneck_description=candidate.description,
            bottleneck_kind=candidate.kind,
            claim_texts=claim_texts,
            known_capabilities=await self.capabilities.known_names(),
        )
        try:
            mapping = await self.mapper.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("capability mapping failed for %s: %s", written.bottleneck_id, exc)
            return None, None

        run_id = await self.runs.record(
            mapping,
            payload=payload,
            prompt=CAPABILITY_MAPPING_V1,
            ontology_layer=self.mapper.ontology_layer,
            provider=self.service.provider.name,
        )
        if not mapping.evaluation.passed or mapping.output.requirement_tree is None:
            reason = (
                "; ".join(check.detail or check.name for check in mapping.evaluation.failures)
                or "no requirement tree"
            )
            logger.warning("refusing capability mapping for %s: %s", written.bottleneck_id, reason)
            return None, run_id

        requirement = await self.capabilities.store_requirement(
            mapping.output,
            bottleneck_id=written.bottleneck_id,
            process_id=process.process_id,
            agent_run_id=run_id,
        )
        for resolved in requirement.capabilities:
            await self._link(
                written.bottleneck_id,
                resolved.capability_id,
                RelationshipType.REQUIRES,
                confidence=1.0,
                rationale=f"required to resolve {candidate.name}",
                agent_run_id=run_id,
            )
        return requirement, run_id

    async def _confluence(
        self, capability_id: uuid.UUID, *, as_of: datetime
    ) -> ConfluenceResult | None:
        """Classify upstream independence when a Capability has several sources.

        Skipped for a single upstream Process: there is no confluence to assess,
        and asking anyway would spend a call to be told so.
        """
        upstream = await self._upstream_processes(capability_id)
        if len(upstream) < 2:
            return None

        capability = await self._capability(capability_id)
        if capability is None:
            return None

        payload = CapabilityConfluenceInput(
            as_of=as_of,
            capability_id=str(capability_id),
            capability_name=capability.name,
            capability_description=capability.description,
            candidate_processes=upstream,
        )
        try:
            result = await self.confluence.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("confluence assessment failed for %s: %s", capability_id, exc)
            return None

        run_id = await self.runs.record(
            result,
            payload=payload,
            prompt=CAPABILITY_CONFLUENCE_V1,
            ontology_layer=self.confluence.ontology_layer,
            provider=self.service.provider.name,
        )
        if not result.evaluation.passed:
            return ConfluenceResult(
                capability_id=capability_id, independent_support=0, run_id=run_id
            )

        count, process_ids = independent_support(result.output)
        for interaction in result.output.interactions:
            if interaction.interaction.lower().startswith("reinforc"):
                await self._link(
                    uuid.UUID(interaction.process_id_a),
                    uuid.UUID(interaction.process_id_b),
                    RelationshipType.INFLUENCES,
                    confidence=0.6,
                    rationale=interaction.rationale,
                    agent_run_id=run_id,
                )
        return ConfluenceResult(
            capability_id=capability_id,
            independent_support=count,
            upstream_process_ids=process_ids,
            run_id=run_id,
        )

    async def _link(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relationship_type: RelationshipType,
        *,
        confidence: float,
        rationale: str,
        agent_run_id: uuid.UUID,
    ) -> None:
        try:
            await self.graph.relate(
                source_id=source_id,
                target_id=target_id,
                relationship_type=relationship_type,
                confidence=confidence,
                rationale=rationale,
                agent_run_id=agent_run_id,
            )
        except IllegalEdgeError:
            logger.exception("refused an illegal edge from %s", source_id)

    async def _pending_process_ids(self, limit: int) -> list[uuid.UUID]:
        """Processes whose State moved since their Bottlenecks were last assessed.

        A constraint is a function of where the Process is in its lifecycle, so
        a State that has not moved does not warrant a fresh assessment.
        """
        latest_state = (
            select(
                ProcessState.process_id.label("process_id"),
                func.max(ProcessState.recorded_at).label("state_at"),
            )
            .group_by(ProcessState.process_id)
            .subquery()
        )
        latest_bottleneck = (
            select(
                Bottleneck.process_id.label("process_id"),
                func.max(Bottleneck.created_at).label("bottleneck_at"),
            )
            .group_by(Bottleneck.process_id)
            .subquery()
        )
        query = (
            select(Process.process_id)
            .join(latest_state, latest_state.c.process_id == Process.process_id)
            .outerjoin(latest_bottleneck, latest_bottleneck.c.process_id == Process.process_id)
            .where(
                Process.valid_to.is_(None),
                Process.status.in_([ProcessStatus.ACTIVE, ProcessStatus.CANDIDATE]),
                or_(
                    latest_bottleneck.c.bottleneck_at.is_(None),
                    latest_bottleneck.c.bottleneck_at < latest_state.c.state_at,
                ),
            )
            .order_by(Process.created_at)
            .limit(limit)
        )
        async with self.session_factory() as session:
            return list((await session.execute(query)).scalars())

    async def _context(
        self, process_id: uuid.UUID
    ) -> tuple[Process, object, dict[str, float], datetime] | None:
        async with self.session_factory() as session:
            process = (
                await session.execute(
                    select(Process).where(
                        Process.process_id == process_id, Process.valid_to.is_(None)
                    )
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
            features: dict[str, float] = {}
            if state is not None:
                rows = (
                    await session.execute(
                        select(ProcessStateFeature.name, ProcessStateFeature.value).where(
                            ProcessStateFeature.process_state_id == state.process_state_id
                        )
                    )
                ).all()
                features = {row.name: row.value for row in rows}

        as_of = state.observed_at if state is not None else process.created_at
        return process, (state.categorical_state if state else None), features, as_of

    async def _claims(self, process_id: uuid.UUID) -> dict[str, str]:
        async with self.session_factory() as session:
            events = (
                (
                    await session.execute(
                        select(Event.event_id)
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
                return {}
            rows = (
                await session.execute(
                    select(Claim.claim_id, Claim.text)
                    .join(EventClaim, EventClaim.claim_id == Claim.claim_id)
                    .where(EventClaim.event_id.in_(events), EventClaim.removed_at.is_(None))
                )
            ).all()
        return {str(row.claim_id): row.text for row in rows}

    async def _upstream_processes(self, capability_id: uuid.UUID) -> list[ProcessContext]:
        """Processes reaching this Capability through their Bottlenecks.

        Read from the graph rather than asked of a model: confluence is a
        structural fact, and the agent's job is only to say how independent the
        sources are.
        """
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(Process)
                        .join(
                            CapabilityRequirement,
                            CapabilityRequirement.process_id == Process.process_id,
                        )
                        .join(
                            Relationship,
                            Relationship.source_id == CapabilityRequirement.bottleneck_id,
                        )
                        .where(
                            Relationship.target_id == capability_id,
                            Relationship.relationship_type == RelationshipType.REQUIRES,
                            Relationship.valid_to.is_(None),
                            Process.valid_to.is_(None),
                            CapabilityRequirement.valid_to.is_(None),
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
        return [
            ProcessContext(
                process_id=str(process.process_id),
                name=process.name,
                description=process.description,
                archetype=process.archetype,
            )
            for process in rows
        ]

    async def _capability(self, capability_id: uuid.UUID) -> Capability | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Capability).where(
                    Capability.capability_id == capability_id,
                    Capability.valid_to.is_(None),
                )
            )
            return result.scalar_one_or_none()
