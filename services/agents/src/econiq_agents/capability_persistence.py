"""Persisting Bottlenecks, Capabilities and requirement trees.

Two things here are worth reading closely.

**Capabilities are shared nodes.** A proposed Capability is resolved against
what already exists — by slug first, then by vector similarity — and only
created when nothing matches. That resolution is what makes confluence real: if
"heavy rare-earth separation" is created afresh for every Process that needs it,
several Processes converging on one Capability is invisible, and ontology §13's
signal is destroyed by a naming accident.

**The requirement tree is stored as a tree.** ``requirement_nodes`` rows
reconstruct into the same ``CapabilityRequirement`` the ontology defines, so
``is_satisfied_by`` and ``coverage`` answer the same way against the database as
against the model. AND and OR imply different Asset universes; flattening them
for storage convenience would quietly discard the distinction the mapping agent
was asked to express.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from econiq_data_models import (
    Bottleneck,
    Capability,
    CapabilityRequirement,
    EmbeddingKind,
    Node,
    RequirementNode,
    RequirementNodeKind,
)
from econiq_ontology import (
    CapabilityLeaf,
    EntityType,
    LogicOperator,
    Necessity,
    RequirementGroup,
    utcnow,
)
from econiq_ontology import CapabilityRequirement as RequirementModel
from econiq_ontology.process_layer import RequirementNode as RequirementNodeModel
from econiq_schemas import (
    CapabilityMappingOutput,
    ProposedBottleneck,
    ProposedLeaf,
    ProposedRequirement,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.embeddings import EmbeddingStore

_NON_SLUG = re.compile(r"[^a-z0-9]+")

#: Cosine distance below which a proposed Capability is treated as one that
#: already exists. Deliberately tight: merging two distinct Capabilities is
#: worse than holding a near-duplicate, because the requirement trees of two
#: Bottlenecks then point at the same node and the Asset universes merge with
#: them.
CAPABILITY_MATCH_DISTANCE = 0.15


def slugify(value: str) -> str:
    slug = _NON_SLUG.sub("-", value.strip().lower()).strip("-")
    return slug or "unnamed"


@dataclass(frozen=True, slots=True)
class PersistedBottleneck:
    bottleneck_id: uuid.UUID
    revision: int
    created: bool
    currently_binding: bool


@dataclass(frozen=True, slots=True)
class ResolvedCapability:
    capability_id: uuid.UUID
    slug: str
    created: bool
    matched_by: str = "created"
    """``slug``, ``embedding`` or ``created`` — how the node was resolved."""


@dataclass(frozen=True, slots=True)
class PersistedRequirement:
    requirement_id: uuid.UUID
    revision: int
    capabilities: list[ResolvedCapability] = field(default_factory=list)
    reused: int = 0
    """Capabilities that already existed — the raw material of confluence."""


class BottleneckWriter:
    """Creates and revises Bottlenecks."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def persist(
        self,
        process_id: uuid.UUID,
        proposed: ProposedBottleneck,
        *,
        agent_run_id: uuid.UUID,
    ) -> PersistedBottleneck:
        """Write a Bottleneck, revising the existing one if it is the same
        constraint under the same name."""
        async with self.session_factory() as session:
            existing = await self._by_name(session, process_id, proposed.name)

            if existing is None:
                bottleneck_id = uuid.uuid4()
                session.add(Node(node_id=bottleneck_id, node_type=EntityType.BOTTLENECK))
                await session.flush()
                session.add(self._row(bottleneck_id, 1, process_id, proposed, agent_run_id))
                await session.commit()
                return PersistedBottleneck(
                    bottleneck_id=bottleneck_id,
                    revision=1,
                    created=True,
                    currently_binding=proposed.currently_binding,
                )

            closed_at = utcnow()
            await session.execute(
                update(Bottleneck)
                .where(
                    Bottleneck.bottleneck_id == existing.bottleneck_id,
                    Bottleneck.valid_to.is_(None),
                )
                .values(valid_to=closed_at)
            )
            revision = existing.revision + 1
            row = self._row(existing.bottleneck_id, revision, process_id, proposed, agent_run_id)
            row.valid_from = closed_at
            session.add(row)
            await session.commit()
            return PersistedBottleneck(
                bottleneck_id=existing.bottleneck_id,
                revision=revision,
                created=False,
                currently_binding=proposed.currently_binding,
            )

    @staticmethod
    def _row(
        bottleneck_id: uuid.UUID,
        revision: int,
        process_id: uuid.UUID,
        proposed: ProposedBottleneck,
        agent_run_id: uuid.UUID,
    ) -> Bottleneck:
        return Bottleneck(
            bottleneck_id=bottleneck_id,
            revision=revision,
            process_id=process_id,
            name=proposed.name,
            description=proposed.description,
            kind=proposed.kind,
            currently_binding=proposed.currently_binding,
            demand_pressure=proposed.demand_pressure,
            supply_elasticity=proposed.supply_elasticity,
            time_to_expand=proposed.time_to_expand,
            current_constraint=proposed.current_constraint,
            relief_indicators=list(proposed.relief_indicators),
            confidence=proposed.confidence,
            resolved=False,
            agent_run_id=agent_run_id,
        )

    async def _by_name(
        self, session: AsyncSession, process_id: uuid.UUID, name: str
    ) -> Bottleneck | None:
        result = await session.execute(
            select(Bottleneck).where(
                Bottleneck.process_id == process_id,
                Bottleneck.name == name,
                Bottleneck.valid_to.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def open_for_process(self, process_id: uuid.UUID) -> list[Bottleneck]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Bottleneck).where(
                    Bottleneck.process_id == process_id,
                    Bottleneck.valid_to.is_(None),
                    Bottleneck.resolved.is_(False),
                )
            )
            return list(result.scalars().all())


class CapabilityWriter:
    """Resolves proposed Capabilities to shared nodes and stores requirement trees."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embeddings: EmbeddingStore,
    ) -> None:
        self.session_factory = session_factory
        self.embeddings = embeddings

    async def resolve(
        self, name: str, description: str, *, agent_run_id: uuid.UUID
    ) -> ResolvedCapability:
        """Find the Capability this proposal means, or create it.

        Slug first because an exact name match is unambiguous; vector similarity
        second because "heavy rare-earth separation" and "heavy rare earth
        separation capacity" are the same ability described twice.
        """
        slug = slugify(name)
        async with self.session_factory() as session:
            by_slug = await self._by_slug(session, slug)
        if by_slug is not None:
            return ResolvedCapability(
                capability_id=by_slug.capability_id,
                slug=by_slug.slug,
                created=False,
                matched_by="slug",
            )

        vector = self.embeddings.embedder.embed([f"{name}\n{description}"])[0]
        nearest = await self.embeddings.nearest(
            vector,
            EmbeddingKind.CAPABILITY_DESCRIPTION,
            limit=1,
            max_distance=CAPABILITY_MATCH_DISTANCE,
        )
        if nearest:
            capability_id = nearest[0][0]
            async with self.session_factory() as session:
                existing = await self._by_id(session, capability_id)
            if existing is not None:
                return ResolvedCapability(
                    capability_id=capability_id,
                    slug=existing.slug,
                    created=False,
                    matched_by="embedding",
                )

        capability_id = uuid.uuid4()
        async with self.session_factory() as session:
            unique_slug = await self._unique_slug(session, slug)
            session.add(
                Node(
                    node_id=capability_id,
                    node_type=EntityType.CAPABILITY,
                    slug=unique_slug,
                )
            )
            await session.flush()
            session.add(
                Capability(
                    capability_id=capability_id,
                    revision=1,
                    name=name,
                    slug=unique_slug,
                    description=description,
                    aliases=[],
                    agent_run_id=agent_run_id,
                )
            )
            await session.commit()
        await self.embeddings.upsert(
            capability_id, EmbeddingKind.CAPABILITY_DESCRIPTION, f"{name}\n{description}"
        )
        return ResolvedCapability(
            capability_id=capability_id, slug=unique_slug, created=True, matched_by="created"
        )

    async def store_requirement(
        self,
        output: CapabilityMappingOutput,
        *,
        bottleneck_id: uuid.UUID,
        process_id: uuid.UUID,
        agent_run_id: uuid.UUID,
    ) -> PersistedRequirement:
        """Resolve every proposed Capability, then materialize the tree."""
        if output.requirement_tree is None:
            raise ValueError("cannot store a requirement without a tree")

        resolved: dict[str, ResolvedCapability] = {}
        for proposal in output.capabilities:
            resolved[proposal.ref] = await self.resolve(
                proposal.name, proposal.description, agent_run_id=agent_run_id
            )

        async with self.session_factory() as session:
            existing = await self._current_requirement(session, bottleneck_id)
            requirement_id = existing.requirement_id if existing else uuid.uuid4()
            revision = existing.revision + 1 if existing else 1
            closed_at = utcnow()
            if existing is not None:
                await session.execute(
                    update(CapabilityRequirement)
                    .where(
                        CapabilityRequirement.requirement_id == requirement_id,
                        CapabilityRequirement.valid_to.is_(None),
                    )
                    .values(valid_to=closed_at)
                )

            root_id = uuid.uuid4()
            requirement = CapabilityRequirement(
                requirement_id=requirement_id,
                revision=revision,
                bottleneck_id=bottleneck_id,
                process_id=process_id,
                root_node_id=root_id,
                agent_run_id=agent_run_id,
            )
            if existing is not None:
                requirement.valid_from = closed_at
            session.add(requirement)
            await session.flush()

            self._write_node(
                session,
                output.requirement_tree,
                node_id=root_id,
                parent_id=None,
                position=0,
                requirement_id=requirement_id,
                revision=revision,
                resolved=resolved,
            )
            await session.commit()

        return PersistedRequirement(
            requirement_id=requirement_id,
            revision=revision,
            capabilities=list(resolved.values()),
            reused=sum(1 for capability in resolved.values() if not capability.created),
        )

    def _write_node(
        self,
        session: AsyncSession,
        node: ProposedRequirement,
        *,
        node_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        position: int,
        requirement_id: uuid.UUID,
        revision: int,
        resolved: dict[str, ResolvedCapability],
    ) -> None:
        if isinstance(node, ProposedLeaf):
            session.add(
                RequirementNode(
                    requirement_node_id=node_id,
                    requirement_id=requirement_id,
                    requirement_revision=revision,
                    parent_id=parent_id,
                    position=position,
                    kind=RequirementNodeKind.CAPABILITY,
                    capability_id=resolved[node.ref].capability_id,
                    necessity=node.necessity,
                    weight=node.weight,
                )
            )
            return

        session.add(
            RequirementNode(
                requirement_node_id=node_id,
                requirement_id=requirement_id,
                requirement_revision=revision,
                parent_id=parent_id,
                position=position,
                kind=RequirementNodeKind.GROUP,
                operator=node.operator,
                label=node.label,
                necessity=node.necessity,
                weight=node.weight,
            )
        )
        for index, child in enumerate(node.children):
            self._write_node(
                session,
                child,
                node_id=uuid.uuid4(),
                parent_id=node_id,
                position=index,
                requirement_id=requirement_id,
                revision=revision,
                resolved=resolved,
            )

    async def load_requirement(self, bottleneck_id: uuid.UUID) -> RequirementModel | None:
        """Rebuild the stored tree as the ontology object.

        The point of the round trip: ``is_satisfied_by`` and ``coverage`` must
        answer identically whether the tree came from an agent or from Postgres.
        """
        async with self.session_factory() as session:
            requirement = await self._current_requirement(session, bottleneck_id)
            if requirement is None:
                return None
            rows = (
                (
                    await session.execute(
                        select(RequirementNode)
                        .where(
                            RequirementNode.requirement_id == requirement.requirement_id,
                            RequirementNode.requirement_revision == requirement.revision,
                        )
                        .order_by(RequirementNode.position)
                    )
                )
                .scalars()
                .all()
            )

        by_parent: dict[uuid.UUID | None, list[RequirementNode]] = {}
        by_id = {row.requirement_node_id: row for row in rows}
        for row in rows:
            by_parent.setdefault(row.parent_id, []).append(row)

        root = by_id.get(requirement.root_node_id)
        if root is None:
            return None
        return RequirementModel(
            id=requirement.requirement_id,
            revision=requirement.revision,
            bottleneck_id=requirement.bottleneck_id,
            process_id=requirement.process_id,
            root=_rebuild(root, by_parent),
        )

    async def capabilities_for(self, bottleneck_id: uuid.UUID) -> list[uuid.UUID]:
        requirement = await self.load_requirement(bottleneck_id)
        return [] if requirement is None else sorted(requirement.capability_ids())

    async def _current_requirement(
        self, session: AsyncSession, bottleneck_id: uuid.UUID
    ) -> CapabilityRequirement | None:
        result = await session.execute(
            select(CapabilityRequirement).where(
                CapabilityRequirement.bottleneck_id == bottleneck_id,
                CapabilityRequirement.valid_to.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _by_slug(self, session: AsyncSession, slug: str) -> Capability | None:
        result = await session.execute(
            select(Capability).where(Capability.slug == slug, Capability.valid_to.is_(None))
        )
        return result.scalar_one_or_none()

    async def _by_id(self, session: AsyncSession, capability_id: uuid.UUID) -> Capability | None:
        result = await session.execute(
            select(Capability).where(
                Capability.capability_id == capability_id, Capability.valid_to.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def _unique_slug(self, session: AsyncSession, slug: str) -> str:
        taken = set(
            (
                await session.execute(
                    select(Node.slug).where(
                        Node.node_type == EntityType.CAPABILITY, Node.slug.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        if slug not in taken:
            return slug
        suffix = 2
        while f"{slug}-{suffix}" in taken:
            suffix += 1
        return f"{slug}-{suffix}"

    async def known_names(self, limit: int = 60) -> list[str]:
        """Existing Capability names, to put in front of the mapping agent.

        Reuse is how confluence becomes visible, and a model cannot reuse a name
        it was never shown.
        """
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Capability.name)
                    .where(Capability.valid_to.is_(None))
                    .order_by(Capability.created_at.desc())
                    .limit(limit)
                )
            ).scalars()
            return list(rows)


def _rebuild(
    row: RequirementNode, by_parent: dict[uuid.UUID | None, list[RequirementNode]]
) -> RequirementNodeModel:
    if row.kind is RequirementNodeKind.CAPABILITY:
        assert row.capability_id is not None
        return CapabilityLeaf(
            capability_id=row.capability_id,
            necessity=Necessity(row.necessity),
            weight=row.weight,
            rationale=row.rationale,
        )
    children = sorted(by_parent.get(row.requirement_node_id, []), key=lambda child: child.position)
    return RequirementGroup(
        operator=LogicOperator(row.operator) if row.operator else LogicOperator.AND,
        children=[_rebuild(child, by_parent) for child in children],
        necessity=Necessity(row.necessity),
        weight=row.weight,
        label=row.label,
    )


def requirement_summary(requirement: RequirementModel) -> str:
    """A one-line rendering of the logic, for journals and logs."""

    def render(node: RequirementNodeModel) -> str:
        if isinstance(node, CapabilityLeaf):
            text = str(node.capability_id)[:8]
            return f"[{text}]" if node.necessity is Necessity.REQUIRED else f"({text})?"
        joiner = " AND " if node.operator is LogicOperator.AND else " OR "
        return "(" + joiner.join(render(child) for child in node.children) + ")"

    return render(requirement.root)


def as_of_now() -> datetime:
    return utcnow()
