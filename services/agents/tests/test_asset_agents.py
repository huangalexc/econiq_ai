"""Asset discovery covers every instrument class, and resolves deterministically."""

from datetime import UTC, datetime

import pytest
from econiq_agents import (
    COMMODITIES,
    CURRENCIES,
    InstrumentBreadthEvaluator,
    NoRankingEvaluator,
    lookup,
    material_candidates,
    resolvable_names,
)
from econiq_ontology import Asset, AssetClass, AssetIdentifiers, ProcessArchetype
from econiq_schemas import AssetDiscoveryInput, AssetDiscoveryOutput

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _payload() -> AssetDiscoveryInput:
    return AssetDiscoveryInput(
        as_of=NOW,
        capability_id="c1",
        capability_name="Heavy rare-earth separation",
        capability_description="…",
    )


def _candidate(
    name: str,
    asset_class: str,
    *,
    ticker: str | None = None,
    confidence: float = 0.8,
    materiality: str = "material",
) -> dict:
    return {
        "proposed_name": name,
        "proposed_ticker": ticker,
        "proposed_exchange": None,
        "asset_class": asset_class,
        "exposure_pathway": "…",
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


def _output(*candidates: dict) -> AssetDiscoveryOutput:
    return AssetDiscoveryOutput.model_validate(
        {
            "candidates": list(candidates),
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _breadth(archetype, output) -> dict[str, bool]:
    checks = InstrumentBreadthEvaluator(archetype=archetype).evaluate(_payload(), output)
    return {check.name: check.passed for check in checks}


def test_gold_and_silver_resolve_from_name_or_code():
    """The user's case: precious metals are namable without a vendor feed."""
    for query in ("gold", "Gold", "XAU", "gold bullion"):
        assert lookup(query) is not None and lookup(query).commodity_code == "XAU", query
    assert lookup("silver").commodity_code == "XAG"
    assert lookup("Silver").benchmark == "LBMA Silver"


def test_currencies_resolve_to_pairs():
    assert lookup("yen").currency_pair == "USDJPY"
    assert lookup("USDJPY").currency_code == "JPY"
    assert lookup("euro").currency_pair == "EURUSD"


def test_commodity_cycle_staples_are_covered():
    for name in ("copper", "crude oil", "uranium", "lithium", "iron ore", "natural gas"):
        assert lookup(name) is not None, name


def test_lookup_is_exact_and_does_not_guess():
    """'Copper mining' is a different Asset from the copper price."""
    assert lookup("copper mining") is None
    assert lookup("gold miners") is None
    assert lookup(None) is None


def test_the_ontology_accepts_a_commodity_without_a_ticker():
    gold = lookup("gold")
    asset = Asset(
        name=gold.name,
        asset_class=AssetClass.COMMODITY,
        identifiers=AssetIdentifiers(commodity_code=gold.commodity_code),
    )
    assert asset.identifiers.ticker is None


def test_the_ontology_still_requires_an_identifier_of_some_kind():
    with pytest.raises(ValueError, match="commodity requires one of"):
        Asset(name="Something", asset_class=AssetClass.COMMODITY)
    with pytest.raises(ValueError, match="currency requires one of"):
        Asset(name="Some pair", asset_class=AssetClass.CURRENCY)


def test_a_commodity_cycle_expressed_only_through_equities_is_flagged():
    """Not refused — an equity-only answer can be right — but noticed."""
    output = _output(
        _candidate("Freeport-McMoRan", "common_stock", ticker="FCX"),
        _candidate("Southern Copper", "common_stock", ticker="SCCO"),
    )
    checks = _breadth(ProcessArchetype.COMMODITY_SUPPLY_CYCLE, output)
    assert checks["instrument_classes_considered"] is False

    advisories = InstrumentBreadthEvaluator(
        archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE
    ).evaluate(_payload(), output)
    assert all(not check.blocking for check in advisories)


def test_including_the_commodity_itself_satisfies_the_breadth_check():
    output = _output(
        _candidate("Freeport-McMoRan", "common_stock", ticker="FCX"),
        _candidate("Copper", "commodity", ticker="HG"),
    )
    assert _breadth(ProcessArchetype.COMMODITY_SUPPLY_CYCLE, output)[
        "instrument_classes_considered"
    ]


def test_an_s_curve_process_is_not_expected_to_produce_a_commodity():
    output = _output(_candidate("Vertiv", "common_stock", ticker="VRT"))
    assert _breadth(ProcessArchetype.INFRASTRUCTURE_S_CURVE, output)[
        "instrument_classes_considered"
    ]


def test_an_unknown_commodity_is_reported_rather_than_silently_dropped():
    output = _output(_candidate("Unobtainium", "commodity", ticker="UNO"))
    checks = _breadth(None, output)
    assert checks["non_equity_candidates_resolve"] is False


def test_an_implicit_ranking_is_flagged_as_an_advisory():
    output = _output(
        _candidate("A", "common_stock", ticker="A", confidence=0.95),
        _candidate("B", "common_stock", ticker="B", confidence=0.7),
        _candidate("C", "common_stock", ticker="C", confidence=0.4),
    )
    checks = NoRankingEvaluator().evaluate(_payload(), output)
    assert checks[0].passed is False
    assert checks[0].blocking is False


def test_similar_confidences_are_not_treated_as_a_ranking():
    output = _output(
        _candidate("A", "common_stock", ticker="A", confidence=0.85),
        _candidate("B", "commodity", ticker="XAU", confidence=0.8),
    )
    assert NoRankingEvaluator().evaluate(_payload(), output)[0].passed


def test_only_material_candidates_are_promoted():
    output = _output(
        _candidate("Core name", "common_stock", ticker="A"),
        _candidate("Tangential name", "common_stock", ticker="B", materiality="incidental"),
    )
    assert material_candidates(output) == [0]


def test_the_reference_universe_is_offered_to_callers():
    names = resolvable_names(AssetClass.COMMODITY)
    assert "Gold" in names and "Silver" in names
    assert len(COMMODITIES) >= 15
    assert len(CURRENCIES) >= 10
