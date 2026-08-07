"""Traversal over the ontology graph (issue #13).

Postgres is the graph. Tech rec §6 is explicit that Neo4j, when it arrives, is a
projection rather than the source of truth — and the multi-hop query it names as
the motivating case ("every Asset within four causal hops of these Processes")
is a recursive CTE, which Postgres has had for years.

Two properties matter more than speed here:

**Point-in-time.** Every traversal takes an ``as_of`` and filters edges by their
validity window. Walking today's graph while claiming to describe July is the
single easiest way to produce a leaked backtest (ontology §33), so the temporal
filter is applied in one place and applied always.

**Termination.** The recursion carries the path it has walked and refuses to
revisit a node. Causal graphs acquire cycles — a Process influences another that
feeds back — and a traversal that assumes otherwise hangs in production rather
than failing in review.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from econiq_data_models import (
    Asset,
    Bottleneck,
    Capability,
    Claim,
    Document,
    Event,
    Process,
)
from econiq_ontology import EntityType, RelationshipType
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_graph.types import (
    DISCOVERY_EDGES,
    AssetReach,
    Direction,
    EvidenceTrail,
    GraphEdge,
    GraphNode,
    Path,
    Subgraph,
    TraversalSpec,
)

#: Entity tables that carry a display label, in node-type order. Labels live in
#: the per-type tables rather than on ``nodes`` so that renaming a Process is a
#: revision of the Process, not an update of the registry.
_LABEL_SOURCES: tuple[tuple[EntityType, str, str, bool], ...] = (
    (EntityType.PROCESS, Process.__tablename__, "process_id", True),
    (EntityType.BOTTLENECK, Bottleneck.__tablename__, "bottleneck_id", True),
    (EntityType.CAPABILITY, Capability.__tablename__, "capability_id", True),
    (EntityType.ASSET, Asset.__tablename__, "asset_id", True),
    (EntityType.EVENT, Event.__tablename__, "event_id", True),
    (EntityType.DOCUMENT, Document.__tablename__, "document_id", False),
    (EntityType.CLAIM, Claim.__tablename__, "claim_id", False),
)


def _label_union() -> str:
    """One query that resolves any node id to a label.

    A UNION over the entity tables rather than a denormalized label column: the
    label of a revisable entity belongs to its current revision, and copying it
    onto the registry would create a second thing to keep in step.
    """
    parts: list[str] = []
    for entity_type, table, id_column, versioned in _LABEL_SOURCES:
        label = "title" if entity_type in (EntityType.EVENT, EntityType.DOCUMENT) else "name"
        if entity_type is EntityType.CLAIM:
            label = "text"
        where = " WHERE valid_to IS NULL" if versioned else ""
        parts.append(
            f"SELECT {id_column} AS node_id, '{entity_type.value}' AS node_type, "
            f"{label} AS label FROM {table}{where}"
        )
    return "\nUNION ALL\n".join(parts)


class GraphQueries:
    """Read-only traversal and integrity queries over the ontology."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    # ---------------------------------------------------------------- nodes

    async def node(self, node_id: uuid.UUID) -> GraphNode | None:
        nodes = await self.nodes([node_id])
        return nodes.get(node_id)

    async def nodes(self, node_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, GraphNode]:
        """Resolve node ids to labelled nodes, in one round trip."""
        if not node_ids:
            return {}
        sql = text(
            f"""
            SELECT n.node_id, n.node_type, n.slug, COALESCE(l.label, '(unlabelled)') AS label
            FROM nodes n
            LEFT JOIN ({_label_union()}) l
                   ON l.node_id = n.node_id AND l.node_type = n.node_type::text
            WHERE n.node_id = ANY(:ids)
            """
        )
        async with self.session_factory() as session:
            rows = (await session.execute(sql, {"ids": list(node_ids)})).mappings().all()
        return {
            row["node_id"]: GraphNode(
                node_id=row["node_id"],
                node_type=EntityType(row["node_type"]),
                label=_truncate(row["label"]),
                slug=row["slug"],
            )
            for row in rows
        }

    # ------------------------------------------------------------ traversal

    async def neighbors(
        self,
        node_id: uuid.UUID,
        *,
        direction: Direction = Direction.DOWNSTREAM,
        relationship_types: Sequence[RelationshipType] = (),
        as_of: datetime | None = None,
    ) -> list[GraphEdge]:
        """Immediate edges. One hop, no recursion."""
        clauses = [_temporal_sql("r", as_of)]
        params: dict[str, object] = {"node_id": node_id}
        if relationship_types:
            clauses.append("r.relationship_type = ANY(:types)")
            params["types"] = [t.value for t in relationship_types]
        if direction is Direction.DOWNSTREAM:
            clauses.append("r.source_id = :node_id")
        elif direction is Direction.UPSTREAM:
            clauses.append("r.target_id = :node_id")
        else:
            clauses.append("(r.source_id = :node_id OR r.target_id = :node_id)")

        sql = text(
            f"SELECT r.source_id, r.target_id, r.relationship_type, r.weight, "
            f"r.confidence, r.rationale FROM relationships r WHERE {' AND '.join(clauses)}"
        )
        async with self.session_factory() as session:
            rows = (await session.execute(sql, params)).mappings().all()
        return [_edge(row) for row in rows]

    async def traverse(
        self, seed_ids: Sequence[uuid.UUID], spec: TraversalSpec | None = None
    ) -> list[Path]:
        """Walk the graph from ``seed_ids`` and return the routes found.

        Every prefix of a route is returned as its own Path, because "which
        Capabilities does this Process reach" and "which Assets" are the same
        traversal at different depths, and re-running it per layer would be
        three times the work for the same answer.
        """
        spec = spec or TraversalSpec()
        if not seed_ids:
            return []

        params: dict[str, object] = {
            "seeds": list(seed_ids),
            "max_hops": spec.max_hops,
            "limit": spec.limit,
        }
        type_filter = ""
        if spec.relationship_types:
            type_filter = " AND r.relationship_type = ANY(:types)"
            params["types"] = [t.value for t in spec.relationship_types]
        temporal = _temporal_sql("r", spec.as_of)
        if spec.as_of is not None:
            params["as_of"] = spec.as_of

        # Normalize direction *before* recursing. A recursive CTE permits exactly
        # one UNION between its non-recursive and recursive terms, so walking both
        # ways has to come from the edge set rather than from two extra branches.
        branches: list[str] = []
        if spec.direction is not Direction.UPSTREAM:
            branches.append(
                f"""
                SELECT r.relationship_id, r.source_id AS from_id, r.target_id AS to_id
                FROM relationships r
                WHERE {temporal}{type_filter}
                """
            )
        if spec.direction is not Direction.DOWNSTREAM:
            branches.append(
                f"""
                SELECT r.relationship_id, r.target_id AS from_id, r.source_id AS to_id
                FROM relationships r
                WHERE {temporal}{type_filter}
                """
            )

        sql = text(
            f"""
            WITH RECURSIVE edges(relationship_id, from_id, to_id) AS (
                {" UNION ALL ".join(branches)}
            ),
            walk(origin, node_id, depth, path, edges) AS (
                SELECT e.from_id, e.to_id, 1,
                       ARRAY[e.from_id, e.to_id], ARRAY[e.relationship_id]
                FROM edges e
                WHERE e.from_id = ANY(:seeds)
              UNION ALL
                SELECT w.origin, e.to_id, w.depth + 1,
                       w.path || e.to_id, w.edges || e.relationship_id
                FROM edges e
                JOIN walk w ON e.from_id = w.node_id
                WHERE w.depth < :max_hops
                  AND NOT (e.to_id = ANY(w.path))
            )
            SELECT origin, node_id, depth, path, edges
            FROM walk
            ORDER BY depth
            LIMIT :limit
            """
        )

        async with self.session_factory() as session:
            rows = (await session.execute(sql, params)).mappings().all()
        if not rows:
            return []

        edge_ids = {edge_id for row in rows for edge_id in row["edges"]}
        node_ids = {node_id for row in rows for node_id in row["path"]}
        edges = await self._edges_by_id(edge_ids, as_of=spec.as_of)
        nodes = await self.nodes(list(node_ids))

        paths: list[Path] = []
        allowed = set(spec.target_types)
        for row in rows:
            if allowed and nodes[row["node_id"]].node_type not in allowed:
                continue
            path_nodes = tuple(nodes[node_id] for node_id in row["path"] if node_id in nodes)
            path_edges = tuple(edges[edge_id] for edge_id in row["edges"] if edge_id in edges)
            if len(path_nodes) != len(path_edges) + 1:
                continue  # an edge or node was superseded mid-read; drop the route
            paths.append(Path(nodes=path_nodes, edges=path_edges))
        return paths

    async def assets_within_hops(
        self,
        process_ids: Sequence[uuid.UUID],
        *,
        max_hops: int = 4,
        as_of: datetime | None = None,
        limit: int = 500,
    ) -> list[AssetReach]:
        """Every Asset reachable from these Processes, and how.

        The query tech rec §6 uses to argue for a graph database — answered in
        Postgres, grouped so that an Asset reached from three Processes is one
        result with three paths rather than three results.
        """
        paths = await self.traverse(
            process_ids,
            TraversalSpec(
                max_hops=max_hops,
                direction=Direction.DOWNSTREAM,
                relationship_types=DISCOVERY_EDGES,
                target_types=(EntityType.ASSET,),
                as_of=as_of,
                limit=limit,
            ),
        )
        grouped: dict[uuid.UUID, list[Path]] = {}
        for path in paths:
            grouped.setdefault(path.end.node_id, []).append(path)
        return sorted(
            (AssetReach(asset=routes[0].end, paths=tuple(routes)) for routes in grouped.values()),
            key=lambda reach: (-len(reach.distinct_sources), reach.shortest_hops),
        )

    async def discovery_chain(
        self, asset_id: uuid.UUID, *, max_hops: int = 4, as_of: datetime | None = None
    ) -> list[Path]:
        """Why this Asset is in the graph, walked back to the Processes.

        The Asset page's discovery chain (issue #28). Ordered shortest-first,
        because the most direct route is the one a reader should see.
        """
        paths = await self.traverse(
            [asset_id],
            TraversalSpec(
                max_hops=max_hops,
                direction=Direction.UPSTREAM,
                relationship_types=DISCOVERY_EDGES,
                target_types=(EntityType.PROCESS,),
                as_of=as_of,
            ),
        )
        return sorted(paths, key=lambda path: (path.depth, -path.weight))

    async def confluence(
        self, node_id: uuid.UUID, *, max_hops: int = 3, as_of: datetime | None = None
    ) -> list[Path]:
        """Distinct upstream Processes reaching a Capability or Asset.

        Several independent Processes converging on one node is the signal of
        ontology §13, and it is a structural fact — which is why it is read from
        the graph rather than asked of a model.
        """
        paths = await self.traverse(
            [node_id],
            TraversalSpec(
                max_hops=max_hops,
                direction=Direction.UPSTREAM,
                relationship_types=DISCOVERY_EDGES,
                target_types=(EntityType.PROCESS,),
                as_of=as_of,
            ),
        )
        shortest: dict[uuid.UUID, Path] = {}
        for path in paths:
            current = shortest.get(path.end.node_id)
            if current is None or path.depth < current.depth:
                shortest[path.end.node_id] = path
        return sorted(shortest.values(), key=lambda path: path.depth)

    async def subgraph(
        self,
        seed_ids: Sequence[uuid.UUID],
        *,
        depth: int = 2,
        as_of: datetime | None = None,
        limit: int = 300,
    ) -> Subgraph:
        """Nodes and edges around a set of seeds, for rendering (issue #26)."""
        paths = await self.traverse(
            seed_ids,
            TraversalSpec(max_hops=depth, direction=Direction.BOTH, as_of=as_of, limit=limit),
        )
        seeds = await self.nodes(list(seed_ids))
        nodes: dict[uuid.UUID, GraphNode] = dict(seeds)
        edges: dict[tuple[uuid.UUID, uuid.UUID, str], GraphEdge] = {}
        for path in paths:
            for node in path.nodes:
                nodes[node.node_id] = node
            for edge in path.edges:
                edges[(edge.source_id, edge.target_id, edge.relationship_type.value)] = edge
        return Subgraph(nodes=tuple(nodes.values()), edges=tuple(edges.values()))

    # ------------------------------------------------------------ provenance

    async def evidence_trail(
        self, node_id: uuid.UUID, *, as_of: datetime | None = None
    ) -> EvidenceTrail:
        """Trace a node back to the documents behind it.

        Statement → Event → Claim → Document, the chain agent doc §2.4 requires
        of every material statement, assembled in one query per layer.
        """
        subject = await self.node(node_id)
        if subject is None:
            raise LookupError(f"unknown node {node_id}")

        temporal = "" if as_of is None else " AND el.created_at <= :as_of"
        params: dict[str, object] = {"node_id": node_id}
        if as_of is not None:
            params["as_of"] = as_of

        sql = text(
            f"""
            SELECT el.evidence_id, el.supports
            FROM evidence_links el
            WHERE el.subject_id = :node_id AND el.retracted_at IS NULL{temporal}
            """
        )
        async with self.session_factory() as session:
            links = (await session.execute(sql, params)).mappings().all()
            supporting = [row["evidence_id"] for row in links if row["supports"]]
            contradicting = [row["evidence_id"] for row in links if not row["supports"]]

            claims: list[uuid.UUID] = []
            documents: list[uuid.UUID] = []
            if supporting:
                rows = (
                    (
                        await session.execute(
                            text(
                                """
                            SELECT DISTINCT c.claim_id, c.document_id
                            FROM event_claims ec
                            JOIN claims c ON c.claim_id = ec.claim_id
                            WHERE ec.event_id = ANY(:events) AND ec.removed_at IS NULL
                            """
                            ),
                            {"events": supporting},
                        )
                    )
                    .mappings()
                    .all()
                )
                claims = [row["claim_id"] for row in rows]
                documents = sorted({row["document_id"] for row in rows})

        nodes = await self.nodes([*supporting, *contradicting])
        return EvidenceTrail(
            subject=subject,
            events=tuple(nodes[e] for e in supporting if e in nodes),
            claims=tuple(claims),
            documents=tuple(documents),
            contradicting_events=tuple(nodes[e] for e in contradicting if e in nodes),
        )

    # ---------------------------------------------------------------- helpers

    async def _edges_by_id(
        self, edge_ids: set[uuid.UUID], *, as_of: datetime | None
    ) -> dict[uuid.UUID, GraphEdge]:
        if not edge_ids:
            return {}
        params: dict[str, object] = {"ids": list(edge_ids)}
        if as_of is not None:
            params["as_of"] = as_of
        sql = text(
            f"""
            SELECT r.relationship_id, r.source_id, r.target_id, r.relationship_type,
                   r.weight, r.confidence, r.rationale
            FROM relationships r
            WHERE r.relationship_id = ANY(:ids) AND {_temporal_sql("r", as_of)}
            """
        )
        async with self.session_factory() as session:
            rows = (await session.execute(sql, params)).mappings().all()
        return {row["relationship_id"]: _edge(row) for row in rows}


def _temporal_sql(alias: str, as_of: datetime | None) -> str:
    """The validity-window filter, in one place.

    With no ``as_of`` this is "the current revision". With one it is "the
    revision that was current then" — which is what makes a replay describe the
    graph as it was rather than as it is (ontology §33).
    """
    if as_of is None:
        return f"{alias}.valid_to IS NULL"
    return (
        f"{alias}.valid_from <= :as_of AND ({alias}.valid_to IS NULL OR {alias}.valid_to > :as_of)"
    )


def _edge(row: object) -> GraphEdge:
    mapping = row  # a RowMapping
    return GraphEdge(
        source_id=mapping["source_id"],  # type: ignore[index]
        target_id=mapping["target_id"],  # type: ignore[index]
        relationship_type=RelationshipType(mapping["relationship_type"]),  # type: ignore[index]
        weight=float(mapping["weight"]),  # type: ignore[index]
        confidence=float(mapping["confidence"]),  # type: ignore[index]
        rationale=mapping["rationale"],  # type: ignore[index]
    )


def _truncate(label: str, limit: int = 120) -> str:
    return label if len(label) <= limit else label[: limit - 1] + "…"
