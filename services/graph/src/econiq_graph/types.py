"""Value types for graph traversal.

Deliberately plain: a traversal result should be renderable by an API, a React
Flow canvas or a test assertion without any of them importing SQLAlchemy.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from econiq_ontology import EntityType, RelationshipType


class Direction(StrEnum):
    """Which way to walk the typed edges.

    The canonical chain runs Process → Bottleneck → Capability → Asset, so
    ``DOWNSTREAM`` answers "what could express this Process" and ``UPSTREAM``
    answers "why is this Asset here" — the two questions the UI asks most.
    """

    DOWNSTREAM = "downstream"
    UPSTREAM = "upstream"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: uuid.UUID
    node_type: EntityType
    label: str
    slug: str | None = None

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.node_type.value}:{self.label}"


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source_id: uuid.UUID
    target_id: uuid.UUID
    relationship_type: RelationshipType
    weight: float = 1.0
    confidence: float = 1.0
    rationale: str | None = None


@dataclass(frozen=True, slots=True)
class Path:
    """One route through the graph, seed first.

    ``edges`` and ``nodes`` line up: ``nodes[i]`` is the source of ``edges[i]``
    and ``nodes[i + 1]`` its target, so a UI can render the chain and its
    reasons together without re-joining anything.
    """

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @property
    def depth(self) -> int:
        return len(self.edges)

    @property
    def start(self) -> GraphNode:
        return self.nodes[0]

    @property
    def end(self) -> GraphNode:
        return self.nodes[-1]

    @property
    def weight(self) -> float:
        """Product of edge weights — a path through weak links is a weak path."""
        total = 1.0
        for edge in self.edges:
            total *= edge.weight
        return total

    def describe(self) -> str:
        parts = [str(self.nodes[0])]
        for edge, node in zip(self.edges, self.nodes[1:], strict=True):
            parts.append(f" --{edge.relationship_type.value}--> {node}")
        return "".join(parts)


@dataclass(frozen=True, slots=True)
class Subgraph:
    """Nodes and edges for rendering (issue #26)."""

    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    @property
    def node_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(node.node_id for node in self.nodes)


@dataclass(frozen=True, slots=True)
class AssetReach:
    """An Asset reachable from a set of Processes, and how it was reached.

    The multi-hop question tech rec §6 names as the reason a graph database
    might eventually be worth it — answered here in Postgres.
    """

    asset: GraphNode
    paths: tuple[Path, ...]

    @property
    def shortest_hops(self) -> int:
        return min(path.depth for path in self.paths)

    @property
    def distinct_sources(self) -> frozenset[uuid.UUID]:
        """Seeds that reach this Asset — several is a confluence signal."""
        return frozenset(path.start.node_id for path in self.paths)

    @property
    def best_weight(self) -> float:
        return max(path.weight for path in self.paths)


@dataclass(frozen=True, slots=True)
class EvidenceTrail:
    """A statement traced back to the documents behind it (agent doc §2.4)."""

    subject: GraphNode
    events: tuple[GraphNode, ...] = ()
    claims: tuple[uuid.UUID, ...] = ()
    documents: tuple[uuid.UUID, ...] = ()
    contradicting_events: tuple[GraphNode, ...] = ()

    @property
    def is_evidenced(self) -> bool:
        return bool(self.documents)


@dataclass(frozen=True, slots=True)
class IntegrityViolation:
    """A structural defect in the graph."""

    kind: str
    node_id: uuid.UUID | None
    detail: str

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.kind}: {self.detail}"


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    violations: tuple[IntegrityViolation, ...] = ()
    checked_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return not self.violations

    def of_kind(self, kind: str) -> tuple[IntegrityViolation, ...]:
        return tuple(v for v in self.violations if v.kind == kind)


@dataclass(frozen=True, slots=True)
class TraversalSpec:
    """What a traversal is allowed to walk."""

    max_hops: int = 4
    direction: Direction = Direction.DOWNSTREAM
    relationship_types: Sequence[RelationshipType] = field(default_factory=tuple)
    target_types: Sequence[EntityType] = field(default_factory=tuple)
    as_of: datetime | None = None
    limit: int = 500

    def __post_init__(self) -> None:
        if self.max_hops < 1:
            raise ValueError("max_hops must be at least 1")
        if self.limit < 1:
            raise ValueError("limit must be at least 1")


#: The canonical chain of ui_concept §9.1. Restricting a traversal to these
#: keeps it on the discovery path rather than wandering through evidence and
#: supersession edges, which are a different question.
DISCOVERY_EDGES: tuple[RelationshipType, ...] = (
    RelationshipType.INFLUENCES,
    RelationshipType.CREATES,
    RelationshipType.REQUIRES,
    RelationshipType.EXPRESSED_BY,
)
