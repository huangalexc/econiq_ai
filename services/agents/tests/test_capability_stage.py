"""Bottlenecks, Capabilities and requirement trees, against a real database."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_agents import CapabilityStage
from econiq_data_models import (
    Bottleneck,
    Capability,
    CapabilityRequirement,
    Claim,
    Document,
    Event,
    EventClaim,
    EvidenceLink,
    Node,
    Process,
    ProcessState,
    Relationship,
    RequirementNode,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import (
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
from econiq_ontology import (
    ProcessStateLabel as S,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


async def _seed_process(
    session_factory, *, name: str = "AI infrastructure expansion", slug: str = "ai-infra"
) -> uuid.UUID:
    """A Process with a State and one supporting Event."""
    process_id, event_id = uuid.uuid4(), uuid.uuid4()
    document_id, claim_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        for node_id, node_type in (
            (process_id, EntityType.PROCESS),
            (event_id, EntityType.EVENT),
            (document_id, EntityType.DOCUMENT),
            (claim_id, EntityType.CLAIM),
        ):
            session.add(Node(node_id=node_id, node_type=node_type, slug=None))
        await session.flush()
        session.add(
            Process(
                process_id=process_id,
                revision=1,
                name=name,
                slug=slug,
                description="Compute demand is driving a datacentre and power buildout.",
                archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
                archetype_confidence=0.8,
                status=ProcessStatus.ACTIVE,
            )
        )
        session.add(
            Document(
                document_id=document_id,
                source="feed",
                publisher="Reuters",
                title="Grid queues lengthen",
                document_type=DocumentType.NEWS_ARTICLE,
                publication_time=PUB,
                retrieved_at=PUB + timedelta(minutes=1),
                content_hash=uuid.uuid4().hex,
                extraction_status=ExtractionStatus.PARSED,
            )
        )
        session.add(
            Event(
                event_id=event_id,
                revision=1,
                event_type=EventType.CAPACITY_CHANGE,
                title="Interconnection queue times lengthen",
                description="Utilities reported longer interconnection queues.",
                occurred_at=PUB,
                entities=[],
                independent_source_count=2,
                novelty=7.0,
                materiality=8.0,
                confidence=0.9,
                epistemic_status=EpistemicStatus.OBSERVED,
                contradictions=[],
                propagated_at=PUB,
            )
        )
        await session.flush()
        session.add(
            Claim(
                claim_id=claim_id,
                document_id=document_id,
                text="Interconnection queue times lengthened again this quarter.",
                claim_type=ClaimType.REPORTED_CLAIM,
                source_location={"quote": "queue times lengthened"},
                extraction_confidence=0.9,
                entities=[],
            )
        )
        session.add(EventClaim(event_id=event_id, claim_id=claim_id))
        session.add(
            EvidenceLink(subject_id=process_id, evidence_id=event_id, supports=True, weight=0.9)
        )
        session.add(
            ProcessState(
                process_id=process_id,
                observed_at=PUB,
                archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
                categorical_state=S.ACCELERATION,
                state_confidence=0.82,
                transition_beliefs={},
                transition_indicators=[],
                reversal_indicators=[],
            )
        )
        await session.commit()
    return process_id


def _bottlenecks(*candidates: dict, index: int | None = 0) -> str:
    return json.dumps(
        {
            "candidates": list(candidates),
            "binding_candidate_index": index,
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _candidate(
    name: str = "Grid interconnection capacity",
    *,
    binding: bool = True,
    kind: str = BottleneckKind.INFRASTRUCTURE.value,
) -> dict:
    return {
        "name": name,
        "description": "New load cannot connect faster than queues clear.",
        "kind": kind,
        "why_limiting": "Datacentres cannot energise without an interconnection slot.",
        "currently_binding": binding,
        "demand_pressure": 9.1,
        "supply_elasticity": 4.2,
        "time_to_expand": 8.8,
        "current_constraint": 8.6,
        "relief_indicators": ["Interconnection queue times fall"],
        "confidence": 0.85,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _capability(ref: str, name: str, role: str = "necessary") -> dict:
    return {
        "ref": ref,
        "name": name,
        "description": f"The ability to deliver {name.lower()}.",
        "role": role,
        "confidence": 0.85,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _leaf(ref: str, necessity: str = "required", weight: float = 1.0) -> dict:
    return {
        "node": "capability",
        "ref": ref,
        "necessity": necessity,
        "weight": weight,
        "schema_version": "1.0.0",
    }


def _group(operator: str, *children: dict) -> dict:
    return {
        "node": "group",
        "operator": operator,
        "children": list(children),
        "necessity": "required",
        "weight": 1.0,
        "label": None,
        "schema_version": "1.0.0",
    }


def _mapping(capabilities: list[dict], tree: dict) -> str:
    return json.dumps(
        {
            "capabilities": capabilities,
            "requirement_tree": tree,
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _confluence(*support: tuple[str, str]) -> str:
    return json.dumps(
        {
            "upstream": [
                {
                    "process_id": pid,
                    "independence": independence,
                    "support_strength": 7.5,
                    "rationale": "…",
                    "supporting_claim_ids": [],
                    "contradicting_claim_ids": [],
                    "evidence": [],
                    "schema_version": "1.0.0",
                }
                for pid, independence in support
            ],
            "interactions": [],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _stage(session_factory, *responses: str) -> CapabilityStage:
    return CapabilityStage(LLMService(ScriptedProvider(responses), observers=[]), session_factory)


def _standard_mapping() -> str:
    return _mapping(
        [
            _capability("transmission", "High-voltage transmission construction"),
            _capability("transformers", "Large power transformer manufacturing"),
        ],
        _group("and", _leaf("transmission"), _leaf("transformers")),
    )


async def test_bottlenecks_are_stored_and_linked_to_the_process(session_factory):
    process_id = await _seed_process(session_factory)
    stage = _stage(
        session_factory,
        _bottlenecks(_candidate(), _candidate("Turbine supply", binding=False), index=0),
        _standard_mapping(),
    )

    outcome = await stage.run(process_id)

    assert len(outcome.bottlenecks) == 2
    assert outcome.binding is not None

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(Bottleneck)
                    .where(Bottleneck.valid_to.is_(None))
                    .order_by(Bottleneck.name)
                )
            )
            .scalars()
            .all()
        )
        edges = (
            (
                await session.execute(
                    select(Relationship).where(
                        Relationship.relationship_type == RelationshipType.CREATES
                    )
                )
            )
            .scalars()
            .all()
        )

    assert [row.currently_binding for row in rows] == [True, False]
    assert rows[0].demand_pressure == pytest.approx(9.1)
    assert rows[0].relief_indicators == ["Interconnection queue times fall"]
    # Process --creates--> Bottleneck, the canonical edge of ui_concept §9.1.
    assert len(edges) == 2
    assert all(edge.source_id == process_id for edge in edges)


async def test_only_the_binding_bottleneck_is_mapped(session_factory):
    """Mapping a constraint that will not bite for years invents a problem."""
    process_id = await _seed_process(session_factory)
    stage = _stage(
        session_factory,
        _bottlenecks(_candidate(binding=False), index=None),
    )

    outcome = await stage.run(process_id)

    assert outcome.skipped_reason == "no currently binding bottleneck"
    assert outcome.requirement is None

    async with session_factory() as session:
        capabilities = (
            await session.execute(select(func.count()).select_from(Capability))
        ).scalar_one()
    assert capabilities == 0


async def test_the_requirement_tree_round_trips_through_postgres(session_factory):
    """AND must still mean AND after a database round trip."""
    process_id = await _seed_process(session_factory)
    stage = _stage(session_factory, _bottlenecks(_candidate()), _standard_mapping())

    outcome = await stage.run(process_id)
    assert outcome.binding is not None

    requirement = await stage.capabilities.load_requirement(outcome.binding.bottleneck_id)
    assert requirement is not None

    ids = sorted(requirement.capability_ids())
    assert len(ids) == 2
    # The ontology's own evaluation, answered off the stored tree.
    assert requirement.is_satisfied_by(frozenset(ids))
    assert not requirement.is_satisfied_by(frozenset(ids[:1]))
    assert requirement.coverage(frozenset(ids[:1])) == pytest.approx(0.5)


async def test_an_or_tree_survives_the_round_trip_as_an_or(session_factory):
    process_id = await _seed_process(session_factory)
    mapping = _mapping(
        [
            _capability("transmission", "High-voltage transmission construction"),
            _capability("storage", "Grid-scale storage deployment"),
            _capability("generation", "On-site generation"),
        ],
        _group(
            "and",
            _leaf("transmission"),
            _group("or", _leaf("storage"), _leaf("generation")),
        ),
    )
    stage = _stage(session_factory, _bottlenecks(_candidate()), mapping)

    outcome = await stage.run(process_id)
    assert outcome.binding is not None
    requirement = await stage.capabilities.load_requirement(outcome.binding.bottleneck_id)
    assert requirement is not None

    by_slug = await _capability_ids_by_slug(session_factory)
    transmission = by_slug["high-voltage-transmission-construction"]
    storage = by_slug["grid-scale-storage-deployment"]
    generation = by_slug["on-site-generation"]

    # Either branch of the OR satisfies it, but transmission is required.
    assert requirement.is_satisfied_by(frozenset({transmission, storage}))
    assert requirement.is_satisfied_by(frozenset({transmission, generation}))
    assert not requirement.is_satisfied_by(frozenset({storage, generation}))


async def test_optional_capabilities_do_not_block_satisfaction_after_storage(session_factory):
    process_id = await _seed_process(session_factory)
    mapping = _mapping(
        [
            _capability("transmission", "High-voltage transmission construction"),
            # Complementary, not necessary: declaring it necessary and then
            # marking it optional is the inconsistency the evaluator refuses.
            _capability("software", "Grid management software", role="complementary"),
        ],
        _group("and", _leaf("transmission"), _leaf("software", necessity="optional")),
    )
    stage = _stage(session_factory, _bottlenecks(_candidate()), mapping)

    outcome = await stage.run(process_id)
    assert outcome.binding is not None
    requirement = await stage.capabilities.load_requirement(outcome.binding.bottleneck_id)
    assert requirement is not None

    by_slug = await _capability_ids_by_slug(session_factory)
    assert requirement.is_satisfied_by(
        frozenset({by_slug["high-voltage-transmission-construction"]})
    )
    # It is still part of the requirement, just not blocking.
    assert len(requirement.capability_ids()) == 2


async def test_two_processes_needing_the_same_capability_share_one_node(session_factory):
    """Confluence only becomes visible if the Capability is one node."""
    first = await _seed_process(session_factory, name="AI infrastructure", slug="ai-infra")
    second = await _seed_process(session_factory, name="Grid decarbonisation", slug="grid-decarb")

    await _stage(session_factory, _bottlenecks(_candidate()), _standard_mapping()).run(first)
    outcome = await _stage(
        session_factory,
        _bottlenecks(_candidate("Transformer lead times")),
        _standard_mapping(),
        _confluence(("p1", "independent")),
        _confluence(("p1", "independent")),
    ).run(second)

    async with session_factory() as session:
        capabilities = (
            await session.execute(
                select(func.count()).select_from(Capability).where(Capability.valid_to.is_(None))
            )
        ).scalar_one()
        requirements = (
            await session.execute(select(func.count()).select_from(CapabilityRequirement))
        ).scalar_one()

    # Two Bottlenecks, two requirement trees, but the same two Capabilities.
    assert capabilities == 2
    assert requirements == 2
    assert outcome.reused_capabilities == 2
    assert all(not c.created for c in outcome.requirement.capabilities)
    assert all(c.matched_by == "slug" for c in outcome.requirement.capabilities)


async def test_confluence_counts_only_independent_upstream_support(session_factory):
    first = await _seed_process(session_factory, name="AI infrastructure", slug="ai-infra")
    second = await _seed_process(session_factory, name="Grid decarbonisation", slug="grid-decarb")
    await _stage(session_factory, _bottlenecks(_candidate()), _standard_mapping()).run(first)

    process_ids = await _process_ids(session_factory)
    stage = _stage(
        session_factory,
        _bottlenecks(_candidate("Transformer lead times")),
        _standard_mapping(),
        _confluence((process_ids[0], "independent"), (process_ids[1], "redundant")),
        _confluence((process_ids[0], "independent"), (process_ids[1], "independent")),
    )

    outcome = await stage.run(second)

    assert len(outcome.confluence) == 2
    assert [result.independent_support for result in outcome.confluence] == [1, 2]


async def test_a_single_upstream_process_is_not_asked_about(session_factory):
    """There is no confluence to assess, so no call is spent asking."""
    process_id = await _seed_process(session_factory)
    stage = _stage(session_factory, _bottlenecks(_candidate()), _standard_mapping())

    outcome = await stage.run(process_id)

    assert outcome.confluence == []


async def test_bottlenecks_and_capabilities_are_linked_by_a_requires_edge(session_factory):
    process_id = await _seed_process(session_factory)
    stage = _stage(session_factory, _bottlenecks(_candidate()), _standard_mapping())

    outcome = await stage.run(process_id)
    assert outcome.binding is not None

    async with session_factory() as session:
        edges = (
            (
                await session.execute(
                    select(Relationship).where(
                        Relationship.relationship_type == RelationshipType.REQUIRES,
                        Relationship.valid_to.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(edges) == 2
    assert all(edge.source_id == outcome.binding.bottleneck_id for edge in edges)


async def test_re_running_revises_the_bottleneck_and_the_requirement(session_factory):
    process_id = await _seed_process(session_factory)
    await _stage(session_factory, _bottlenecks(_candidate()), _standard_mapping()).run(process_id)
    outcome = await _stage(session_factory, _bottlenecks(_candidate()), _standard_mapping()).run(
        process_id
    )

    assert outcome.binding is not None
    assert outcome.binding.created is False
    assert outcome.binding.revision == 2
    assert outcome.requirement is not None
    assert outcome.requirement.revision == 2

    async with session_factory() as session:
        current = (
            await session.execute(
                select(func.count())
                .select_from(CapabilityRequirement)
                .where(CapabilityRequirement.valid_to.is_(None))
            )
        ).scalar_one()
        nodes = (
            await session.execute(select(func.count()).select_from(RequirementNode))
        ).scalar_one()

    assert current == 1  # one current revision
    assert nodes == 6  # both revisions' trees are kept: 3 nodes each


async def test_a_rejected_bottleneck_output_writes_nothing(session_factory):
    process_id = await _seed_process(session_factory)
    unwatchable = _candidate()
    unwatchable["relief_indicators"] = []
    stage = _stage(session_factory, _bottlenecks(unwatchable))

    outcome = await stage.run(process_id)

    assert outcome.rejected_reason is not None
    assert outcome.bottlenecks == []

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(Bottleneck))).scalar_one()
    assert count == 0


async def _capability_ids_by_slug(session_factory) -> dict[str, uuid.UUID]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Capability.slug, Capability.capability_id).where(
                    Capability.valid_to.is_(None)
                )
            )
        ).all()
    return {row.slug: row.capability_id for row in rows}


async def _process_ids(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Process.process_id)
                .where(Process.valid_to.is_(None))
                .order_by(Process.created_at)
            )
        ).scalars()
        return [str(row) for row in rows]
