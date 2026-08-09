"""Evidence endpoints — the provenance drill-down (issue #24).

Deliberately general: any node can be asked what stands behind it, because
"every material statement is traceable" (agent doc §2.4) is a property of the
system rather than of one screen.

Two endpoints, at two depths. ``/api/evidence/{id}`` returns the shape of the
trail — which Events support or contradict, how many Claims and documents —
which is what a summary badge needs. ``/inspect`` returns the Claims themselves
with their verified spans and the run that extracted each, because ui_concept
§29 is explicit that evidence must never be shown as "an undifferentiated AI
summary", and a list of identifiers is exactly that with extra steps.

They are separate because the second is much more expensive and most callers
want the first.
"""

from __future__ import annotations

import uuid

from econiq_data_models import Claim, Document, Event
from econiq_graph import GraphNode
from fastapi import APIRouter
from sqlalchemy import func, select

from econiq_api import provenance
from econiq_api.deps import AsOfDep, GraphDep, SessionDep
from econiq_api.errors import not_found
from econiq_api.schemas import (
    ClaimOut,
    DocumentOut,
    EvidenceTrailOut,
    NodeRef,
    ProvenanceInspectionOut,
)

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


@router.get("/{node_id}", response_model=EvidenceTrailOut)
async def evidence_trail(node_id: uuid.UUID, graph: GraphDep, as_of: AsOfDep) -> EvidenceTrailOut:
    """Trace a node back through Events and Claims to its documents."""
    try:
        trail = await graph.evidence_trail(node_id, as_of=as_of)
    except LookupError as exc:
        raise not_found("node", node_id) from exc

    return EvidenceTrailOut(
        subject=_ref(trail.subject),
        supporting_events=[_ref(e) for e in trail.events],
        contradicting_events=[_ref(e) for e in trail.contradicting_events],
        claim_ids=list(trail.claims),
        document_ids=list(trail.documents),
        is_evidenced=trail.is_evidenced,
    )


@router.get("/{node_id}/inspect", response_model=ProvenanceInspectionOut)
async def inspect(
    node_id: uuid.UUID, session: SessionDep, graph: GraphDep, as_of: AsOfDep
) -> ProvenanceInspectionOut:
    """The full chain behind a node: Events, Claims, spans, documents, runs.

    This is the endpoint the trust argument rests on. A user who cannot get from
    a conclusion to the sentence in the document that produced it has to take
    the conclusion on faith, which is the thing this system exists not to ask.
    """
    try:
        trail = await graph.evidence_trail(node_id, as_of=as_of)
    except LookupError as exc:
        raise not_found("node", node_id) from exc

    claims = (
        (
            await session.execute(
                select(Claim).where(Claim.claim_id.in_(trail.claims)).order_by(Claim.created_at)
            )
        )
        .scalars()
        .all()
        if trail.claims
        else []
    )
    documents = (
        (
            await session.execute(
                select(Document)
                .where(Document.document_id.in_(trail.documents))
                .order_by(Document.publication_time.desc())
            )
        )
        .scalars()
        .all()
        if trail.documents
        else []
    )
    attribution = await provenance.load(session, (claim.agent_run_id for claim in claims))

    # Summed over Events rather than counting documents: four syndicated copies
    # of one wire report are one source (ontology §47), and the Event layer has
    # already done that arithmetic.
    independent = 0
    if trail.events:
        event_query = select(func.coalesce(func.sum(Event.independent_source_count), 0)).where(
            Event.event_id.in_([e.node_id for e in trail.events]),
            Event.valid_to.is_(None),
        )
        independent = (await session.execute(event_query)).scalar_one()

    return ProvenanceInspectionOut(
        subject=_ref(trail.subject),
        is_evidenced=trail.is_evidenced,
        supporting_events=[_ref(e) for e in trail.events],
        contradicting_events=[_ref(e) for e in trail.contradicting_events],
        claims=[
            ClaimOut(
                id=claim.claim_id,
                document_id=claim.document_id,
                text=claim.text,
                claim_type=claim.claim_type.value,
                assertion_source=claim.assertion_source,
                attributed_to=claim.attributed_to,
                extraction_confidence=claim.extraction_confidence,
                source_location=dict(claim.source_location),
                stated_at=claim.stated_at,
                provenance=(attribution.get(claim.agent_run_id) if claim.agent_run_id else None),
            )
            for claim in claims
        ],
        documents=[
            DocumentOut(
                id=document.document_id,
                source=document.source,
                publisher=document.publisher,
                title=document.title,
                url=document.url,
                document_type=document.document_type.value,
                publication_time=document.publication_time,
                storage_uri=document.storage_uri,
            )
            for document in documents
        ],
        independent_source_count=independent,
    )


def _ref(node: GraphNode) -> NodeRef:
    return NodeRef(id=node.node_id, type=node.node_type, label=node.label, slug=node.slug)
