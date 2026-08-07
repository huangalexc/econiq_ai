"""Structural checks Postgres cannot express."""

from __future__ import annotations

import uuid

import pytest
from econiq_data_models import Bottleneck, Capability, Node, Process, Relationship
from econiq_graph import GraphIntegrity, assert_healthy
from econiq_ontology import (
    BottleneckKind,
    EntityType,
    ProcessArchetype,
    ProcessStatus,
    RelationshipType,
)

pytestmark = pytest.mark.integration


async def _process(session_factory, slug: str) -> uuid.UUID:
    process_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=process_id, node_type=EntityType.PROCESS, slug=slug))
        await session.flush()
        session.add(
            Process(
                process_id=process_id,
                revision=1,
                name=slug,
                slug=slug,
                description="…",
                archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
                status=ProcessStatus.ACTIVE,
            )
        )
        await session.commit()
    return process_id


async def _influences(session_factory, source: uuid.UUID, target: uuid.UUID) -> None:
    async with session_factory() as session:
        session.add(
            Relationship(
                relationship_id=uuid.uuid4(),
                revision=1,
                source_id=source,
                target_id=target,
                relationship_type=RelationshipType.INFLUENCES,
                weight=1.0,
                confidence=0.8,
            )
        )
        await session.commit()


async def test_a_clean_graph_reports_no_violations(session_factory):
    a = await _process(session_factory, "a")
    b = await _process(session_factory, "b")
    await _influences(session_factory, a, b)

    report = await GraphIntegrity(session_factory).check()

    assert report.ok
    assert await assert_healthy(session_factory)


async def test_a_direct_causal_cycle_is_found(session_factory):
    """A --influences--> B --influences--> A asserts A causes A."""
    a = await _process(session_factory, "a")
    b = await _process(session_factory, "b")
    await _influences(session_factory, a, b)
    await _influences(session_factory, b, a)

    cycles = await GraphIntegrity(session_factory).causal_cycles()

    assert {violation.node_id for violation in cycles} == {a, b}
    assert "cycle of length 2" in cycles[0].detail


async def test_a_longer_cycle_is_found(session_factory):
    a = await _process(session_factory, "a")
    b = await _process(session_factory, "b")
    c = await _process(session_factory, "c")
    await _influences(session_factory, a, b)
    await _influences(session_factory, b, c)
    await _influences(session_factory, c, a)

    cycles = await GraphIntegrity(session_factory).causal_cycles()

    assert len(cycles) == 3
    assert all("cycle of length 3" in violation.detail for violation in cycles)


async def test_a_diamond_is_not_a_cycle(session_factory):
    """Two routes to the same node is convergence, not circular causality."""
    a = await _process(session_factory, "a")
    b = await _process(session_factory, "b")
    c = await _process(session_factory, "c")
    d = await _process(session_factory, "d")
    await _influences(session_factory, a, b)
    await _influences(session_factory, a, c)
    await _influences(session_factory, b, d)
    await _influences(session_factory, c, d)

    assert await GraphIntegrity(session_factory).causal_cycles() == []


async def test_a_cycle_can_be_predicted_before_the_edge_is_written(session_factory):
    a = await _process(session_factory, "a")
    b = await _process(session_factory, "b")
    await _influences(session_factory, a, b)
    integrity = GraphIntegrity(session_factory)

    assert await integrity.would_create_cycle(b, a) is True
    assert await integrity.would_create_cycle(a, b) is False
    assert await integrity.would_create_cycle(a, a) is True


async def test_an_illegal_edge_is_caught_however_it_arrived(session_factory):
    """GraphWriter refuses these; this catches a fixture or migration that did not."""
    process_id = await _process(session_factory, "a")
    bottleneck_id, capability_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=bottleneck_id, node_type=EntityType.BOTTLENECK))
        session.add(Node(node_id=capability_id, node_type=EntityType.CAPABILITY, slug="c"))
        await session.flush()
        session.add(
            Bottleneck(
                bottleneck_id=bottleneck_id,
                revision=1,
                process_id=process_id,
                name="b",
                description="…",
                kind=BottleneckKind.CAPITAL,
                currently_binding=True,
                relief_indicators=[],
                confidence=0.8,
            )
        )
        session.add(
            Capability(
                capability_id=capability_id,
                revision=1,
                name="c",
                slug="c",
                description="…",
                aliases=[],
            )
        )
        await session.flush()
        # A Capability cannot "create" a Bottleneck — the chain runs the other way.
        session.add(
            Relationship(
                relationship_id=uuid.uuid4(),
                revision=1,
                source_id=capability_id,
                target_id=bottleneck_id,
                relationship_type=RelationshipType.CREATES,
                weight=1.0,
                confidence=0.9,
            )
        )
        await session.commit()

    violations = await GraphIntegrity(session_factory).illegal_edges()

    assert len(violations) == 1
    assert "capability --creates--> bottleneck" in violations[0].detail

    with pytest.raises(AssertionError, match="illegal_edge"):
        await assert_healthy(session_factory)


async def test_a_registry_row_with_no_entity_is_caught(session_factory):
    """A half-finished write leaves a node nothing can render."""
    async with session_factory() as session:
        session.add(Node(node_id=uuid.uuid4(), node_type=EntityType.PROCESS, slug="ghost"))
        await session.commit()

    violations = await GraphIntegrity(session_factory).orphaned_nodes()

    assert any(v.kind == "node_without_entity" for v in violations)


async def test_a_disconnected_capability_is_reported_but_does_not_block(session_factory):
    """Mid-pipeline a Capability exists briefly before anything requires it."""
    capability_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=capability_id, node_type=EntityType.CAPABILITY, slug="lonely"))
        await session.flush()
        session.add(
            Capability(
                capability_id=capability_id,
                revision=1,
                name="Lonely capability",
                slug="lonely",
                description="…",
                aliases=[],
            )
        )
        await session.commit()

    violations = await GraphIntegrity(session_factory).orphaned_nodes()
    assert any(v.kind == "disconnected_node" for v in violations)

    # Ignored by default, so ingestion is not blocked by a transient state.
    await assert_healthy(session_factory)


async def test_revision_uniqueness_is_verified(session_factory):
    a = await _process(session_factory, "a")
    assert await GraphIntegrity(session_factory).multiple_current_revisions() == []
    assert a
