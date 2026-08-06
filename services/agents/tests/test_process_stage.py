"""Event → Process, against a real database.

Where the graph starts existing: Processes get created, accumulate evidence as
revisions, and carry a journal explaining every change.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_agents import GraphWriter, IllegalEdgeError, ProcessDiscoveryStage
from econiq_data_models import (
    Claim,
    Document,
    Event,
    EventClaim,
    EvidenceLink,
    JournalEntry,
    JournalEntryKind,
    Node,
    Process,
    Relationship,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import (
    ClaimType,
    DocumentType,
    EntityType,
    EpistemicStatus,
    EventType,
    ExtractionStatus,
    ProcessStatus,
    RelationshipType,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


async def _seed_event(session_factory, *, propagated: bool = True, title: str | None = None):
    """A propagated Event with one supporting Claim."""
    document_id, claim_id, event_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        for node_id, node_type in (
            (document_id, EntityType.DOCUMENT),
            (claim_id, EntityType.CLAIM),
            (event_id, EntityType.EVENT),
        ):
            session.add(Node(node_id=node_id, node_type=node_type))
        await session.flush()
        session.add(
            Document(
                document_id=document_id,
                source="feed",
                publisher="Reuters",
                title="Pentagon stake",
                document_type=DocumentType.NEWS_ARTICLE,
                publication_time=PUB,
                retrieved_at=PUB + timedelta(minutes=1),
                content_hash=uuid.uuid4().hex,
                extraction_status=ExtractionStatus.PARSED,
            )
        )
        await session.flush()
        session.add(
            Claim(
                claim_id=claim_id,
                document_id=document_id,
                text="The Pentagon acquired a 15 percent stake in a rare-earth producer.",
                claim_type=ClaimType.REPORTED_CLAIM,
                source_location={"quote": "acquired a 15 percent stake"},
                extraction_confidence=0.95,
                entities=[],
            )
        )
        session.add(
            Event(
                event_id=event_id,
                revision=1,
                event_type=EventType.GOVERNMENT_FUNDING,
                title=title or "US government takes equity stake in a rare-earth producer",
                description="The Pentagon acquired a 15 percent stake.",
                occurred_at=PUB,
                entities=[],
                independent_source_count=2,
                novelty=8.0,
                materiality=8.5,
                confidence=0.9,
                epistemic_status=EpistemicStatus.OBSERVED,
                contradictions=[],
                propagated_at=PUB if propagated else None,
            )
        )
        await session.flush()
        session.add(EventClaim(event_id=event_id, claim_id=claim_id))
        await session.commit()
    return event_id, claim_id


def _discovery(*, new=(), affected=(), claim_id="c1"):
    return json.dumps(
        {
            "new_processes": [
                {
                    "name": name,
                    "slug": slug,
                    "description": "The state is underwriting domestic rare-earth capacity.",
                    "suggested_archetype": None,
                    "causal_mechanism": "Federal equity funding lowers the cost of capital.",
                    "confidence": 0.85,
                    "supporting_claim_ids": [claim_id],
                    "contradicting_claim_ids": [],
                    "evidence": [],
                    "schema_version": "1.0.0",
                }
                for name, slug in new
            ],
            "affected_processes": [
                {
                    "process_id": str(process_id),
                    "implication": implication,
                    "causal_mechanism": "Direct federal support for the buildout.",
                    "direction": "advances the Process",
                    "confidence": 0.8,
                    "supporting_claim_ids": [claim_id],
                    "contradicting_claim_ids": [],
                    "evidence": [],
                    "schema_version": "1.0.0",
                }
                for process_id, implication in affected
            ],
            "unaffected_process_ids": [],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _update(*, claim_id="c1", beliefs=1, features=(("capex_acceleration", 0.08),), confidence=0.82):
    return json.dumps(
        {
            "belief_changes": [
                {
                    "statement": "Federal support for domestic separation is durable.",
                    "direction": "strengthened",
                    "rationale": "An equity stake is a longer commitment than a grant.",
                    "schema_version": "1.0.0",
                }
            ]
            * beliefs,
            "feature_deltas": [
                {"name": name, "delta": delta, "rationale": "…", "schema_version": "1.0.0"}
                for name, delta in features
            ],
            "state_change_recommended": False,
            "proposed_state": None,
            "confidence_after": confidence,
            "bottlenecks_may_have_changed": True,
            "capabilities_may_have_changed": False,
            "contradicts_existing_beliefs": False,
            "supporting_claim_ids": [claim_id],
            "contradicting_claim_ids": [],
            "evidence": [],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _stage(session_factory, *responses: str) -> ProcessDiscoveryStage:
    return ProcessDiscoveryStage(
        LLMService(ScriptedProvider(responses), observers=[]), session_factory
    )


async def test_a_new_process_is_created_flagged_and_journalled(session_factory):
    event_id, claim_id = await _seed_event(session_factory)
    stage = _stage(
        session_factory,
        _discovery(
            new=[("Domestic strategic-mineral security", "strategic-minerals")],
            claim_id=str(claim_id),
        ),
    )

    outcome = await stage.run(event_id)

    assert len(outcome.created) == 1
    persisted = outcome.created[0]

    async with session_factory() as session:
        process = (
            await session.execute(select(Process).where(Process.valid_to.is_(None)))
        ).scalar_one()
        entries = (
            (await session.execute(select(JournalEntry).order_by(JournalEntry.kind)))
            .scalars()
            .all()
        )

    # A new Process is a candidate awaiting review, not an established fact.
    assert process.status is ProcessStatus.CANDIDATE
    assert process.requires_review is True
    assert process.slug == "strategic-minerals"
    # Archetype classification belongs to the next agent, not this one.
    assert process.archetype is None
    assert persisted.requires_review

    kinds = {entry.kind for entry in entries}
    assert kinds == {JournalEntryKind.CREATED, JournalEntryKind.REVIEW_REQUESTED}
    assert all(entry.triggering_event_id == event_id for entry in entries)


async def test_the_event_is_linked_to_the_process_it_created(session_factory):
    event_id, claim_id = await _seed_event(session_factory)
    stage = _stage(
        session_factory,
        _discovery(
            new=[("Domestic strategic-mineral security", "strategic-minerals")],
            claim_id=str(claim_id),
        ),
    )

    outcome = await stage.run(event_id)

    async with session_factory() as session:
        edge = (
            await session.execute(select(Relationship).where(Relationship.valid_to.is_(None)))
        ).scalar_one()
    assert edge.source_id == event_id
    assert edge.target_id == outcome.created[0].process_id
    assert edge.relationship_type is RelationshipType.AFFECTS
    assert edge.rationale


async def test_a_material_change_writes_a_revision_and_a_belief_journal_entry(session_factory):
    event_id, claim_id = await _seed_event(session_factory)
    created = await _stage(
        session_factory,
        _discovery(
            new=[("Domestic strategic-mineral security", "strategic-minerals")],
            claim_id=str(claim_id),
        ),
    ).run(event_id)
    process_id = created.created[0].process_id

    second_event_id, second_claim_id = await _seed_event(
        session_factory, title="Congress appropriates further rare-earth funding"
    )
    stage = _stage(
        session_factory,
        _discovery(affected=[(process_id, "materially_changes")], claim_id=str(second_claim_id)),
        _update(claim_id=str(second_claim_id)),
    )

    outcome = await stage.run(second_event_id)

    assert len(outcome.updated) == 1
    applied = outcome.updated[0]
    assert applied.revision == 2
    assert applied.feature_deltas == {"capex_acceleration": 0.08}

    async with session_factory() as session:
        revisions = (
            (
                await session.execute(
                    select(Process)
                    .where(Process.process_id == process_id)
                    .order_by(Process.revision)
                )
            )
            .scalars()
            .all()
        )
        belief = (
            await session.execute(
                select(JournalEntry).where(JournalEntry.kind == JournalEntryKind.BELIEF_CHANGE)
            )
        ).scalar_one()

    assert [r.revision for r in revisions] == [1, 2]
    assert revisions[0].valid_to is not None
    # Evidence that changed beliefs promotes a candidate to active.
    assert revisions[1].status is ProcessStatus.ACTIVE
    assert "strengthened" in belief.summary
    assert "capex_acceleration +0.08" in belief.summary
    assert belief.confidence_after == pytest.approx(0.82)


async def test_corroboration_accumulates_without_writing_a_revision(session_factory):
    """A Process that held its belief through an Event is a different object
    from one re-derived."""
    event_id, claim_id = await _seed_event(session_factory)
    created = await _stage(
        session_factory,
        _discovery(
            new=[("Domestic strategic-mineral security", "strategic-minerals")],
            claim_id=str(claim_id),
        ),
    ).run(event_id)
    process_id = created.created[0].process_id

    second_event_id, second_claim_id = await _seed_event(session_factory, title="More coverage")
    stage = _stage(
        session_factory,
        _discovery(affected=[(process_id, "provides_evidence")], claim_id=str(second_claim_id)),
    )

    outcome = await stage.run(second_event_id)

    assert outcome.evidenced == [process_id]
    assert outcome.updated == []

    async with session_factory() as session:
        revisions = (
            await session.execute(
                select(func.count()).select_from(Process).where(Process.process_id == process_id)
            )
        ).scalar_one()
        evidence = (
            (
                await session.execute(
                    select(EvidenceLink).where(EvidenceLink.subject_id == process_id)
                )
            )
            .scalars()
            .all()
        )

    assert revisions == 1
    # The evidence still accumulates even though no belief moved.
    assert len(evidence) == 2
    assert all(link.supports for link in evidence)


async def test_state_review_is_flagged_for_the_next_agent_not_applied_here(session_factory):
    """The State layer has one owner; this stage carries the signal."""
    event_id, claim_id = await _seed_event(session_factory)
    created = await _stage(
        session_factory,
        _discovery(
            new=[("Domestic strategic-mineral security", "strategic-minerals")],
            claim_id=str(claim_id),
        ),
    ).run(event_id)
    process_id = created.created[0].process_id

    second_event_id, second_claim_id = await _seed_event(session_factory, title="Further funding")
    outcome = await _stage(
        session_factory,
        _discovery(affected=[(process_id, "materially_changes")], claim_id=str(second_claim_id)),
        _update(claim_id=str(second_claim_id)),
    ).run(second_event_id)

    assert outcome.needs_state_review == [process_id]

    from econiq_data_models import ProcessState

    async with session_factory() as session:
        states = (
            await session.execute(select(func.count()).select_from(ProcessState))
        ).scalar_one()
    assert states == 0


async def test_only_propagated_events_are_picked_up(session_factory):
    await _seed_event(session_factory, propagated=False)
    stage = _stage(session_factory)

    assert await stage.run_pending() == []


async def test_an_event_is_not_processed_twice(session_factory):
    _, claim_id = await _seed_event(session_factory)
    stage = _stage(
        session_factory,
        _discovery(
            new=[("Domestic strategic-mineral security", "strategic-minerals")],
            claim_id=str(claim_id),
        ),
    )

    first = await stage.run_pending()
    assert len(first) == 1

    second = await _stage(session_factory).run_pending()
    assert second == []


async def test_slug_collisions_do_not_fail_the_write(session_factory):
    first_event, first_claim = await _seed_event(session_factory)
    await _stage(
        session_factory,
        _discovery(
            new=[("Domestic strategic-mineral security", "strategic-minerals")],
            claim_id=str(first_claim),
        ),
    ).run(first_event)

    second_event, second_claim = await _seed_event(session_factory, title="A separate development")
    outcome = await _stage(
        session_factory,
        _discovery(
            new=[("Strategic minerals, second reading", "strategic-minerals")],
            claim_id=str(second_claim),
        ),
    ).run(second_event)

    assert outcome.created[0].slug == "strategic-minerals-2"


async def test_illegal_edges_are_refused_by_the_graph_writer(session_factory):
    """ALLOWED_EDGES is enforced at the write, not just documented."""
    writer = GraphWriter(session_factory)
    bottleneck_id, asset_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=bottleneck_id, node_type=EntityType.BOTTLENECK))
        session.add(Node(node_id=asset_id, node_type=EntityType.ASSET))
        await session.commit()

    with pytest.raises(IllegalEdgeError, match="not a legal edge"):
        await writer.relate(
            source_id=bottleneck_id,
            target_id=asset_id,
            relationship_type=RelationshipType.EXPRESSED_BY,
            confidence=0.9,
            agent_run_id=uuid.uuid4(),
        )

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(Relationship))).scalar_one()
    assert count == 0
