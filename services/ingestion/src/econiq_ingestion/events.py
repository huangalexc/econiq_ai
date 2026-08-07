"""Domain events.

Documents never propagate synchronously through the graph (ontology §46). The
pipeline announces what happened and stops; deciding what that should trigger is
the orchestrator's job (issue #14). Keeping the two apart is what makes updates
staged rather than cascading.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from econiq_ontology import DocumentType, utcnow


@dataclass(frozen=True, slots=True)
class DocumentIngested:
    """A new document is stored, parsed and ready for Claim extraction."""

    document_id: uuid.UUID
    source: str
    document_type: DocumentType
    publication_time: datetime
    content_hash: str
    storage_uri: str
    section_count: int
    occurred_at: datetime = field(default_factory=utcnow)
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)

    name = "document.ingested"


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, event: DocumentIngested) -> None: ...


class InMemoryEventPublisher:
    """Collects events. Used by tests and single-process batch runs."""

    def __init__(self) -> None:
        self.events: list[DocumentIngested] = []

    def publish(self, event: DocumentIngested) -> None:
        self.events.append(event)


class NullEventPublisher:
    """Drops events.

    For backfills where propagation is deliberately deferred: re-ingesting a
    historical corpus should not fire thousands of downstream updates.
    """

    def publish(self, event: DocumentIngested) -> None:
        return None
