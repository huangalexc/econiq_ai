"""Staged, triggered updates over the ontology pipeline (issue #14).

Documents do not propagate synchronously through the graph (ontology §46).
Each stage records what it did and schedules what follows; the queue is
Postgres, the events are a transactional outbox, and a reconciler sweeps for
anything the event path missed. ``docs/orchestration.md`` records why this
rather than a workflow engine, and what would change that.
"""

from econiq_orchestration.events import DomainEvent, Emitted, Outbox, StoredEvent
from econiq_orchestration.pipeline import build_orchestrator
from econiq_orchestration.queue import (
    ClaimedWork,
    Enqueued,
    Priority,
    QueueDepth,
    Trigger,
    WorkQueue,
    backoff_for,
)
from econiq_orchestration.runner import (
    Dispatcher,
    DispatchResult,
    Orchestrator,
    Reconciler,
    ReconcileResult,
    Worker,
    WorkResult,
    pipeline_summary,
)
from econiq_orchestration.stages import (
    BY_NAME,
    PIPELINE,
    Stage,
    StageDefinition,
    StageRegistry,
    stages_for,
)

__all__ = [
    "BY_NAME",
    "PIPELINE",
    "ClaimedWork",
    "DispatchResult",
    "Dispatcher",
    "DomainEvent",
    "Emitted",
    "Enqueued",
    "Orchestrator",
    "Outbox",
    "Priority",
    "QueueDepth",
    "ReconcileResult",
    "Reconciler",
    "Stage",
    "StageDefinition",
    "StageRegistry",
    "StoredEvent",
    "Trigger",
    "WorkQueue",
    "WorkResult",
    "Worker",
    "backoff_for",
    "build_orchestrator",
    "pipeline_summary",
    "stages_for",
]
