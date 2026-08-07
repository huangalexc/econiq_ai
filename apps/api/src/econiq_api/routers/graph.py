"""Graph endpoints — traversal, reach and integrity.

``/reach`` is the query tech rec §6 uses to argue for a graph database, exposed
directly: "every Asset within N causal hops of these Processes". It is served by
a recursive CTE over Postgres (see ``docs/graph-projection.md``).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from econiq_graph import Direction, GraphIntegrity, TraversalSpec
from fastapi import APIRouter, Query

from econiq_api.deps import AsOfDep, GraphDep, SessionFactoryDep
from econiq_api.schemas import (
    AssetReachOut,
    DiscoveryPathOut,
    GraphEdgeOut,
    GraphNodeOut,
    IntegrityReportOut,
    IntegrityViolationOut,
    NodeRef,
    PathStepOut,
    SubgraphOut,
)

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/reach", response_model=list[AssetReachOut])
async def asset_reach(
    graph: GraphDep,
    as_of: AsOfDep,
    process_id: Annotated[list[uuid.UUID], Query(min_length=1)],
    max_hops: Annotated[int, Query(ge=1, le=8)] = 4,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AssetReachOut]:
    """Assets reachable from these Processes, most-converged-on first."""
    reaches = await graph.assets_within_hops(
        process_id, max_hops=max_hops, as_of=as_of, limit=limit
    )
    return [
        AssetReachOut(
            asset=NodeRef(
                id=reach.asset.node_id,
                type=reach.asset.node_type,
                label=reach.asset.label,
                slug=reach.asset.slug,
            ),
            shortest_hops=reach.shortest_hops,
            distinct_source_count=len(reach.distinct_sources),
            best_weight=reach.best_weight,
            paths=[_path_out(path) for path in reach.paths],
        )
        for reach in reaches
    ]


@router.get("/subgraph", response_model=SubgraphOut)
async def subgraph(
    graph: GraphDep,
    as_of: AsOfDep,
    node_id: Annotated[list[uuid.UUID], Query(min_length=1)],
    depth: Annotated[int, Query(ge=1, le=4)] = 2,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> SubgraphOut:
    """Nodes and edges around a set of seeds, for the explorer (issue #26)."""
    result = await graph.subgraph(node_id, depth=depth, as_of=as_of, limit=limit)
    return SubgraphOut(
        nodes=[
            GraphNodeOut(id=n.node_id, type=n.node_type, label=n.label, slug=n.slug)
            for n in result.nodes
        ],
        edges=[
            GraphEdgeOut(
                source_id=e.source_id,
                target_id=e.target_id,
                relationship_type=e.relationship_type,
                weight=e.weight,
                confidence=e.confidence,
                rationale=e.rationale,
            )
            for e in result.edges
        ],
    )


@router.get("/paths", response_model=list[DiscoveryPathOut])
async def paths(
    graph: GraphDep,
    as_of: AsOfDep,
    node_id: Annotated[list[uuid.UUID], Query(min_length=1)],
    direction: Direction = Direction.DOWNSTREAM,
    max_hops: Annotated[int, Query(ge=1, le=8)] = 3,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[DiscoveryPathOut]:
    results = await graph.traverse(
        node_id,
        TraversalSpec(max_hops=max_hops, direction=direction, as_of=as_of, limit=limit),
    )
    return [_path_out(path) for path in results]


@router.get("/integrity", response_model=IntegrityReportOut)
async def integrity(factory: SessionFactoryDep) -> IntegrityReportOut:
    """Structural checks Postgres cannot express (issue #13).

    Exposed because the Research Quality Auditor (#57) and the eval harness both
    need it, and because a graph that has quietly acquired a causal cycle should
    be visible rather than discovered through a traversal that makes no sense.
    """
    report = await GraphIntegrity(factory).check()
    return IntegrityReportOut(
        ok=report.ok,
        checked_at=report.checked_at,
        violations=[
            IntegrityViolationOut(kind=v.kind, node_id=v.node_id, detail=v.detail)
            for v in report.violations
        ],
    )


def _path_out(path: object) -> DiscoveryPathOut:
    from econiq_graph import Path

    assert isinstance(path, Path)
    return DiscoveryPathOut(
        start=NodeRef(
            id=path.start.node_id,
            type=path.start.node_type,
            label=path.start.label,
            slug=path.start.slug,
        ),
        steps=[
            PathStepOut(
                relationship_type=edge.relationship_type,
                rationale=edge.rationale,
                to=NodeRef(id=node.node_id, type=node.node_type, label=node.label, slug=node.slug),
            )
            for edge, node in zip(path.edges, path.nodes[1:], strict=True)
        ],
        depth=path.depth,
        weight=path.weight,
    )
