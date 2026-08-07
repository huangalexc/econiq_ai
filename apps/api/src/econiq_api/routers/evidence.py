"""Evidence endpoints — the provenance drill-down.

One endpoint, deliberately general: any node can be asked what stands behind it,
because "every material statement is traceable" (agent doc §2.4) is a property
of the system rather than of one screen.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from econiq_api.deps import AsOfDep, GraphDep
from econiq_api.errors import not_found
from econiq_api.schemas import EvidenceTrailOut, NodeRef

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


@router.get("/{node_id}", response_model=EvidenceTrailOut)
async def evidence_trail(node_id: uuid.UUID, graph: GraphDep, as_of: AsOfDep) -> EvidenceTrailOut:
    """Trace a node back through Events and Claims to its documents."""
    try:
        trail = await graph.evidence_trail(node_id, as_of=as_of)
    except LookupError as exc:
        raise not_found("node", node_id) from exc

    return EvidenceTrailOut(
        subject=NodeRef(
            id=trail.subject.node_id,
            type=trail.subject.node_type,
            label=trail.subject.label,
            slug=trail.subject.slug,
        ),
        supporting_events=[
            NodeRef(id=e.node_id, type=e.node_type, label=e.label, slug=e.slug)
            for e in trail.events
        ],
        contradicting_events=[
            NodeRef(id=e.node_id, type=e.node_type, label=e.label, slug=e.slug)
            for e in trail.contradicting_events
        ],
        claim_ids=list(trail.claims),
        document_ids=list(trail.documents),
        is_evidenced=trail.is_evidenced,
    )
