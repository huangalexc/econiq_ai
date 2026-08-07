"""Stage definitions — the resumable workflow the issue asks for.

Each stage declares what it consumes, what it emits and how to name a unit of
its work. That declaration is the workflow definition: the pipeline of ontology
§46 is expressed as data here rather than as control flow, so it can be
inspected, tested, and — if the day comes — handed to Temporal without rewriting
the stages themselves.

Two rules the whole design rests on:

**Nothing propagates synchronously.** A document does not walk the graph on
arrival. Each stage records what it did; the next stage is *scheduled*, and may
run in a second or a day (ontology §46).

**The reconciler is the authority, the event path is the accelerator.** Every
stage can also derive its own pending work from ontology state, which is what
the ``run_pending`` methods already do. A dropped event is therefore a latency
problem, never a correctness one.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from econiq_orchestration.events import DomainEvent
from econiq_orchestration.queue import Priority


class Stage:
    """Stage names. Strings because they are stored on work items."""

    EXTRACT_CLAIMS = "extract_claims"
    RESOLVE_EVENTS = "resolve_events"
    DISCOVER_PROCESSES = "discover_processes"
    ESTIMATE_STATE = "estimate_state"
    CRITIQUE_PROCESS = "critique_process"
    MAP_CAPABILITIES = "map_capabilities"
    DISCOVER_ASSETS = "discover_assets"


#: Signature of a stage handler. Takes the work payload, returns the events its
#: work produced. The runner is responsible for everything else.
StageHandler = Callable[[uuid.UUID | None, dict[str, object]], Awaitable[Sequence[object]]]


@dataclass(frozen=True, slots=True)
class StageDefinition:
    """One stage of the pipeline, described rather than coded.

    ``triggered_by`` is what makes the pipeline event-driven without any stage
    knowing who follows it: a stage emits what happened, and whichever stages
    declared an interest get scheduled.
    """

    name: str
    triggered_by: tuple[DomainEvent, ...]
    emits: tuple[DomainEvent, ...]
    priority: int = Priority.DEFAULT
    max_attempts: int = 3
    concurrency: int = 4
    """Simultaneous units of this stage. Reasoning-tier stages run narrow: cost
    and provider rate limits both argue against forty concurrent Opus calls."""

    subject_from_payload: bool = True
    """Whether a unit of work targets one subject, or sweeps (event resolution
    batches many Claims and so has no single subject)."""

    description: str = ""

    def key_for(self, subject_id: uuid.UUID | None) -> str:
        """The idempotency key for a unit of this stage's work."""
        return f"{self.name}:{subject_id}" if subject_id else self.name


#: The pipeline of ontology §46, declared. Reading down this list is reading the
#: staged architecture: documents accumulate into Events, Events accumulate
#: before moving Processes, and Asset work happens only when the layers above it
#: actually changed.
PIPELINE: tuple[StageDefinition, ...] = (
    StageDefinition(
        name=Stage.EXTRACT_CLAIMS,
        triggered_by=(DomainEvent.DOCUMENT_INGESTED,),
        emits=(DomainEvent.CLAIMS_EXTRACTED,),
        priority=Priority.LIVE,
        concurrency=8,
        description="Document → Claims. High volume, cheap tiers, safe to run wide.",
    ),
    StageDefinition(
        name=Stage.RESOLVE_EVENTS,
        triggered_by=(DomainEvent.CLAIMS_EXTRACTED,),
        emits=(DomainEvent.EVENT_CREATED, DomainEvent.EVENT_UPDATED, DomainEvent.EVENT_PROPAGATED),
        priority=Priority.DEFAULT,
        concurrency=1,
        subject_from_payload=False,
        description=(
            "Claims → Events. Batched and single-flighted on purpose: two "
            "concurrent passes over overlapping Claims would cluster the same "
            "occurrence twice and the duplicate would look like corroboration."
        ),
    ),
    StageDefinition(
        name=Stage.DISCOVER_PROCESSES,
        triggered_by=(DomainEvent.EVENT_PROPAGATED,),
        emits=(
            DomainEvent.PROCESS_CREATED,
            DomainEvent.PROCESS_UPDATED,
            DomainEvent.STATE_TRANSITION_CANDIDATE,
        ),
        priority=Priority.LIVE,
        concurrency=2,
        description="Only Events that cleared the significance gate reach here.",
    ),
    StageDefinition(
        name=Stage.ESTIMATE_STATE,
        triggered_by=(DomainEvent.PROCESS_CREATED, DomainEvent.STATE_TRANSITION_CANDIDATE),
        emits=(DomainEvent.STATE_RECORDED,),
        priority=Priority.DEFAULT,
        concurrency=2,
        description="Archetype then State, for Processes whose beliefs moved.",
    ),
    StageDefinition(
        name=Stage.CRITIQUE_PROCESS,
        triggered_by=(DomainEvent.STATE_RECORDED,),
        emits=(DomainEvent.THESIS_CRITIQUED,),
        priority=Priority.RECONCILED,
        concurrency=1,
        description=(
            "Adversarial critique. Deliberately low priority: it is the most "
            "expensive call in the pipeline and nothing downstream blocks on it."
        ),
    ),
    StageDefinition(
        name=Stage.MAP_CAPABILITIES,
        triggered_by=(DomainEvent.STATE_RECORDED,),
        emits=(DomainEvent.BOTTLENECK_UPDATED, DomainEvent.CAPABILITY_UPDATED),
        priority=Priority.DEFAULT,
        concurrency=2,
        description="Constraints follow from State, so this waits for State.",
    ),
    StageDefinition(
        name=Stage.DISCOVER_ASSETS,
        triggered_by=(DomainEvent.CAPABILITY_UPDATED,),
        emits=(DomainEvent.ASSET_UPDATED,),
        priority=Priority.DEFAULT,
        concurrency=2,
        description="The last layer, and the only one permitted to name an instrument.",
    ),
)

BY_NAME: dict[str, StageDefinition] = {stage.name: stage for stage in PIPELINE}


def stages_for(event: DomainEvent) -> tuple[StageDefinition, ...]:
    """Which stages an event should schedule."""
    return tuple(stage for stage in PIPELINE if event in stage.triggered_by)


@dataclass(frozen=True, slots=True)
class StageRegistry:
    """Stage definitions bound to their handlers.

    Kept apart from ``PIPELINE`` so the shape of the pipeline can be reasoned
    about — and tested — without constructing an LLM service or a database
    session.
    """

    handlers: dict[str, StageHandler] = field(default_factory=dict)

    def register(self, stage: str, handler: StageHandler) -> None:
        if stage not in BY_NAME:
            raise KeyError(f"unknown stage {stage!r}; known: {sorted(BY_NAME)}")
        self.handlers[stage] = handler

    def handler_for(self, stage: str) -> StageHandler | None:
        return self.handlers.get(stage)

    @property
    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self.handlers))

    @property
    def unregistered(self) -> tuple[str, ...]:
        """Stages with no handler — visible rather than silently inert."""
        return tuple(sorted(set(BY_NAME) - set(self.handlers)))
