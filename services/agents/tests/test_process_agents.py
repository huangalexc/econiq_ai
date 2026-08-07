"""The layer boundary: these agents must not reach the Asset layer."""

from datetime import UTC, datetime

from econiq_agents import LayerBoundaryEvaluator
from econiq_schemas import EventSummary, ProcessDiscoveryInput, ProcessDiscoveryOutput

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _payload() -> ProcessDiscoveryInput:
    return ProcessDiscoveryInput(
        as_of=NOW,
        event=EventSummary(
            event_id="e1",
            title="Pentagon takes stake in MP Materials",
            description="…",
            timestamp=NOW,
            materiality=8.0,
            novelty=7.0,
        ),
    )


def _output(mechanism: str) -> ProcessDiscoveryOutput:
    return ProcessDiscoveryOutput.model_validate(
        {
            "new_processes": [
                {
                    "name": "Domestic strategic-mineral security",
                    "slug": "domestic-strategic-mineral-security",
                    "description": "The state is underwriting domestic rare-earth capacity.",
                    "suggested_archetype": None,
                    "causal_mechanism": mechanism,
                    "confidence": 0.8,
                    "supporting_claim_ids": ["c1"],
                    "contradicting_claim_ids": [],
                    "evidence": [],
                    "schema_version": "1.0.0",
                }
            ],
            "affected_processes": [],
            "unaffected_process_ids": [],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _checks(mechanism: str) -> dict[str, bool]:
    checks = LayerBoundaryEvaluator(layer="Process").evaluate(_payload(), _output(mechanism))
    return {check.name: check.passed for check in checks}


def test_ordinary_economic_prose_passes():
    assert all(
        _checks(
            "Federal equity funding lowers the cost of capital for domestic "
            "separation capacity, which accelerates the buildout."
        ).values()
    )


def test_a_ticker_is_caught():
    checks = _checks("This is bullish for $MP and the wider sector.")
    assert checks["no_asset_identifiers"] is False


def test_an_exchange_qualified_ticker_is_caught():
    assert _checks("NYSE: MP benefits directly.")["no_asset_identifiers"] is False


def test_recommendation_vocabulary_is_caught():
    assert _checks("Investors should buy exposure here.")["no_investment_language"] is False
    assert _checks("Shares of the operator will re-rate.")["no_investment_language"] is False


def test_industrial_vocabulary_is_not_mistaken_for_asset_language():
    """'Stockpile' and 'long lead times' are ordinary economics, not tickers."""
    checks = _checks(
        "The government is building a strategic stockpile, and long lead times "
        "for separation capacity constrain the response."
    )
    assert checks["no_asset_identifiers"] is True
    assert checks["no_investment_language"] is True
