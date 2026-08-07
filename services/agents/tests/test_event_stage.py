"""Claims → Events, against a real database.

The compression the whole Event layer exists for: many documents in, one Event
out, with the independent-source count reflecting how many reports actually
stand behind it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_agents import EventResolutionStage, PropagationPolicy
from econiq_data_models import AgentRun, Claim, Document, Event, EventClaim, Node
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import ClaimType, DocumentType, EntityType, ExtractionStatus
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

WIRE = (
    "The Pentagon acquired a 15 percent stake in MP Materials on Monday, the "
    "companies said in a joint statement, in the largest federal investment in "
    "a rare-earth producer to date."
)
SYNDICATED = "REUTERS - " + WIRE
INDEPENDENT = (
    "Defense officials confirmed a new equity position in the Mountain Pass "
    "operator, describing the arrangement as a strategic reserve measure after "
    "two years of negotiation over domestic magnet supply."
)


async def _seed_claim(
    session_factory, *, publisher: str, text: str, document_text: str, published: datetime = PUB
) -> uuid.UUID:
    """One document with one Claim, the shape ingestion + extraction produce."""
    document_id, claim_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=document_id, node_type=EntityType.DOCUMENT))
        session.add(Node(node_id=claim_id, node_type=EntityType.CLAIM))
        await session.flush()
        session.add(
            Document(
                document_id=document_id,
                source="feed",
                publisher=publisher,
                title=text[:80],
                document_type=DocumentType.NEWS_ARTICLE,
                publication_time=published,
                retrieved_at=published + timedelta(minutes=1),
                content_hash=uuid.uuid4().hex,
                raw_content=document_text,
                extraction_status=ExtractionStatus.PARSED,
            )
        )
        await session.flush()  # the Claim's FK needs the Document to exist first
        session.add(
            Claim(
                claim_id=claim_id,
                document_id=document_id,
                text=text,
                claim_type=ClaimType.REPORTED_CLAIM,
                source_location={"quote": text[:40]},
                extraction_confidence=0.9,
                entities=[],
            )
        )
        await session.commit()
    return claim_id


def _cluster(claim_ids, *, publishers, title="Pentagon takes stake in MP Materials", merge=None):
    return {
        "canonical_title": title,
        "description": "The US government acquired an equity position in MP Materials.",
        "event_type": "government_funding",
        "timestamp": PUB.isoformat(),
        "supporting_claim_ids": [str(cid) for cid in claim_ids],
        "distinct_publishers": publishers,
        "contradictions": [],
        "entities": [],
        "confidence": 0.9,
        "merge_into_event_id": merge,
        "schema_version": "1.0.0",
    }


def _resolution(*clusters, unassigned=()):
    return json.dumps(
        {
            "events": list(clusters),
            "unassigned_claim_ids": list(unassigned),
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _significance(materiality: float = 7.0, novelty: float = 7.0, trigger: bool = True) -> str:
    def judged(value: float):
        return {"value": value, "confidence": 0.8, "rationale": "…", "schema_version": "1.0.0"}

    return json.dumps(
        {
            "novelty": judged(novelty),
            "economic_materiality": judged(materiality),
            "credibility": judged(8.0),
            "persistence_potential": judged(7.0),
            "process_relevance": judged(8.0),
            "asset_relevance": judged(6.0),
            "should_trigger_update": trigger,
            "trigger_rationale": "material and corroborated",
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _stage(session_factory, *responses: str, policy: PropagationPolicy | None = None):
    return EventResolutionStage(
        LLMService(ScriptedProvider(responses), observers=[]), session_factory, policy=policy
    )


async def test_syndicated_coverage_collapses_to_one_independent_source(session_factory):
    """The compression the Event layer exists for."""
    wire = await _seed_claim(
        session_factory, publisher="Reuters", text=WIRE[:120], document_text=WIRE
    )
    reprints = [
        await _seed_claim(
            session_factory, publisher=f"Outlet {i}", text=WIRE[:120], document_text=SYNDICATED
        )
        for i in range(4)
    ]
    original = await _seed_claim(
        session_factory,
        publisher="Bloomberg",
        text=INDEPENDENT[:120],
        document_text=INDEPENDENT,
    )
    claim_ids = [wire, *reprints, original]

    stage = _stage(
        session_factory,
        _resolution(_cluster(claim_ids, publishers=["Reuters", "Bloomberg"])),
        _significance(),
    )
    outcome = await stage.run(as_of=PUB + timedelta(hours=1))

    assert len(outcome.events) == 1
    persisted = outcome.events[0].persisted
    # Six documents, two genuinely independent reports.
    assert persisted.independence.independent_source_count == 2
    assert outcome.duplicate_suppression == 4

    async with session_factory() as session:
        row = (await session.execute(select(Event).where(Event.valid_to.is_(None)))).scalar_one()
        links = (await session.execute(select(func.count()).select_from(EventClaim))).scalar_one()
    assert row.independent_source_count == 2
    assert links == 6


async def test_new_evidence_writes_a_revision_rather_than_overwriting(session_factory):
    first = await _seed_claim(
        session_factory, publisher="Reuters", text=WIRE[:120], document_text=WIRE
    )
    stage = _stage(
        session_factory,
        _resolution(_cluster([first], publishers=["Reuters"])),
        _significance(),
    )
    outcome = await stage.run(as_of=PUB + timedelta(hours=1))
    event_id = outcome.events[0].persisted.event_id

    later = await _seed_claim(
        session_factory,
        publisher="Bloomberg",
        text=INDEPENDENT[:120],
        document_text=INDEPENDENT,
        published=PUB + timedelta(days=1),
    )
    stage2 = _stage(
        session_factory,
        _resolution(_cluster([later], publishers=["Bloomberg"], merge=str(event_id))),
        _significance(),
    )
    second = await stage2.run(as_of=PUB + timedelta(days=2))

    assert second.events[0].persisted.created is False
    assert second.events[0].persisted.revision == 2

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(Event).where(Event.event_id == event_id).order_by(Event.revision)
                )
            )
            .scalars()
            .all()
        )
    assert [row.revision for row in rows] == [1, 2]
    # The superseded revision keeps what it believed at the time.
    assert rows[0].valid_to is not None
    assert rows[0].independent_source_count == 1
    assert rows[1].valid_to is None
    assert rows[1].independent_source_count == 2


async def test_a_held_event_is_stored_but_not_propagated(session_factory):
    """Most Events should not move the graph."""
    claim_id = await _seed_claim(
        session_factory, publisher="Reuters", text=WIRE[:120], document_text=WIRE
    )
    stage = _stage(
        session_factory,
        _resolution(_cluster([claim_id], publishers=["Reuters"])),
        _significance(materiality=2.0),
    )

    outcome = await stage.run(as_of=PUB + timedelta(hours=1))

    assert outcome.propagated == []
    assert "materiality" in (outcome.events[0].decision.reason or "")

    async with session_factory() as session:
        row = (await session.execute(select(Event).where(Event.valid_to.is_(None)))).scalar_one()
    assert row.propagated_at is None


async def test_significance_scores_land_on_the_event_revision(session_factory):
    """The scores describe that revision, so they are written with it."""
    claim_id = await _seed_claim(
        session_factory, publisher="Reuters", text=WIRE[:120], document_text=WIRE
    )
    stage = _stage(
        session_factory,
        _resolution(_cluster([claim_id], publishers=["Reuters"])),
        _significance(materiality=8.25, novelty=6.5),
    )

    await stage.run(as_of=PUB + timedelta(hours=1))

    async with session_factory() as session:
        row = (await session.execute(select(Event).where(Event.valid_to.is_(None)))).scalar_one()
    assert row.materiality == pytest.approx(8.25)
    assert row.novelty == pytest.approx(6.5)


async def test_a_material_corroborated_event_is_marked_propagated(session_factory):
    claims = [
        await _seed_claim(
            session_factory, publisher="Reuters", text=WIRE[:120], document_text=WIRE
        ),
        await _seed_claim(
            session_factory,
            publisher="Bloomberg",
            text=INDEPENDENT[:120],
            document_text=INDEPENDENT,
        ),
    ]
    stage = _stage(
        session_factory,
        _resolution(_cluster(claims, publishers=["Reuters", "Bloomberg"])),
        _significance(),
    )

    outcome = await stage.run(as_of=PUB + timedelta(hours=1))

    assert len(outcome.propagated) == 1
    async with session_factory() as session:
        row = (await session.execute(select(Event).where(Event.valid_to.is_(None)))).scalar_one()
    assert row.propagated_at is not None


async def test_clustered_claims_are_not_reconsidered_on_the_next_run(session_factory):
    claim_id = await _seed_claim(
        session_factory, publisher="Reuters", text=WIRE[:120], document_text=WIRE
    )
    stage = _stage(
        session_factory,
        _resolution(_cluster([claim_id], publishers=["Reuters"])),
        _significance(),
    )
    await stage.run(as_of=PUB + timedelta(hours=1))

    idle = _stage(session_factory)
    outcome = await idle.run(as_of=PUB + timedelta(hours=2))

    assert outcome.skipped_reason == "no unclustered claims"
    assert outcome.events == []


async def test_claims_published_after_the_as_of_date_are_invisible(session_factory):
    """An as-of run must not see evidence that did not exist yet (ontology §33)."""
    await _seed_claim(
        session_factory,
        publisher="Reuters",
        text=WIRE[:120],
        document_text=WIRE,
        published=PUB + timedelta(days=5),
    )

    outcome = await _stage(session_factory).run(as_of=PUB)

    assert outcome.skipped_reason == "no unclustered claims"


async def test_a_double_counted_claim_fails_the_partition_check(session_factory):
    """A Claim in two clusters has been counted twice as evidence."""
    claim_id = await _seed_claim(
        session_factory, publisher="Reuters", text=WIRE[:120], document_text=WIRE
    )
    stage = _stage(
        session_factory,
        _resolution(
            _cluster([claim_id], publishers=["Reuters"], title="First reading"),
            _cluster([claim_id], publishers=["Reuters"], title="Second reading"),
        ),
        _significance(),
        _significance(),
    )

    outcome = await stage.run(as_of=PUB + timedelta(hours=1))

    async with session_factory() as session:
        run = await session.get(AgentRun, outcome.resolution_run_id)
    assert run is not None
    assert run.evaluation["passed"] is False
    failed = [c["name"] for c in run.evaluation["checks"] if not c["passed"]]
    assert "claims_assigned_once" in failed


async def test_similar_prior_events_are_offered_to_the_agent(session_factory):
    """pgvector narrows the candidate set before the agent is asked anything."""
    first = await _seed_claim(
        session_factory, publisher="Reuters", text=WIRE[:120], document_text=WIRE
    )
    stage = _stage(
        session_factory,
        _resolution(_cluster([first], publishers=["Reuters"])),
        _significance(),
    )
    outcome = await stage.run(as_of=PUB + timedelta(hours=1))
    event_id = outcome.events[0].persisted.event_id

    later = await _seed_claim(
        session_factory,
        publisher="Bloomberg",
        text=WIRE[:120],
        document_text=INDEPENDENT,
        published=PUB + timedelta(days=1),
    )
    provider_stage = _stage(
        session_factory,
        _resolution(_cluster([later], publishers=["Bloomberg"], merge=str(event_id))),
        _significance(),
    )
    await provider_stage.run(as_of=PUB + timedelta(days=2))

    shown_to_agent = provider_stage.service.provider.requests[0].messages[0].content
    assert "Known Events this evidence might belong to" in shown_to_agent
    assert str(event_id) in shown_to_agent
