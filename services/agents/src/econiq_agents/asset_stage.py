"""The Capability → Asset stage (issue #12).

::

    Capability (required by a binding Bottleneck)
      → Asset Discovery, across every instrument class
      → deterministic resolution: reference universe for commodities and
        currencies, symbol or existing node for equities
      → Capability --expressed_by--> Asset
      → Asset Exposure, per material candidate

This is the last agent layer of Phase 0 and the first that may name an
instrument. The archetype travels with the request so the discovery agent knows
when the commodity itself is likely the cleaner expression — a copper shortage
is expressed by copper more directly than by any one miner.
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
    Process,
    ProcessState,
    Relationship,
)
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import EntityType, ProcessArchetype, RelationshipType
from econiq_schemas import (
    AssetDiscoveryInput,
    AssetExposureInput,
    ProposedAssetCandidate,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.asset_agents import (
    AssetDiscoveryAgent,
    AssetExposureAgent,
    InstrumentBreadthEvaluator,
    material_candidates,
)
from econiq_agents.asset_persistence import (
    AssetResolution,
    AssetWriter,
    ExposureWriter,
    PersistedExposures,
    resolution_rate,
)
from econiq_agents.graph_writer import GraphWriter, IllegalEdgeError
from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.prompts import ASSET_DISCOVERY_V1, ASSET_EXPOSURE_V1

logger = logging.getLogger("econiq.agents.assets")


@dataclass(frozen=True, slots=True)
class AssetOutcome:
    capability_id: uuid.UUID
    resolutions: list[AssetResolution] = field(default_factory=list)
    exposures: list[PersistedExposures] = field(default_factory=list)
    discovery_run_id: uuid.UUID | None = None
    advisories: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def resolved(self) -> int:
        return sum(1 for resolution in self.resolutions if resolution.ok)

    @property
    def unresolved(self) -> list[str]:
        return [r.reason for r in self.resolutions if r.reason is not None]

    @property
    def resolution_rate(self) -> float:
        return resolution_rate(self.resolutions)


class AssetDiscoveryStage:
    """Finds and evidences the investable expressions of a Capability."""

    def __init__(
        self,
        service: LLMService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.discovery = AssetDiscoveryAgent(service)
        self.exposure = AssetExposureAgent(service)
        self.assets = AssetWriter(session_factory)
        self.exposures = ExposureWriter(session_factory)
        self.graph = GraphWriter(session_factory)
        self.runs = AgentRunRecorder(session_factory)

    async def run_pending(self, *, limit: int = 10) -> list[AssetOutcome]:
        outcomes: list[AssetOutcome] = []
        for capability_id in await self._pending_capability_ids(limit):
            outcomes.append(await self.run(capability_id))
        return outcomes

    async def run(self, capability_id: uuid.UUID) -> AssetOutcome:
        capability = await self._capability(capability_id)
        if capability is None:
            return AssetOutcome(capability_id=capability_id, skipped_reason="capability not found")

        processes, archetype, as_of = await self._context(capability_id)
        payload = AssetDiscoveryInput(
            as_of=as_of,
            capability_id=str(capability_id),
            capability_name=capability.name,
            capability_description=capability.description,
            process_names=[process.name for process in processes],
            known_asset_names=await self.assets.known_names(),
        )

        # The archetype is given to the breadth check rather than to the prompt
        # alone: whether an equity-only answer is worth flagging depends on what
        # kind of Process this Capability serves.
        agent = AssetDiscoveryAgent(
            self.service,
            evaluators=[
                *self.discovery.default_evaluators()[:-1],
                InstrumentBreadthEvaluator(archetype=archetype),
            ],
        )
        try:
            discovery = await agent.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("asset discovery failed for %s: %s", capability_id, exc)
            return AssetOutcome(capability_id=capability_id, skipped_reason=str(exc))

        discovery_run_id = await self.runs.record(
            discovery,
            payload=payload,
            prompt=ASSET_DISCOVERY_V1,
            ontology_layer=self.discovery.ontology_layer,
            provider=self.service.provider.name,
        )
        advisories = [check.detail or check.name for check in discovery.evaluation.advisories]
        for advisory in advisories:
            logger.info("asset discovery advisory for %s: %s", capability_id, advisory)

        if not discovery.evaluation.passed:
            reason = "; ".join(
                check.detail or check.name for check in discovery.evaluation.failures
            )
            return AssetOutcome(
                capability_id=capability_id,
                discovery_run_id=discovery_run_id,
                advisories=advisories,
                skipped_reason=reason,
            )

        material = set(material_candidates(discovery.output))
        resolutions: list[AssetResolution] = []
        exposures: list[PersistedExposures] = []

        for index, proposal in enumerate(discovery.output.candidates):
            resolution = await self.assets.resolve(
                proposal, capability_id=capability_id, agent_run_id=discovery_run_id
            )
            resolutions.append(resolution)
            if resolution.resolved is None:
                logger.info(
                    "unresolved asset candidate %r: %s", proposal.proposed_name, resolution.reason
                )
                continue

            await self._link(
                capability_id,
                resolution.resolved.asset_id,
                confidence=proposal.confidence,
                rationale=proposal.exposure_pathway,
                agent_run_id=discovery_run_id,
            )
            # Only material exposures are worth a second call. An Asset that
            # touches the Capability incidentally is not an expression of it.
            if index in material:
                persisted = await self._estimate_exposure(
                    resolution.resolved.asset_id,
                    resolution.resolved.name,
                    capability,
                    proposal,
                    as_of=as_of,
                )
                if persisted is not None:
                    exposures.append(persisted)

        return AssetOutcome(
            capability_id=capability_id,
            resolutions=resolutions,
            exposures=exposures,
            discovery_run_id=discovery_run_id,
            advisories=advisories,
        )

    async def _estimate_exposure(
        self,
        asset_id: uuid.UUID,
        asset_name: str,
        capability: Capability,
        proposal: ProposedAssetCandidate,
        *,
        as_of: datetime,
    ) -> PersistedExposures | None:
        payload = AssetExposureInput(
            as_of=as_of,
            asset_id=str(asset_id),
            asset_name=asset_name,
            capability_id=str(capability.capability_id),
            capability_name=capability.name,
            business_description=proposal.exposure_pathway,
        )
        try:
            estimate = await self.exposure.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("exposure estimation failed for %s: %s", asset_id, exc)
            return None

        run_id = await self.runs.record(
            estimate,
            payload=payload,
            prompt=ASSET_EXPOSURE_V1,
            ontology_layer=self.exposure.ontology_layer,
            provider=self.service.provider.name,
        )
        if not estimate.evaluation.passed or not estimate.output.exposures:
            return None

        return await self.exposures.persist(
            asset_id,
            capability.capability_id,
            estimate.output.exposures,
            target_type=EntityType.CAPABILITY,
            agent_run_id=run_id,
            observed_at=as_of,
            offsetting=tuple(estimate.output.offsetting_exposures),
        )

    async def _link(
        self,
        capability_id: uuid.UUID,
        asset_id: uuid.UUID,
        *,
        confidence: float,
        rationale: str,
        agent_run_id: uuid.UUID,
    ) -> None:
        try:
            await self.graph.relate(
                source_id=capability_id,
                target_id=asset_id,
                relationship_type=RelationshipType.EXPRESSED_BY,
                confidence=confidence,
                rationale=rationale,
                agent_run_id=agent_run_id,
            )
        except IllegalEdgeError:
            logger.exception("refused an illegal edge from capability %s", capability_id)

    async def _pending_capability_ids(self, limit: int) -> list[uuid.UUID]:
        """Capabilities required by a binding Bottleneck and not yet expressed.

        Discovery is driven by the constraint that actually binds: a Capability
        attached only to a future constraint has no investable universe worth
        building yet.
        """
        expressed = select(Relationship.source_id).where(
            Relationship.relationship_type == RelationshipType.EXPRESSED_BY,
            Relationship.valid_to.is_(None),
        )
        query = (
            select(Relationship.target_id)
            .join(Bottleneck, Bottleneck.bottleneck_id == Relationship.source_id)
            .where(
                Relationship.relationship_type == RelationshipType.REQUIRES,
                Relationship.valid_to.is_(None),
                Bottleneck.valid_to.is_(None),
                Bottleneck.currently_binding.is_(True),
                Bottleneck.resolved.is_(False),
                Relationship.target_id.notin_(expressed),
            )
            .distinct()
            .limit(limit)
        )
        async with self.session_factory() as session:
            return list((await session.execute(query)).scalars())

    async def _capability(self, capability_id: uuid.UUID) -> Capability | None:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(Capability).where(
                        Capability.capability_id == capability_id,
                        Capability.valid_to.is_(None),
                    )
                )
            ).scalar_one_or_none()

    async def _context(
        self, capability_id: uuid.UUID
    ) -> tuple[list[Process], ProcessArchetype | None, datetime]:
        """The Processes reaching this Capability, and the archetype they share.

        Where several Processes converge on one Capability and disagree about
        archetype, none is imposed: the breadth check then stays quiet rather
        than flagging an equity-only answer on a Process it may not describe.
        """
        async with self.session_factory() as session:
            processes = list(
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
                ).scalars()
            )
            as_of: datetime | None = None
            if processes:
                as_of = (
                    await session.execute(
                        select(func.max(ProcessState.observed_at)).where(
                            ProcessState.process_id.in_([p.process_id for p in processes])
                        )
                    )
                ).scalar_one_or_none()

        archetypes = {p.archetype for p in processes if p.archetype is not None}
        archetype = archetypes.pop() if len(archetypes) == 1 else None
        return processes, archetype, as_of or _fallback_as_of(processes)


def _fallback_as_of(processes: list[Process]) -> datetime:
    """Date the run by the newest Process the Capability serves.

    Never ``now()``: a Capability discovered from evidence that ends in July is
    a July observation, and dating it today corrupts point-in-time queries.
    """
    from econiq_ontology import utcnow

    if not processes:
        return utcnow()
    return max(process.created_at for process in processes)
