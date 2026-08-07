"""Event endpoints — the deduplication layer.

``independent_source_count`` is the field to read here, not the claim count: it
is what the Event layer computed after collapsing syndication (ontology §47),
and it is the number that makes accumulated evidence meaningful.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from econiq_data_models import Claim, Document, Event, EventClaim
from econiq_ontology import EventType
from fastapi import APIRouter, Query
from sqlalchemy import Select, select

from econiq_api.deps import AsOfDep, PageDep, SessionDep
from econiq_api.errors import not_found
from econiq_api.schemas import ClaimOut, DocumentOut, EventDetailOut, EventOut
from econiq_api.temporal import current_revision

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=list[EventOut])
async def list_events(
    session: SessionDep,
    page: PageDep,
    as_of: AsOfDep,
    event_type: Annotated[list[EventType] | None, Query()] = None,
    propagated_only: Annotated[
        bool, Query(description="Only Events that cleared the significance gate.")
    ] = False,
    min_materiality: Annotated[float | None, Query(ge=0, le=10)] = None,
) -> list[EventOut]:
    query: Select[tuple[Event]] = select(Event)
    query = current_revision(query, Event, as_of)
    if event_type:
        query = query.where(Event.event_type.in_(event_type))
    if propagated_only:
        query = query.where(Event.propagated_at.is_not(None))
    if min_materiality is not None:
        query = query.where(Event.materiality >= min_materiality)
    if as_of is not None:
        query = query.where(Event.occurred_at <= as_of)

    rows = (
        (
            await session.execute(
                query.order_by(Event.occurred_at.desc()).limit(page.limit).offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return [_event_out(row) for row in rows]


@router.get("/{event_id}", response_model=EventDetailOut)
async def get_event(event_id: uuid.UUID, session: SessionDep, as_of: AsOfDep) -> EventDetailOut:
    query: Select[tuple[Event]] = select(Event).where(Event.event_id == event_id)
    event = (await session.execute(current_revision(query, Event, as_of))).scalar_one_or_none()
    if event is None:
        raise not_found("event", event_id)

    rows = (
        await session.execute(
            select(Claim, Document)
            .join(EventClaim, EventClaim.claim_id == Claim.claim_id)
            .join(Document, Document.document_id == Claim.document_id)
            .where(EventClaim.event_id == event_id, EventClaim.removed_at.is_(None))
        )
    ).all()

    claims = [ClaimOut.model_validate(_claim_dict(row[0])) for row in rows]
    documents = {row[1].document_id: row[1] for row in rows}
    return EventDetailOut(
        **_event_out(event).model_dump(),
        claims=claims,
        documents=[_document_out(document) for document in documents.values()],
    )


def _event_out(event: Event) -> EventOut:
    return EventOut(
        id=event.event_id,
        event_type=event.event_type,
        title=event.title,
        description=event.description,
        occurred_at=event.occurred_at,
        independent_source_count=event.independent_source_count,
        novelty=event.novelty,
        materiality=event.materiality,
        confidence=event.confidence,
        contradictions=list(event.contradictions),
        propagated_at=event.propagated_at,
        revision=event.revision,
    )


def _claim_dict(claim: Claim) -> dict[str, object]:
    return {
        "id": claim.claim_id,
        "document_id": claim.document_id,
        "text": claim.text,
        "claim_type": claim.claim_type.value,
        "assertion_source": claim.assertion_source,
        "attributed_to": claim.attributed_to,
        "extraction_confidence": claim.extraction_confidence,
        "source_location": claim.source_location,
    }


def _document_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.document_id,
        source=document.source,
        publisher=document.publisher,
        title=document.title,
        url=document.url,
        document_type=document.document_type.value,
        publication_time=document.publication_time,
        storage_uri=document.storage_uri,
    )
