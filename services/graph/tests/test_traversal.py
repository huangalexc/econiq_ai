"""Traversal over a real graph in Postgres."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from econiq_data_models import (
    Asset,
    Bottleneck,
    Capability,
    Claim,
    Document,
    Event,
    EventClaim,
    EvidenceLink,
    Node,
    Process,
    Relationship,
)
from econiq_graph import Direction, GraphQueries, TraversalSpec
from econiq_ontology import (
    AssetClass,
    BottleneckKind,
    ClaimType,
    DocumentType,
    EntityType,
    EpistemicStatus,
    EventType,
    ExtractionStatus,
    ProcessArchetype,
    ProcessStatus,
    RelationshipType,
)
from sqlalchemy import update

pytestmark = pytest.mark.integration

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


@dataclass
class Chain:
    process: uuid.UUID
    bottleneck: uuid.UUID
    capability: uuid.UUID
    asset: uuid.UUID
    event: uuid.UUID
    claim: uuid.UUID
    document: uuid.UUID


async def _seed_chain(session_factory, *, suffix: str = "a", asset_id: uuid.UUID | None = None):
    """A full Document → Claim → Event → Process → Bottleneck → Capability → Asset chain."""
    ids = Chain(
        process=uuid.uuid4(),
        bottleneck=uuid.uuid4(),
        capability=uuid.uuid4(),
        asset=asset_id or uuid.uuid4(),
        event=uuid.uuid4(),
        claim=uuid.uuid4(),
        document=uuid.uuid4(),
    )
    async with session_factory() as session:
        session.add(Node(node_id=ids.process, node_type=EntityType.PROCESS, slug=f"proc-{suffix}"))
        session.add(Node(node_id=ids.bottleneck, node_type=EntityType.BOTTLENECK))
        session.add(
            Node(node_id=ids.capability, node_type=EntityType.CAPABILITY, slug=f"cap-{suffix}")
        )
        session.add(Node(node_id=ids.event, node_type=EntityType.EVENT))
        session.add(Node(node_id=ids.document, node_type=EntityType.DOCUMENT))
        session.add(Node(node_id=ids.claim, node_type=EntityType.CLAIM))
        if asset_id is None:
            session.add(Node(node_id=ids.asset, node_type=EntityType.ASSET))
        await session.flush()

        session.add(
            Process(
                process_id=ids.process,
                revision=1,
                name=f"Process {suffix.upper()}",
                slug=f"proc-{suffix}",
                description="…",
                archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                status=ProcessStatus.ACTIVE,
            )
        )
        session.add(
            Bottleneck(
                bottleneck_id=ids.bottleneck,
                revision=1,
                process_id=ids.process,
                name=f"Bottleneck {suffix.upper()}",
                description="…",
                kind=BottleneckKind.PROCESSING_CAPACITY,
                currently_binding=True,
                relief_indicators=[],
                confidence=0.8,
            )
        )
        session.add(
            Capability(
                capability_id=ids.capability,
                revision=1,
                name=f"Capability {suffix.upper()}",
                slug=f"cap-{suffix}",
                description="…",
                aliases=[],
            )
        )
        if asset_id is None:
            session.add(
                Asset(
                    asset_id=ids.asset,
                    revision=1,
                    name="Copper",
                    asset_class=AssetClass.COMMODITY,
                    commodity_code="HG",
                )
            )
        session.add(
            Document(
                document_id=ids.document,
                source="feed",
                publisher="Reuters",
                title=f"Report {suffix}",
                document_type=DocumentType.NEWS_ARTICLE,
                publication_time=PUB,
                retrieved_at=PUB + timedelta(minutes=1),
                content_hash=uuid.uuid4().hex,
                extraction_status=ExtractionStatus.PARSED,
            )
        )
        session.add(
            Event(
                event_id=ids.event,
                revision=1,
                event_type=EventType.SUPPLY_DISRUPTION,
                title=f"Event {suffix.upper()}",
                description="…",
                occurred_at=PUB,
                entities=[],
                independent_source_count=2,
                novelty=7.0,
                materiality=8.0,
                confidence=0.9,
                epistemic_status=EpistemicStatus.OBSERVED,
                contradictions=[],
            )
        )
        await session.flush()
        session.add(
            Claim(
                claim_id=ids.claim,
                document_id=ids.document,
                text="A smelter outage was announced.",
                claim_type=ClaimType.REPORTED_CLAIM,
                source_location={"quote": "outage"},
                extraction_confidence=0.9,
                entities=[],
            )
        )
        session.add(EventClaim(event_id=ids.event, claim_id=ids.claim))
        session.add(
            EvidenceLink(subject_id=ids.process, evidence_id=ids.event, supports=True, weight=0.9)
        )
        for source, target, kind, weight in (
            (ids.event, ids.process, RelationshipType.AFFECTS, 1.0),
            (ids.process, ids.bottleneck, RelationshipType.CREATES, 0.9),
            (ids.bottleneck, ids.capability, RelationshipType.REQUIRES, 1.0),
            (ids.capability, ids.asset, RelationshipType.EXPRESSED_BY, 0.8),
        ):
            session.add(
                Relationship(
                    relationship_id=uuid.uuid4(),
                    revision=1,
                    source_id=source,
                    target_id=target,
                    relationship_type=kind,
                    weight=weight,
                    confidence=0.9,
                    rationale=f"{kind.value} link",
                )
            )
        await session.commit()
    return ids


async def test_the_full_chain_is_walkable_downstream(session_factory):
    ids = await _seed_chain(session_factory)
    graph = GraphQueries(session_factory)

    reach = await graph.assets_within_hops([ids.process])

    assert len(reach) == 1
    assert reach[0].asset.node_id == ids.asset
    assert reach[0].asset.label == "Copper"
    assert reach[0].shortest_hops == 3

    path = reach[0].paths[0]
    assert [node.node_type for node in path.nodes] == [
        EntityType.PROCESS,
        EntityType.BOTTLENECK,
        EntityType.CAPABILITY,
        EntityType.ASSET,
    ]
    assert [edge.relationship_type for edge in path.edges] == [
        RelationshipType.CREATES,
        RelationshipType.REQUIRES,
        RelationshipType.EXPRESSED_BY,
    ]
    # Weight is the product along the path: a route through weak links is weak.
    assert path.weight == pytest.approx(0.9 * 1.0 * 0.8)


async def test_the_discovery_chain_answers_why_this_asset_is_here(session_factory):
    ids = await _seed_chain(session_factory)
    graph = GraphQueries(session_factory)

    chains = await graph.discovery_chain(ids.asset)

    assert len(chains) == 1
    assert chains[0].start.node_id == ids.asset
    assert chains[0].end.node_id == ids.process
    assert "expressed_by" in chains[0].describe()


async def test_hop_limits_are_respected(session_factory):
    ids = await _seed_chain(session_factory)
    graph = GraphQueries(session_factory)

    assert await graph.assets_within_hops([ids.process], max_hops=2) == []
    assert len(await graph.assets_within_hops([ids.process], max_hops=3)) == 1


async def test_an_asset_reached_from_two_processes_is_one_result(session_factory):
    """Confluence: several sources, one Asset, and the count is visible."""
    first = await _seed_chain(session_factory, suffix="a")
    second = await _seed_chain(session_factory, suffix="b", asset_id=first.asset)
    graph = GraphQueries(session_factory)

    reach = await graph.assets_within_hops([first.process, second.process])

    assert len(reach) == 1
    assert len(reach[0].distinct_sources) == 2
    assert len(reach[0].paths) == 2


async def test_confluence_returns_the_shortest_route_per_process(session_factory):
    first = await _seed_chain(session_factory, suffix="a")
    second = await _seed_chain(session_factory, suffix="b", asset_id=first.asset)
    graph = GraphQueries(session_factory)

    upstream = await graph.confluence(first.asset)

    assert {path.end.node_id for path in upstream} == {first.process, second.process}
    assert all(path.depth == 3 for path in upstream)


async def test_a_causal_cycle_terminates_instead_of_hanging(session_factory):
    """Causal graphs acquire cycles; a traversal that assumes otherwise hangs."""
    first = await _seed_chain(session_factory, suffix="a")
    second = await _seed_chain(session_factory, suffix="b")

    async with session_factory() as session:
        for source, target in ((first.process, second.process), (second.process, first.process)):
            session.add(
                Relationship(
                    relationship_id=uuid.uuid4(),
                    revision=1,
                    source_id=source,
                    target_id=target,
                    relationship_type=RelationshipType.INFLUENCES,
                    weight=1.0,
                    confidence=0.7,
                )
            )
        await session.commit()

    graph = GraphQueries(session_factory)
    paths = await graph.traverse(
        [first.process], TraversalSpec(max_hops=8, direction=Direction.DOWNSTREAM)
    )

    assert paths
    for path in paths:
        ids = [node.node_id for node in path.nodes]
        assert len(ids) == len(set(ids)), "a node was revisited"


async def test_traversal_respects_the_as_of_date(session_factory):
    """Walking today's graph while claiming to describe July is a leak."""
    ids = await _seed_chain(session_factory)
    graph = GraphQueries(session_factory)

    # A marker after the edges were written, and a closure strictly after it, so
    # the assertion does not depend on how fast the seed ran.
    marker = datetime.now(UTC)
    async with session_factory() as session:
        await session.execute(
            update(Relationship)
            .where(
                Relationship.source_id == ids.capability,
                Relationship.relationship_type == RelationshipType.EXPRESSED_BY,
            )
            .values(valid_to=marker + timedelta(seconds=1))
        )
        await session.commit()

    # The edge is gone from the current graph …
    assert await graph.assets_within_hops([ids.process]) == []
    # … but a run as of while it was still open sees it.
    before = await graph.assets_within_hops([ids.process], as_of=marker)
    assert len(before) == 1
    assert before[0].asset.node_id == ids.asset


async def test_the_evidence_trail_reaches_the_documents(session_factory):
    ids = await _seed_chain(session_factory)
    graph = GraphQueries(session_factory)

    trail = await graph.evidence_trail(ids.process)

    assert trail.subject.node_id == ids.process
    assert [event.node_id for event in trail.events] == [ids.event]
    assert trail.claims == (ids.claim,)
    assert trail.documents == (ids.document,)
    assert trail.is_evidenced


async def test_contradicting_evidence_is_kept_separate(session_factory):
    ids = await _seed_chain(session_factory)
    contradiction = uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=contradiction, node_type=EntityType.EVENT))
        await session.flush()
        session.add(
            Event(
                event_id=contradiction,
                revision=1,
                event_type=EventType.CAPACITY_CHANGE,
                title="Smelter restarts ahead of schedule",
                description="…",
                occurred_at=PUB,
                entities=[],
                independent_source_count=1,
                novelty=6.0,
                materiality=6.0,
                confidence=0.8,
                epistemic_status=EpistemicStatus.OBSERVED,
                contradictions=[],
            )
        )
        await session.flush()
        session.add(
            EvidenceLink(
                subject_id=ids.process, evidence_id=contradiction, supports=False, weight=0.7
            )
        )
        await session.commit()

    trail = await GraphQueries(session_factory).evidence_trail(ids.process)

    assert [e.node_id for e in trail.events] == [ids.event]
    assert [e.node_id for e in trail.contradicting_events] == [contradiction]


async def test_a_subgraph_carries_both_directions(session_factory):
    ids = await _seed_chain(session_factory)
    graph = GraphQueries(session_factory)

    rendered = await graph.subgraph([ids.bottleneck], depth=2)

    assert ids.process in rendered.node_ids
    assert ids.capability in rendered.node_ids
    assert ids.asset in rendered.node_ids
    assert ids.event in rendered.node_ids


async def test_neighbors_is_one_hop_only(session_factory):
    ids = await _seed_chain(session_factory)
    graph = GraphQueries(session_factory)

    downstream = await graph.neighbors(ids.process, direction=Direction.DOWNSTREAM)
    upstream = await graph.neighbors(ids.process, direction=Direction.UPSTREAM)

    assert [edge.target_id for edge in downstream] == [ids.bottleneck]
    assert [edge.source_id for edge in upstream] == [ids.event]


async def test_traversal_from_nothing_returns_nothing(session_factory):
    graph = GraphQueries(session_factory)
    assert await graph.traverse([]) == []
    assert await graph.assets_within_hops([uuid.uuid4()]) == []
