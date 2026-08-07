"""Traversal and integrity over the ontology graph (issue #13).

Postgres is the graph. Tech rec §6 is explicit that Neo4j is a projection when
it arrives, not the source of truth — and the multi-hop query it names as the
motivating case is a recursive CTE, which Postgres has had for years. See
``docs/graph-projection.md`` for when that changes.
"""

from econiq_graph.integrity import GraphIntegrity, assert_healthy
from econiq_graph.queries import GraphQueries
from econiq_graph.types import (
    DISCOVERY_EDGES,
    AssetReach,
    Direction,
    EvidenceTrail,
    GraphEdge,
    GraphNode,
    IntegrityReport,
    IntegrityViolation,
    Path,
    Subgraph,
    TraversalSpec,
)

__all__ = [
    "DISCOVERY_EDGES",
    "AssetReach",
    "Direction",
    "EvidenceTrail",
    "GraphEdge",
    "GraphIntegrity",
    "GraphNode",
    "GraphQueries",
    "IntegrityReport",
    "IntegrityViolation",
    "Path",
    "Subgraph",
    "TraversalSpec",
    "assert_healthy",
]
