"""Writing typed edges and evidence links.

This is where ``ALLOWED_EDGES`` stops being documentation. Postgres guarantees
an edge points at nodes that exist; it cannot express "a Bottleneck may not
reach an Asset directly". So every relationship goes through here, the triple is
checked against the ontology, and an illegal edge raises instead of landing.

Edges are revisable entities, so re-asserting one with new evidence writes a
revision rather than duplicating the edge.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from econiq_data_models import EvidenceLink, Node, Relationship
from econiq_ontology import CausalRole, EntityType, RelationshipType, edge_is_legal
from econiq_ontology.base import utcnow
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class IllegalEdgeError(ValueError):
    """An edge the ontology does not permit.

    Raised rather than logged: an illegal edge means an agent reasoned past its
    layer, and writing it would corrupt every traversal that follows.
    """


@dataclass(frozen=True, slots=True)
class WrittenEdge:
    relationship_id: uuid.UUID
    revision: int
    created: bool


class GraphWriter:
    """The only sanctioned way to add edges and evidence to the graph."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def relate(
        self,
        *,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relationship_type: RelationshipType,
        confidence: float,
        agent_run_id: uuid.UUID,
        weight: float = 1.0,
        causal_role: CausalRole | None = None,
        rationale: str | None = None,
    ) -> WrittenEdge:
        async with self.session_factory() as session:
            source_type = await self._node_type(session, source_id)
            target_type = await self._node_type(session, target_id)

        if not edge_is_legal(source_type, relationship_type, target_type):
            raise IllegalEdgeError(
                f"{source_type.value} --{relationship_type.value}--> {target_type.value} "
                "is not a legal edge; see econiq_ontology.graph.ALLOWED_EDGES"
            )
        if source_id == target_id:
            raise IllegalEdgeError("a node may not relate to itself")

        async with self.session_factory() as session:
            existing = await self._current_edge(session, source_id, target_id, relationship_type)
            if existing is None:
                relationship_id = uuid.uuid4()
                session.add(
                    Relationship(
                        relationship_id=relationship_id,
                        revision=1,
                        source_id=source_id,
                        target_id=target_id,
                        relationship_type=relationship_type,
                        causal_role=causal_role,
                        weight=weight,
                        confidence=confidence,
                        rationale=rationale,
                        agent_run_id=agent_run_id,
                    )
                )
                await session.commit()
                return WrittenEdge(relationship_id, 1, created=True)

            closed_at = utcnow()
            await session.execute(
                update(Relationship)
                .where(
                    Relationship.relationship_id == existing.relationship_id,
                    Relationship.valid_to.is_(None),
                )
                .values(valid_to=closed_at)
            )
            revision = existing.revision + 1
            row = Relationship(
                relationship_id=existing.relationship_id,
                revision=revision,
                source_id=source_id,
                target_id=target_id,
                relationship_type=relationship_type,
                causal_role=causal_role,
                weight=weight,
                confidence=confidence,
                rationale=rationale,
                agent_run_id=agent_run_id,
            )
            row.valid_from = closed_at
            session.add(row)
            await session.commit()
            return WrittenEdge(existing.relationship_id, revision, created=False)

    async def add_evidence(
        self,
        *,
        subject_id: uuid.UUID,
        evidence_id: uuid.UUID,
        supports: bool,
        agent_run_id: uuid.UUID,
        weight: float = 1.0,
        note: str | None = None,
    ) -> uuid.UUID:
        """Record evidence for or against a statement about a node.

        Contradicting evidence is stored the same way as supporting evidence.
        Contradiction is a scored dimension of Thesis Quality (ontology §17), so
        it has to accumulate rather than be filtered out at write time.
        """
        link_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                EvidenceLink(
                    evidence_link_id=link_id,
                    subject_id=subject_id,
                    evidence_id=evidence_id,
                    supports=supports,
                    weight=weight,
                    note=note,
                    agent_run_id=agent_run_id,
                )
            )
            await session.commit()
        return link_id

    async def _node_type(self, session: AsyncSession, node_id: uuid.UUID) -> EntityType:
        node = await session.get(Node, node_id)
        if node is None:
            raise IllegalEdgeError(f"node {node_id} does not exist")
        return node.node_type

    async def _current_edge(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relationship_type: RelationshipType,
    ) -> Relationship | None:
        result = await session.execute(
            select(Relationship).where(
                Relationship.source_id == source_id,
                Relationship.target_id == target_id,
                Relationship.relationship_type == relationship_type,
                Relationship.valid_to.is_(None),
            )
        )
        return result.scalar_one_or_none()
