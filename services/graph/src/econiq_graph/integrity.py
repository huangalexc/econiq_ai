"""Graph integrity checks (issue #13, tech rec §31).

Postgres guarantees an edge points at nodes that exist. It cannot express the
three things that actually go wrong in an ontology graph:

* an edge type the ontology does not permit — a Bottleneck reaching an Asset
  directly, skipping the Capability layer that makes the chain inspectable;
* circular causality — Process A influences B influences A, which is not
  obviously wrong to a model writing one edge at a time but makes traversal,
  scoring and explanation incoherent;
* orphaned nodes — an entity in the registry with no row, or a Capability
  nothing requires, which is either a bug or a leak.

These run as a suite rather than a constraint because some are expensive and
none should block a write mid-pipeline. The evaluation harness (issue #16) and
the Research Quality Auditor (issue #57) are their consumers.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from econiq_ontology import EntityType, RelationshipType, edge_is_legal, utcnow
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_graph.types import IntegrityReport, IntegrityViolation


class GraphIntegrity:
    """Structural checks over the whole graph."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def check(self, *, as_of: datetime | None = None) -> IntegrityReport:
        violations: list[IntegrityViolation] = []
        violations.extend(await self.illegal_edges())
        violations.extend(await self.causal_cycles())
        violations.extend(await self.orphaned_nodes())
        violations.extend(await self.multiple_current_revisions())
        return IntegrityReport(violations=tuple(violations), checked_at=as_of or utcnow())

    async def illegal_edges(self) -> list[IntegrityViolation]:
        """Edges the ontology does not permit.

        ``GraphWriter`` refuses these on the way in. This catches anything that
        arrived another way — a migration, a fixture, a direct insert — because
        one illegal edge quietly changes what every traversal means.
        """
        sql = text(
            """
            SELECT r.relationship_id, r.relationship_type,
                   s.node_type AS source_type, t.node_type AS target_type
            FROM relationships r
            JOIN nodes s ON s.node_id = r.source_id
            JOIN nodes t ON t.node_id = r.target_id
            WHERE r.valid_to IS NULL
            """
        )
        async with self.session_factory() as session:
            rows = (await session.execute(sql)).mappings().all()

        violations: list[IntegrityViolation] = []
        for row in rows:
            source = EntityType(row["source_type"])
            target = EntityType(row["target_type"])
            relationship = RelationshipType(row["relationship_type"])
            if not edge_is_legal(source, relationship, target):
                violations.append(
                    IntegrityViolation(
                        kind="illegal_edge",
                        node_id=row["relationship_id"],
                        detail=(
                            f"{source.value} --{relationship.value}--> {target.value} "
                            "is not in ALLOWED_EDGES"
                        ),
                    )
                )
        return violations

    async def causal_cycles(self, *, max_depth: int = 8) -> list[IntegrityViolation]:
        """Processes that influence themselves through a chain.

        Only ``influences`` edges are walked: that is the causal relation, and a
        cycle in it means the graph asserts A causes B causes A. The other edge
        types run down the layers and cannot loop.
        """
        sql = text(
            """
            WITH RECURSIVE walk(start_id, node_id, depth, path) AS (
                SELECT r.source_id, r.target_id, 1, ARRAY[r.source_id, r.target_id]
                FROM relationships r
                WHERE r.relationship_type = 'influences' AND r.valid_to IS NULL
              UNION ALL
                SELECT w.start_id, r.target_id, w.depth + 1, w.path || r.target_id
                FROM relationships r
                JOIN walk w ON r.source_id = w.node_id
                WHERE r.relationship_type = 'influences'
                  AND r.valid_to IS NULL
                  AND w.depth < :max_depth
                  AND NOT (r.target_id = ANY(w.path[2:]))
            )
            SELECT DISTINCT start_id, depth, path
            FROM walk
            WHERE node_id = start_id
            """
        )
        async with self.session_factory() as session:
            rows = (await session.execute(sql, {"max_depth": max_depth})).mappings().all()
        return [
            IntegrityViolation(
                kind="causal_cycle",
                node_id=row["start_id"],
                detail=(
                    f"influences cycle of length {row['depth']} through {len(row['path'])} nodes"
                ),
            )
            for row in rows
        ]

    async def orphaned_nodes(self) -> list[IntegrityViolation]:
        """Registry rows with no entity, and entities nothing connects to.

        A node with no backing row is a half-finished write. A Capability that
        nothing requires, or an Asset nothing expresses, is a leak: it was
        created for a reason that no longer exists in the graph.
        """
        violations: list[IntegrityViolation] = []
        async with self.session_factory() as session:
            missing = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT n.node_id, n.node_type
                        FROM nodes n
                        LEFT JOIN processes p ON p.process_id = n.node_id
                        LEFT JOIN bottlenecks b ON b.bottleneck_id = n.node_id
                        LEFT JOIN capabilities c ON c.capability_id = n.node_id
                        LEFT JOIN assets a ON a.asset_id = n.node_id
                        LEFT JOIN events e ON e.event_id = n.node_id
                        LEFT JOIN documents d ON d.document_id = n.node_id
                        LEFT JOIN claims cl ON cl.claim_id = n.node_id
                        WHERE p.process_id IS NULL AND b.bottleneck_id IS NULL
                          AND c.capability_id IS NULL AND a.asset_id IS NULL
                          AND e.event_id IS NULL AND d.document_id IS NULL
                          AND cl.claim_id IS NULL
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )
            violations.extend(
                IntegrityViolation(
                    kind="node_without_entity",
                    node_id=row["node_id"],
                    detail=f"{row['node_type']} registered with no entity row",
                )
                for row in missing
            )

            disconnected = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT n.node_id, n.node_type
                        FROM nodes n
                        WHERE n.node_type IN ('capability', 'asset', 'bottleneck')
                          AND NOT EXISTS (
                              SELECT 1 FROM relationships r
                              WHERE r.valid_to IS NULL
                                AND (r.source_id = n.node_id OR r.target_id = n.node_id)
                          )
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )
            violations.extend(
                IntegrityViolation(
                    kind="disconnected_node",
                    node_id=row["node_id"],
                    detail=f"{row['node_type']} has no current edges",
                )
                for row in disconnected
            )
        return violations

    async def multiple_current_revisions(self) -> list[IntegrityViolation]:
        """More than one current revision of a revisable entity.

        The partial unique indexes make this impossible in Postgres. Checking
        anyway is cheap, and if it ever fires it means an index was dropped —
        at which point every "what does the system currently believe" query has
        been silently wrong.
        """
        violations: list[IntegrityViolation] = []
        tables = {
            "processes": "process_id",
            "events": "event_id",
            "bottlenecks": "bottleneck_id",
            "capabilities": "capability_id",
            "assets": "asset_id",
            "relationships": "relationship_id",
            "capability_requirements": "requirement_id",
        }
        async with self.session_factory() as session:
            for table, id_column in tables.items():
                rows = (
                    (
                        await session.execute(
                            text(
                                f"""
                            SELECT {id_column} AS entity_id, COUNT(*) AS current_count
                            FROM {table}
                            WHERE valid_to IS NULL
                            GROUP BY {id_column}
                            HAVING COUNT(*) > 1
                            """
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                violations.extend(
                    IntegrityViolation(
                        kind="multiple_current_revisions",
                        node_id=row["entity_id"],
                        detail=f"{table} has {row['current_count']} current revisions",
                    )
                    for row in rows
                )
        return violations

    async def would_create_cycle(self, source_id: uuid.UUID, target_id: uuid.UUID) -> bool:
        """Whether adding ``source --influences--> target`` closes a loop.

        Offered so a writer can refuse the edge rather than discovering the
        cycle in an audit weeks later.
        """
        if source_id == target_id:
            return True
        sql = text(
            """
            WITH RECURSIVE walk(node_id, depth, path) AS (
                SELECT r.target_id, 1, ARRAY[r.source_id, r.target_id]
                FROM relationships r
                WHERE r.source_id = :target_id
                  AND r.relationship_type = 'influences'
                  AND r.valid_to IS NULL
              UNION ALL
                SELECT r.target_id, w.depth + 1, w.path || r.target_id
                FROM relationships r
                JOIN walk w ON r.source_id = w.node_id
                WHERE r.relationship_type = 'influences'
                  AND r.valid_to IS NULL
                  AND w.depth < 12
                  AND NOT (r.target_id = ANY(w.path))
            )
            SELECT 1 FROM walk WHERE node_id = :source_id LIMIT 1
            """
        )
        async with self.session_factory() as session:
            found = (
                await session.execute(sql, {"source_id": source_id, "target_id": target_id})
            ).first()
        return found is not None


async def assert_healthy(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    ignore: Sequence[str] = ("disconnected_node",),
) -> IntegrityReport:
    """Raise if the graph has structural defects.

    ``disconnected_node`` is ignored by default: mid-pipeline a Capability
    legitimately exists for a moment before anything requires it, and failing on
    that would make the check useless during ingestion.
    """
    report = await GraphIntegrity(session_factory).check()
    blocking = tuple(v for v in report.violations if v.kind not in ignore)
    if blocking:
        raise AssertionError(
            "graph integrity violations:\n" + "\n".join(f"  {v}" for v in blocking)
        )
    return report
