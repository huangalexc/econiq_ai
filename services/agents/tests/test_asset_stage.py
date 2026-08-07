"""Capability → Asset, against a real database."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from econiq_agents import AssetDiscoveryStage
from econiq_data_models import (
    Asset,
    AssetCandidate,
    AssetExposure,
    Bottleneck,
    Capability,
    CapabilityRequirement,
    Node,
    Process,
    ProcessState,
    Relationship,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import (
    AssetClass,
    BottleneckKind,
    EntityType,
    ExposureKind,
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


async def _seed_graph(
    session_factory,
    *,
    archetype: ProcessArchetype = ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
    capability_name: str = "Heavy rare-earth separation",
    slug: str = "minerals",
) -> uuid.UUID:
    """Process → Bottleneck → Capability, the shape issue #11 leaves behind."""
    process_id = uuid.uuid4()
    bottleneck_id = uuid.uuid4()
    capability_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(Node(node_id=process_id, node_type=EntityType.PROCESS, slug=slug))
        session.add(Node(node_id=bottleneck_id, node_type=EntityType.BOTTLENECK))
        session.add(
            Node(node_id=capability_id, node_type=EntityType.CAPABILITY, slug=f"{slug}-cap")
        )
        await session.flush()
        session.add(
            Process(
                process_id=process_id,
                revision=1,
                name="Domestic strategic-mineral security",
                slug=slug,
                description="The state is underwriting domestic rare-earth capacity.",
                archetype=archetype,
                archetype_confidence=0.8,
                status=ProcessStatus.ACTIVE,
            )
        )
        session.add(
            Bottleneck(
                bottleneck_id=bottleneck_id,
                revision=1,
                process_id=process_id,
                name="Heavy rare-earth separation capacity",
                description="Separation capacity outside China is minimal.",
                kind=BottleneckKind.PROCESSING_CAPACITY,
                currently_binding=True,
                relief_indicators=["Non-Chinese separation tonnage rises"],
                confidence=0.85,
                resolved=False,
            )
        )
        session.add(
            Capability(
                capability_id=capability_id,
                revision=1,
                name=capability_name,
                slug=f"{slug}-cap",
                description="The ability to separate heavy rare-earth oxides at scale.",
                aliases=[],
            )
        )
        session.add(
            ProcessState(
                process_id=process_id,
                observed_at=PUB,
                archetype=archetype,
                categorical_state=(
                    S.SUPPLY_TIGHTNESS
                    if archetype is ProcessArchetype.COMMODITY_SUPPLY_CYCLE
                    else S.ACCELERATION
                ),
                state_confidence=0.8,
                transition_beliefs={},
                transition_indicators=[],
                reversal_indicators=[],
            )
        )
        await session.flush()
        session.add(
            CapabilityRequirement(
                requirement_id=uuid.uuid4(),
                revision=1,
                bottleneck_id=bottleneck_id,
                process_id=process_id,
                root_node_id=uuid.uuid4(),
            )
        )
        session.add(
            Relationship(
                relationship_id=uuid.uuid4(),
                revision=1,
                source_id=bottleneck_id,
                target_id=capability_id,
                relationship_type=RelationshipType.REQUIRES,
                weight=1.0,
                confidence=1.0,
            )
        )
        await session.commit()
    return capability_id


def _candidate(
    name: str,
    asset_class: str,
    *,
    ticker: str | None = None,
    materiality: str = "material",
    confidence: float = 0.8,
) -> dict:
    return {
        "proposed_name": name,
        "proposed_ticker": ticker,
        "proposed_exchange": None,
        "asset_class": asset_class,
        "exposure_pathway": "Processing capacity is the binding input.",
        "directness": "direct",
        "materiality": materiality,
        "geography": None,
        "dependencies": [],
        "confidence": confidence,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _discovery(*candidates: dict) -> str:
    return json.dumps(
        {
            "candidates": list(candidates),
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _exposure(*, kind: str = "production_capability", magnitude: float = 8.0, offsetting=()) -> str:
    return json.dumps(
        {
            "exposures": [
                {
                    "exposure_kind": kind,
                    "directness": "direct",
                    "magnitude": magnitude,
                    "revenue_share": None,
                    "rationale": "Separation is the core of the operation.",
                    "quantitative_basis": None,
                    "confidence": 0.8,
                    "supporting_claim_ids": [],
                    "contradicting_claim_ids": [],
                    "evidence": [],
                    "schema_version": "1.0.0",
                }
            ],
            "dependencies": [],
            "offsetting_exposures": list(offsetting),
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _stage(session_factory, *responses: str) -> AssetDiscoveryStage:
    return AssetDiscoveryStage(
        LLMService(ScriptedProvider(responses), observers=[]), session_factory
    )


async def test_a_commodity_resolves_against_the_reference_universe(session_factory):
    """The commodity itself, not only the miners."""
    capability_id = await _seed_graph(session_factory)
    stage = _stage(
        session_factory,
        _discovery(_candidate("Neodymium-praseodymium oxide", "commodity", ticker="NDPR")),
        _exposure(),
    )

    outcome = await stage.run(capability_id)

    assert outcome.resolved == 1
    async with session_factory() as session:
        asset = (await session.execute(select(Asset))).scalar_one()
    assert asset.asset_class is AssetClass.COMMODITY
    assert asset.commodity_code == "NDPR"
    assert asset.benchmark == "Asian Metal NdPr Oxide"
    assert asset.ticker is None


async def test_gold_and_a_currency_resolve_alongside_equities(session_factory):
    capability_id = await _seed_graph(session_factory)
    stage = _stage(
        session_factory,
        _discovery(
            _candidate("MP Materials", "common_stock", ticker="MP"),
            _candidate("Gold", "commodity", ticker="XAU"),
            _candidate("USD/JPY", "currency", ticker="USDJPY", materiality="incidental"),
        ),
        _exposure(),
        _exposure(),
    )

    outcome = await stage.run(capability_id)

    assert outcome.resolved == 3
    async with session_factory() as session:
        rows = (await session.execute(select(Asset).order_by(Asset.asset_class))).scalars().all()
    by_class = {row.asset_class: row for row in rows}
    assert by_class[AssetClass.COMMON_STOCK].ticker == "MP"
    assert by_class[AssetClass.COMMODITY].commodity_code == "XAU"
    assert by_class[AssetClass.CURRENCY].currency_pair == "USDJPY"
    assert by_class[AssetClass.CURRENCY].currency_code == "JPY"


async def test_the_same_commodity_reached_twice_is_one_node(session_factory):
    """Two theses converging on gold must converge on one Asset."""
    first = await _seed_graph(session_factory)
    second = await _seed_graph(
        session_factory, capability_name="Monetary debasement hedging", slug="monetary"
    )

    await _stage(
        session_factory, _discovery(_candidate("Gold", "commodity", ticker="XAU")), _exposure()
    ).run(first)
    await _stage(
        session_factory, _discovery(_candidate("Gold", "commodity", ticker="XAU")), _exposure()
    ).run(second)

    async with session_factory() as session:
        assets = (await session.execute(select(func.count()).select_from(Asset))).scalar_one()
        edges = (
            await session.execute(
                select(func.count())
                .select_from(Relationship)
                .where(Relationship.relationship_type == RelationshipType.EXPRESSED_BY)
            )
        ).scalar_one()

    assert assets == 1
    # One Asset, two Capabilities expressing themselves through it.
    assert edges == 2


async def test_an_unresolvable_commodity_is_kept_as_a_candidate(session_factory):
    """The record that discovery found something the system cannot name."""
    capability_id = await _seed_graph(session_factory)
    stage = _stage(session_factory, _discovery(_candidate("Unobtainium", "commodity")))

    outcome = await stage.run(capability_id)

    assert outcome.resolved == 0
    assert "reference universe" in outcome.unresolved[0]
    assert outcome.resolution_rate == 0.0

    async with session_factory() as session:
        candidate = (await session.execute(select(AssetCandidate))).scalar_one()
        assets = (await session.execute(select(func.count()).select_from(Asset))).scalar_one()
    assert candidate.resolved_asset_id is None
    assert "reference universe" in (candidate.resolution_note or "")
    assert assets == 0


async def test_an_equity_without_a_ticker_stays_a_candidate(session_factory):
    """Guessing an identifier would put an unverifiable one in the graph."""
    capability_id = await _seed_graph(session_factory)
    stage = _stage(
        session_factory, _discovery(_candidate("A private separation venture", "common_stock"))
    )

    outcome = await stage.run(capability_id)

    assert outcome.resolved == 0
    assert "no usable identifier" in outcome.unresolved[0]


async def test_the_capability_is_linked_to_its_expressions(session_factory):
    capability_id = await _seed_graph(session_factory)
    stage = _stage(
        session_factory,
        _discovery(_candidate("MP Materials", "common_stock", ticker="MP")),
        _exposure(),
    )

    await stage.run(capability_id)

    async with session_factory() as session:
        edge = (
            await session.execute(
                select(Relationship).where(
                    Relationship.relationship_type == RelationshipType.EXPRESSED_BY
                )
            )
        ).scalar_one()
    assert edge.source_id == capability_id
    assert edge.rationale


async def test_exposures_are_recorded_for_material_candidates_only(session_factory):
    capability_id = await _seed_graph(session_factory)
    stage = _stage(
        session_factory,
        _discovery(
            _candidate("MP Materials", "common_stock", ticker="MP"),
            _candidate("Gold", "commodity", ticker="XAU", materiality="incidental"),
        ),
        _exposure(magnitude=9.0),
    )

    outcome = await stage.run(capability_id)

    assert outcome.resolved == 2
    assert len(outcome.exposures) == 1

    async with session_factory() as session:
        rows = (await session.execute(select(AssetExposure))).scalars().all()
    assert len(rows) == 1
    assert rows[0].magnitude == pytest.approx(9.0)
    assert rows[0].exposure_kind is ExposureKind.PRODUCTION_CAPABILITY
    assert rows[0].target_id == capability_id
    # Dated by the evidence, not by wall-clock time.
    assert rows[0].observed_at == PUB


async def test_an_equity_only_commodity_cycle_produces_an_advisory(session_factory):
    """Recorded, surfaced, and explicitly not refused."""
    capability_id = await _seed_graph(
        session_factory, archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE
    )
    stage = _stage(
        session_factory,
        _discovery(_candidate("MP Materials", "common_stock", ticker="MP")),
        _exposure(),
    )

    outcome = await stage.run(capability_id)

    assert outcome.resolved == 1  # the work still landed
    assert any("only equity expressions" in advisory for advisory in outcome.advisories)

    from econiq_data_models import AgentRun

    async with session_factory() as session:
        run = await session.get(AgentRun, outcome.discovery_run_id)
    assert run is not None
    assert run.evaluation["advisories"] == ["instrument_classes_considered"]
    # Advisories do not fail the run.
    assert run.evaluation["passed"] is True


async def test_capabilities_are_picked_up_only_from_binding_bottlenecks(session_factory):
    capability_id = await _seed_graph(session_factory)

    pending = await _stage(session_factory)._pending_capability_ids(10)
    assert pending == [capability_id]

    async with session_factory() as session:
        await session.execute(Bottleneck.__table__.update().values(currently_binding=False))
        await session.commit()

    assert await _stage(session_factory)._pending_capability_ids(10) == []


async def test_a_capability_already_expressed_is_not_rediscovered(session_factory):
    capability_id = await _seed_graph(session_factory)
    await _stage(
        session_factory,
        _discovery(_candidate("MP Materials", "common_stock", ticker="MP")),
        _exposure(),
    ).run(capability_id)

    assert await _stage(session_factory).run_pending() == []
