"""The Discover feed and screener (issue #20).

The ranking is arithmetic over rows, so most of what can go wrong here is a
component that silently contributes nothing — which looks exactly like a
component that contributes nothing because the data says so.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_data_models import (
    AssetExposure,
    Bottleneck,
    Capability,
    Claim,
    Document,
    Event,
    EventClaim,
    EvidenceLink,
    Node,
    Process,
    ProcessState,
    Relationship,
)
from econiq_ontology import (
    BottleneckKind,
    ClaimType,
    DocumentType,
    EntityType,
    EpistemicStatus,
    EventType,
    ExposureKind,
    ExtractionStatus,
    ProcessArchetype,
    ProcessStatus,
    RelationshipType,
)
from econiq_ontology import (
    ProcessStateLabel as S,
)
from sqlalchemy import update

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
# The graph is backdated so an `as_of` in the past is a replay rather than a
# read of rows that did not exist yet. A Process created today is correctly
# invisible thirty days ago.
CREATED = NOW - timedelta(days=120)


async def _process(
    session,
    name: str,
    *,
    slug: str,
    status: ProcessStatus = ProcessStatus.ACTIVE,
    state: S | None = S.SUPPLY_TIGHTNESS,
    confidence: float = 0.8,
    state_age_days: int = 3,
) -> uuid.UUID:
    process_id = uuid.uuid4()
    session.add(Node(node_id=process_id, node_type=EntityType.PROCESS, slug=slug))
    await session.flush()
    session.add(
        Process(
            process_id=process_id,
            revision=1,
            name=name,
            slug=slug,
            description="…",
            archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
            archetype_confidence=0.85,
            status=status,
            valid_from=CREATED,
        )
    )
    await session.flush()
    if state is not None:
        session.add(
            ProcessState(
                process_state_id=uuid.uuid4(),
                process_id=process_id,
                observed_at=NOW - timedelta(days=state_age_days),
                archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                categorical_state=state,
                state_confidence=confidence,
                transition_beliefs={},
                transition_indicators=[],
                reversal_indicators=[],
                recorded_at=NOW - timedelta(days=state_age_days),
            )
        )
        await session.flush()
    return process_id


async def _evidence(
    session,
    process_id: uuid.UUID,
    *,
    days_ago: int,
    supports: bool = True,
    publisher: str = "Wire A",
    novelty: float = 7.0,
) -> uuid.UUID:
    """One Event, its Claim and its Document, linked as evidence."""
    document_id, claim_id, event_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for node_id, kind in (
        (document_id, EntityType.DOCUMENT),
        (claim_id, EntityType.CLAIM),
        (event_id, EntityType.EVENT),
    ):
        session.add(Node(node_id=node_id, node_type=kind))
    await session.flush()

    session.add(
        Document(
            document_id=document_id,
            source="test",
            publisher=publisher,
            title="…",
            document_type=DocumentType.NEWS_ARTICLE,
            publication_time=NOW - timedelta(days=days_ago),
            retrieved_at=NOW - timedelta(days=days_ago),
            content_hash=uuid.uuid4().hex,
            extraction_status=ExtractionStatus.PARSED,
        )
    )
    session.add(
        Event(
            event_id=event_id,
            revision=1,
            event_type=EventType.GOVERNMENT_FUNDING,
            title="…",
            description="…",
            occurred_at=NOW - timedelta(days=days_ago),
            entities=[],
            independent_source_count=1,
            novelty=novelty,
            materiality=8.0,
            confidence=0.9,
            epistemic_status=EpistemicStatus.OBSERVED,
            contradictions=[],
        )
    )
    await session.flush()
    session.add(
        Claim(
            claim_id=claim_id,
            document_id=document_id,
            text="…",
            claim_type=ClaimType.REPORTED_CLAIM,
            source_location={"quote": "x", "char_start": 0, "char_end": 1},
            extraction_confidence=0.9,
            entities=[],
        )
    )
    await session.flush()
    session.add(EventClaim(event_id=event_id, claim_id=claim_id))

    link_id = uuid.uuid4()
    session.add(
        EvidenceLink(
            evidence_link_id=link_id,
            subject_id=process_id,
            evidence_id=event_id,
            supports=supports,
            weight=0.9,
        )
    )
    await session.flush()
    # `created_at` is server-set to now; the window comparison reads it, so a
    # test about acceleration has to be able to backdate it.
    await session.execute(
        update(EvidenceLink)
        .where(EvidenceLink.evidence_link_id == link_id)
        .values(created_at=NOW - timedelta(days=days_ago))
    )
    return event_id


async def _chain(session, process_id: uuid.UUID, *, assets: int) -> None:
    """Process → Bottleneck → Capability → n Assets."""
    bottleneck_id, capability_id = uuid.uuid4(), uuid.uuid4()
    session.add(Node(node_id=bottleneck_id, node_type=EntityType.BOTTLENECK))
    session.add(Node(node_id=capability_id, node_type=EntityType.CAPABILITY))
    await session.flush()
    session.add(
        Bottleneck(
            bottleneck_id=bottleneck_id,
            revision=1,
            process_id=process_id,
            name="Separation capacity",
            description="…",
            kind=BottleneckKind.PROCESSING_CAPACITY,
            currently_binding=True,
            confidence=0.85,
            resolved=False,
        )
    )
    session.add(
        Capability(
            capability_id=capability_id,
            revision=1,
            name="Separation",
            slug=f"sep-{capability_id.hex[:6]}",
            description="…",
            aliases=[],
        )
    )
    await session.flush()

    for source, target, kind in (
        (process_id, bottleneck_id, RelationshipType.CREATES),
        (bottleneck_id, capability_id, RelationshipType.REQUIRES),
    ):
        session.add(
            Relationship(
                relationship_id=uuid.uuid4(),
                revision=1,
                source_id=source,
                target_id=target,
                relationship_type=kind,
                weight=0.9,
                confidence=0.9,
                rationale="…",
            )
        )

    for index in range(assets):
        asset_id = uuid.uuid4()
        session.add(Node(node_id=asset_id, node_type=EntityType.ASSET))
        await session.flush()
        from econiq_data_models import Asset
        from econiq_ontology import AssetClass

        session.add(
            Asset(
                asset_id=asset_id,
                revision=1,
                name=f"Asset {index}",
                asset_class=AssetClass.COMMON_STOCK,
                ticker=f"T{index}{asset_id.hex[:3]}",
                currency="USD",
            )
        )
        await session.flush()
        session.add(
            AssetExposure(
                asset_exposure_id=uuid.uuid4(),
                asset_id=asset_id,
                target_id=capability_id,
                target_type=EntityType.CAPABILITY,
                exposure_kind=ExposureKind.PRODUCTION_CAPABILITY,
                directness="direct",
                magnitude=8.0,
                rationale="…",
                confidence=0.85,
                observed_at=NOW - timedelta(days=1),
            )
        )
    await session.flush()


@pytest.fixture
async def feed_graph(session_factory):
    """Two Processes: one accelerating, one that stopped moving."""
    ids: dict[str, uuid.UUID] = {}
    async with session_factory() as session:
        hot = await _process(session, "Accelerating", slug="hot", confidence=0.9)
        cold = await _process(session, "Stalled", slug="cold", confidence=0.6, state_age_days=200)
        ids["hot"], ids["cold"] = hot, cold

        # Hot: four this window, one the window before.
        for days in (2, 5, 9, 20):
            await _evidence(session, hot, days_ago=days, publisher=f"Wire {days}")
        await _evidence(session, hot, days_ago=45, publisher="Wire old")
        await _chain(session, hot, assets=3)

        # Cold: nothing recent, three in the prior window.
        for days in (40, 50, 55):
            await _evidence(session, cold, days_ago=days)
        await _chain(session, cold, assets=1)

        await session.commit()
    return ids


async def test_the_feed_ranks_the_accelerating_process_first(client, feed_graph):
    response = await client.get("/api/discover")

    assert response.status_code == 200
    body = response.json()
    names = [row["name"] for row in body["processes"]]
    assert names == ["Accelerating", "Stalled"]


async def test_every_rank_can_be_taken_apart(client, feed_graph):
    """A rank nobody can decompose is a number the reader has to trust (#25)."""
    body = (await client.get("/api/discover")).json()
    row = body["processes"][0]

    assert {c["name"] for c in row["components"]} == set(body["weights"])
    # The score is exactly the sum of its parts, not a separate calculation.
    assert row["rank_score"] == pytest.approx(
        sum(c["contribution"] for c in row["components"]), abs=1e-3
    )
    for component in row["components"]:
        assert component["contribution"] == pytest.approx(
            component["normalised"] * component["weight"], abs=1e-4
        )


async def test_the_feed_names_the_inputs_it_cannot_compute(client, feed_graph):
    """A ranking that silently drops half its stated inputs is a different ranking."""
    body = (await client.get("/api/discover")).json()

    missing = {item["name"]: item["reason"] for item in body["unavailable_inputs"]}
    assert "market_attention" in missing
    assert "source_breadth" in missing["market_attention"]
    assert "historical_analogue_strength" in missing
    assert "Phase 2" in missing["historical_analogue_strength"]


async def test_the_ordering_is_not_presented_as_a_forecast(client, feed_graph):
    """ui_concept §5.2: a discovery visualisation, not a predictive claim."""
    body = (await client.get("/api/discover")).json()

    assert body["is_prediction"] is False


async def test_media_coverage_is_reported_beside_the_rank_not_inside_it(client, feed_graph):
    """Calling publisher count 'attention' would make §5.2's claim untestable."""
    body = (await client.get("/api/discover")).json()
    hot = next(row for row in body["processes"] if row["name"] == "Accelerating")

    # Four distinct publishers this window plus one older.
    assert hot["source_breadth"] == 5
    assert "source_breadth" not in body["weights"]
    assert all(c["name"] != "source_breadth" for c in hot["components"])


async def test_evidence_windows_are_reported_so_the_delta_is_checkable(client, feed_graph):
    body = (await client.get("/api/discover")).json()
    hot = next(row for row in body["processes"] if row["name"] == "Accelerating")
    cold = next(row for row in body["processes"] if row["name"] == "Stalled")

    assert (hot["evidence_recent"], hot["evidence_prior"]) == (4, 1)
    assert hot["evidence_delta"] == 3
    # Deceleration is representable, not clamped to zero.
    assert cold["evidence_recent"] == 0
    assert cold["evidence_delta"] < 0


async def test_contradicting_evidence_is_counted_not_netted_off(
    client, session_factory, feed_graph
):
    """Contradiction is a scored dimension, not a deduction (ontology §17)."""
    async with session_factory() as session:
        await _evidence(session, feed_graph["hot"], days_ago=3, supports=False)
        await session.commit()

    body = (await client.get("/api/discover")).json()
    hot = next(row for row in body["processes"] if row["name"] == "Accelerating")

    assert hot["contradiction_count"] == 1
    # It arrived in the window, so it still counts as evidence activity.
    assert hot["evidence_recent"] == 5


async def test_the_screener_filters_without_reordering(client, feed_graph):
    """§25. A screener that reranked would answer a different question."""
    unfiltered = (await client.get("/api/discover")).json()
    order = [row["name"] for row in unfiltered["processes"]]

    filtered = (await client.get("/api/discover", params={"min_assets": 2})).json()

    assert [row["name"] for row in filtered["processes"]] == ["Accelerating"]
    assert order.index("Accelerating") < order.index("Stalled")


async def test_the_screener_filters_on_state_and_confidence(client, feed_graph):
    high = await client.get("/api/discover", params={"min_state_confidence": 0.85})
    assert [row["name"] for row in high.json()["processes"]] == ["Accelerating"]

    wrong_state = await client.get("/api/discover", params={"state": "price_acceleration"})
    assert wrong_state.json()["processes"] == []


async def test_accelerating_only_excludes_a_process_that_stopped_moving(client, feed_graph):
    body = (await client.get("/api/discover", params={"accelerating_only": True})).json()

    assert [row["name"] for row in body["processes"]] == ["Accelerating"]


async def test_a_merged_process_does_not_appear_twice_under_two_names(
    client, session_factory, feed_graph
):
    """A merged Process *is* another Process; listing both double-counts it."""
    async with session_factory() as session:
        # `merged` without a target is refused by the database, which is the
        # right constraint: a merge that does not say what it merged into is
        # just a deletion.
        await session.execute(
            update(Process)
            .where(Process.process_id == feed_graph["cold"])
            .values(status=ProcessStatus.MERGED, merged_into=feed_graph["hot"])
        )
        await session.commit()

    body = (await client.get("/api/discover")).json()

    assert [row["name"] for row in body["processes"]] == ["Accelerating"]


async def test_the_feed_honours_a_past_cut_off(client, feed_graph):
    """As of 30 days ago, this window's evidence had not been recorded."""
    cut = (NOW - timedelta(days=30)).isoformat()

    body = (await client.get("/api/discover", params={"as_of": cut})).json()
    hot = next(row for row in body["processes"] if row["name"] == "Accelerating")

    # Only the 45-day-old link precedes the cut-off.
    assert hot["evidence_recent"] == 1
    assert hot["source_breadth"] == 1


async def test_binding_bottlenecks_travel_with_the_card(client, feed_graph):
    """§5.3's hot card names the constraints, so the feed carries them."""
    body = (await client.get("/api/discover")).json()
    hot = next(row for row in body["processes"] if row["name"] == "Accelerating")

    assert hot["binding_bottlenecks"] == ["Separation capacity"]
    assert hot["capability_count"] == 1
    assert hot["asset_count"] == 3


async def test_source_breadth_and_evidence_independence_measure_different_things(
    client, session_factory, feed_graph
):
    """One wire story carried by two outlets is one source but two publishers.

    The Event layer collapses syndication so confidence cannot inflate
    (ontology §47). The coverage proxy must not, or a story everybody ran looks
    obscure. Asserted here because the two numbers look interchangeable and are
    not.
    """
    before = (await client.get("/api/discover")).json()
    hot_before = next(r for r in before["processes"] if r["name"] == "Accelerating")

    async with session_factory() as session:
        # A second outlet, same window.
        await _evidence(session, feed_graph["hot"], days_ago=4, publisher="Syndicating Outlet")
        await session.commit()

    after = (await client.get("/api/discover")).json()
    hot_after = next(r for r in after["processes"] if r["name"] == "Accelerating")

    assert hot_after["source_breadth"] == hot_before["source_breadth"] + 1


async def test_one_outlet_publishing_repeatedly_is_still_one_voice(
    client, session_factory, feed_graph
):
    async with session_factory() as session:
        for _ in range(3):
            await _evidence(session, feed_graph["hot"], days_ago=6, publisher="Wire 2")
        await session.commit()

    body = (await client.get("/api/discover")).json()
    hot = next(r for r in body["processes"] if r["name"] == "Accelerating")

    # "Wire 2" was already present, so three more of its stories add no breadth.
    assert hot["source_breadth"] == 5
