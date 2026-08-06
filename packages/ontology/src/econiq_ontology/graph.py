"""Typed relationships between ontology nodes (ui_concept §9.1, ontology §9).

Edges are typed and the legal (source, type, target) triples are enumerated
here. This is not bureaucracy: an untyped edge from a Bottleneck to an Asset
would silently skip the Capability layer, which is exactly the shortcut the
system exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Self

from pydantic import Field, model_validator

from econiq_ontology.base import Confidence, Entity, Weight
from econiq_ontology.enums import CausalRole, EntityType, RelationshipType
from econiq_ontology.provenance import AgentAttribution, EntityRef, EvidenceRef

E = EntityType
R = RelationshipType

#: Legal ``(source_type, target_type)`` pairs per relationship type.
#:
#: The canonical chain of ui_concept §9.1 is the backbone; ``AFFECTS`` carries
#: the direct Event → Asset relationships of ontology §15, which coexist with
#: Process-mediated exposure rather than replacing it.
ALLOWED_EDGES: Mapping[RelationshipType, frozenset[tuple[EntityType, EntityType]]] = (
    MappingProxyType(
        {
            R.INFLUENCES: frozenset({(E.PROCESS, E.PROCESS)}),
            R.CREATES: frozenset({(E.PROCESS, E.BOTTLENECK)}),
            R.REQUIRES: frozenset({(E.BOTTLENECK, E.CAPABILITY), (E.PROCESS, E.CAPABILITY)}),
            R.EXPRESSED_BY: frozenset({(E.CAPABILITY, E.ASSET)}),
            R.AFFECTS: frozenset(
                {
                    (E.EVENT, E.PROCESS),
                    (E.EVENT, E.ASSET),
                    (E.EVENT, E.BOTTLENECK),
                    (E.EVENT, E.CAPABILITY),
                }
            ),
            R.SUPPORTS: frozenset(
                {
                    (E.CLAIM, E.EVENT),
                    (E.EVENT, E.PROCESS),
                    (E.EVENT, E.BOTTLENECK),
                    (E.CLAIM, E.PROCESS),
                }
            ),
            R.CONTRADICTS: frozenset(
                {
                    (E.CLAIM, E.EVENT),
                    (E.EVENT, E.PROCESS),
                    (E.EVENT, E.EVENT),
                    (E.CLAIM, E.PROCESS),
                }
            ),
            R.SUPERSEDES: frozenset(
                {
                    (E.EVENT, E.EVENT),
                    (E.PROCESS, E.PROCESS),
                    (E.BOTTLENECK, E.BOTTLENECK),
                    (E.CAPABILITY, E.CAPABILITY),
                }
            ),
            R.DERIVED_FROM: frozenset(
                {(E.CLAIM, E.DOCUMENT), (E.EVENT, E.CLAIM), (E.PROCESS, E.EVENT)}
            ),
        }
    )
)


def edge_is_legal(source: EntityType, relationship: RelationshipType, target: EntityType) -> bool:
    return (source, target) in ALLOWED_EDGES.get(relationship, frozenset())


class Relationship(Entity):
    """A typed, evidenced edge in the economic graph.

    ``causal_role`` records whether the source acts as a Driver or a Mechanism
    *in this relationship* (ontology §9). It is a property of the edge, not of
    the node: the same Process is a Mechanism downstream of one Process and a
    Driver of the next, and duplicating nodes to express that would fragment the
    evidence.
    """

    source: EntityRef
    target: EntityRef
    relationship_type: RelationshipType
    causal_role: CausalRole | None = None
    weight: Weight = 1.0
    confidence: Confidence
    rationale: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    attribution: AgentAttribution | None = None

    @model_validator(mode="after")
    def _edge_is_legal(self) -> Self:
        if not edge_is_legal(
            self.source.entity_type, self.relationship_type, self.target.entity_type
        ):
            raise ValueError(
                f"illegal edge: {self.source.entity_type.value} "
                f"--{self.relationship_type.value}--> {self.target.entity_type.value}"
            )
        if self.source == self.target:
            raise ValueError("a node may not relate to itself")
        if self.causal_role is not None and self.relationship_type is not R.INFLUENCES:
            raise ValueError("causal_role applies only to 'influences' relationships")
        return self
