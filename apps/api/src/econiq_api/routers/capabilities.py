"""Bottleneck and Capability endpoints.

The requirement tree is returned as a tree. AND and OR over the same
Capabilities imply completely different sets of participants (ontology §12), so
flattening it for transport would hand the caller a structure that cannot answer
the question it was built to answer.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Annotated

from econiq_data_models import Bottleneck, Capability
from econiq_graph import GraphNode
from econiq_ontology import CapabilityLeaf, RelationshipType
from econiq_ontology.process_layer import RequirementNode as RequirementNodeModel
from fastapi import APIRouter, Query
from sqlalchemy import Select, select

from econiq_api.deps import AsOfDep, GraphDep, PageDep, SessionDep, SessionFactoryDep
from econiq_api.errors import not_found
from econiq_api.schemas import (
    BottleneckOut,
    CapabilityDetailOut,
    CapabilityOut,
    NodeRef,
    RequirementNodeOut,
    RequirementOut,
)
from econiq_api.temporal import current_revision

router = APIRouter(prefix="/api", tags=["capabilities"])


@router.get("/bottlenecks", response_model=list[BottleneckOut])
async def list_bottlenecks(
    session: SessionDep,
    page: PageDep,
    as_of: AsOfDep,
    binding_only: Annotated[
        bool, Query(description="Only constraints that bind now, not ones that would later.")
    ] = False,
    process_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[BottleneckOut]:
    query: Select[tuple[Bottleneck]] = select(Bottleneck)
    query = current_revision(query, Bottleneck, as_of)
    if binding_only:
        query = query.where(Bottleneck.currently_binding.is_(True), Bottleneck.resolved.is_(False))
    if process_id is not None:
        query = query.where(Bottleneck.process_id == process_id)

    rows = (
        (
            await session.execute(
                query.order_by(Bottleneck.created_at.desc()).limit(page.limit).offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return [BottleneckOut.from_row(row) for row in rows]


@router.get("/bottlenecks/{bottleneck_id}", response_model=BottleneckOut)
async def get_bottleneck(
    bottleneck_id: uuid.UUID, session: SessionDep, as_of: AsOfDep
) -> BottleneckOut:
    query: Select[tuple[Bottleneck]] = select(Bottleneck).where(
        Bottleneck.bottleneck_id == bottleneck_id
    )
    row = (await session.execute(current_revision(query, Bottleneck, as_of))).scalar_one_or_none()
    if row is None:
        raise not_found("bottleneck", bottleneck_id)
    return BottleneckOut.from_row(row)


@router.get("/bottlenecks/{bottleneck_id}/requirements", response_model=RequirementOut)
async def get_requirements(
    bottleneck_id: uuid.UUID, factory: SessionFactoryDep, graph: GraphDep
) -> RequirementOut:
    """The AND/OR/optional structure that would resolve this constraint."""
    from econiq_agents import CapabilityWriter, EmbeddingStore, HashingEmbedder

    writer = CapabilityWriter(factory, EmbeddingStore(factory, HashingEmbedder()))
    requirement = await writer.load_requirement(bottleneck_id)
    if requirement is None:
        raise not_found("requirement for bottleneck", bottleneck_id)

    labels = await graph.nodes(sorted(requirement.capability_ids()))
    return RequirementOut(
        bottleneck_id=bottleneck_id,
        revision=requirement.revision,
        root=_node_out(requirement.root, labels),
        capability_count=len(requirement.capability_ids()),
    )


@router.get("/capabilities", response_model=list[CapabilityOut])
async def list_capabilities(
    session: SessionDep, page: PageDep, as_of: AsOfDep
) -> list[CapabilityOut]:
    query: Select[tuple[Capability]] = select(Capability)
    rows = (
        (
            await session.execute(
                current_revision(query, Capability, as_of)
                .order_by(Capability.created_at.desc())
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return [_capability_out(row) for row in rows]


@router.get("/capabilities/{capability_id}", response_model=CapabilityDetailOut)
async def get_capability(
    capability_id: uuid.UUID, session: SessionDep, graph: GraphDep, as_of: AsOfDep
) -> CapabilityDetailOut:
    query: Select[tuple[Capability]] = select(Capability).where(
        Capability.capability_id == capability_id
    )
    row = (await session.execute(current_revision(query, Capability, as_of))).scalar_one_or_none()
    if row is None:
        raise not_found("capability", capability_id)

    # Upstream Processes are read off the graph rather than stored: confluence
    # is a structural fact (ontology §13), and a cached count would drift.
    upstream = await graph.confluence(capability_id, as_of=as_of)
    expressed = await graph.neighbors(
        capability_id,
        relationship_types=[RelationshipType.EXPRESSED_BY],
        as_of=as_of,
    )
    assets = await graph.nodes([edge.target_id for edge in expressed])

    return CapabilityDetailOut(
        **_capability_out(row).model_dump(),
        upstream_processes=[
            NodeRef(
                id=path.end.node_id,
                type=path.end.node_type,
                label=path.end.label,
                slug=path.end.slug,
            )
            for path in upstream
        ],
        expressed_by=[
            NodeRef(id=n.node_id, type=n.node_type, label=n.label, slug=n.slug)
            for n in assets.values()
        ],
    )


def _capability_out(row: Capability) -> CapabilityOut:
    return CapabilityOut(
        id=row.capability_id,
        name=row.name,
        slug=row.slug,
        description=row.description,
        aliases=list(row.aliases),
    )


def _node_out(
    node: RequirementNodeModel, labels: Mapping[uuid.UUID, GraphNode]
) -> RequirementNodeOut:
    if isinstance(node, CapabilityLeaf):
        label = labels.get(node.capability_id)
        return RequirementNodeOut(
            kind="capability",
            capability=(
                NodeRef(
                    id=label.node_id,
                    type=label.node_type,
                    label=label.label,
                    slug=label.slug,
                )
                if label is not None
                else None
            ),
            necessity=node.necessity,
            weight=node.weight,
        )
    return RequirementNodeOut(
        kind="group",
        operator=node.operator,
        label=node.label,
        necessity=node.necessity,
        weight=node.weight,
        children=[_node_out(child, labels) for child in node.children],
    )
