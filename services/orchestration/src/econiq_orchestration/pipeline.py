"""Binding the Phase 0 stages to the orchestrator.

The stage handlers are thin on purpose: each one calls the stage object that
already exists, translates its outcome into domain events, and stops. All the
judgement lives in the stages; this file only knows what follows what.

The reconciler finders are the ``run_pending``-style queries the stages already
carry. That is the property that makes the event path optional for correctness:
the same question ("what is outstanding?") is answerable from ontology state.

``extract_claims`` is deliberately not registered here. It needs the parsed
document, which lives in the ingestion result rather than in the graph, so the
ingestion worker owns that stage and publishes ``claims.extracted`` when it is
done. Everything downstream is graph-driven and belongs to this orchestrator.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from econiq_agents import (
    AssetDiscoveryStage,
    CapabilityStage,
    EventResolutionStage,
    ProcessCritiqueStage,
    ProcessDiscoveryStage,
    ProcessStateStage,
)
from econiq_llm import LLMService
from econiq_ontology import EntityType
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_orchestration.events import DomainEvent, Emitted
from econiq_orchestration.runner import Orchestrator
from econiq_orchestration.stages import Stage, StageRegistry


def build_orchestrator(
    service: LLMService,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker_name: str = "orchestrator",
) -> Orchestrator:
    """Wire the Phase 0 pipeline into a runnable orchestrator."""
    events = EventResolutionStage(service, session_factory)
    processes = ProcessDiscoveryStage(service, session_factory)
    states = ProcessStateStage(service, session_factory)
    critique = ProcessCritiqueStage(service, session_factory)
    capabilities = CapabilityStage(service, session_factory)
    assets = AssetDiscoveryStage(service, session_factory)

    registry = StageRegistry()

    async def resolve_events(
        _subject: uuid.UUID | None, _payload: dict[str, object]
    ) -> Sequence[Emitted]:
        outcome = await events.run()
        emitted: list[Emitted] = []
        for resolved in outcome.events:
            emitted.append(
                Emitted(
                    name=(
                        DomainEvent.EVENT_CREATED
                        if resolved.persisted.created
                        else DomainEvent.EVENT_UPDATED
                    ),
                    subject_id=resolved.persisted.event_id,
                    subject_type=EntityType.EVENT,
                )
            )
            # Only a propagated Event moves the Process layer. This is the gate
            # of ontology §46, expressed as an event nobody else emits.
            if resolved.propagated:
                emitted.append(
                    Emitted(
                        name=DomainEvent.EVENT_PROPAGATED,
                        subject_id=resolved.persisted.event_id,
                        subject_type=EntityType.EVENT,
                    )
                )
        return emitted

    async def discover_processes(
        subject: uuid.UUID | None, _payload: dict[str, object]
    ) -> Sequence[Emitted]:
        if subject is None:
            return []
        outcome = await processes.run(subject)
        emitted: list[Emitted] = [
            Emitted(
                name=DomainEvent.PROCESS_CREATED,
                subject_id=created.process_id,
                subject_type=EntityType.PROCESS,
            )
            for created in outcome.created
        ]
        emitted += [
            Emitted(
                name=DomainEvent.PROCESS_UPDATED,
                subject_id=update.process_id,
                subject_type=EntityType.PROCESS,
            )
            for update in outcome.updated
        ]
        # The signal issue #8 carries rather than acts on: the State layer has
        # one owner, and this is how it hears about it.
        emitted += [
            Emitted(
                name=DomainEvent.STATE_TRANSITION_CANDIDATE,
                subject_id=process_id,
                subject_type=EntityType.PROCESS,
            )
            for process_id in outcome.needs_state_review
        ]
        return emitted

    async def estimate_state(
        subject: uuid.UUID | None, _payload: dict[str, object]
    ) -> Sequence[Emitted]:
        if subject is None:
            return []
        outcome = await states.run(subject)
        if outcome.state is None:
            return []
        return [
            Emitted(
                name=DomainEvent.STATE_RECORDED,
                subject_id=subject,
                subject_type=EntityType.PROCESS,
                payload={"state_changed": outcome.state_changed},
            )
        ]

    async def critique_process(
        subject: uuid.UUID | None, _payload: dict[str, object]
    ) -> Sequence[Emitted]:
        if subject is None:
            return []
        outcome = await critique.run(subject)
        if not outcome.critique_ids:
            return []
        return [
            Emitted(
                name=DomainEvent.THESIS_CRITIQUED,
                subject_id=subject,
                subject_type=EntityType.PROCESS,
                payload={"findings": len(outcome.critique_ids)},
            )
        ]

    async def map_capabilities(
        subject: uuid.UUID | None, _payload: dict[str, object]
    ) -> Sequence[Emitted]:
        if subject is None:
            return []
        outcome = await capabilities.run(subject)
        emitted: list[Emitted] = [
            Emitted(
                name=DomainEvent.BOTTLENECK_UPDATED,
                subject_id=bottleneck.bottleneck_id,
                subject_type=EntityType.BOTTLENECK,
            )
            for bottleneck in outcome.bottlenecks
        ]
        if outcome.requirement is not None:
            emitted += [
                Emitted(
                    name=DomainEvent.CAPABILITY_UPDATED,
                    subject_id=resolved.capability_id,
                    subject_type=EntityType.CAPABILITY,
                )
                for resolved in outcome.requirement.capabilities
            ]
        return emitted

    async def discover_assets(
        subject: uuid.UUID | None, _payload: dict[str, object]
    ) -> Sequence[Emitted]:
        if subject is None:
            return []
        outcome = await assets.run(subject)
        return [
            Emitted(
                name=DomainEvent.ASSET_UPDATED,
                subject_id=resolution.resolved.asset_id,
                subject_type=EntityType.ASSET,
            )
            for resolution in outcome.resolutions
            if resolution.resolved is not None
        ]

    registry.register(Stage.RESOLVE_EVENTS, resolve_events)
    registry.register(Stage.DISCOVER_PROCESSES, discover_processes)
    registry.register(Stage.ESTIMATE_STATE, estimate_state)
    registry.register(Stage.CRITIQUE_PROCESS, critique_process)
    registry.register(Stage.MAP_CAPABILITIES, map_capabilities)
    registry.register(Stage.DISCOVER_ASSETS, discover_assets)

    orchestrator = Orchestrator(session_factory, registry, worker_name=worker_name)

    # The backstops. Each asks ontology state what is outstanding, which is why
    # a dropped domain event costs latency rather than correctness.
    orchestrator.reconciler.register(
        Stage.DISCOVER_PROCESSES, lambda: processes._pending_event_ids(50)
    )
    orchestrator.reconciler.register(Stage.ESTIMATE_STATE, lambda: states._pending_process_ids(50))
    orchestrator.reconciler.register(
        Stage.CRITIQUE_PROCESS, lambda: critique._pending_process_ids(50)
    )
    orchestrator.reconciler.register(
        Stage.MAP_CAPABILITIES, lambda: capabilities._pending_process_ids(50)
    )
    orchestrator.reconciler.register(
        Stage.DISCOVER_ASSETS, lambda: assets._pending_capability_ids(50)
    )
    return orchestrator
