"""Historical Asset matching (#43) and extreme-opportunity search (#46)."""

from __future__ import annotations

import inspect as _inspect
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from econiq_market import (
    MIN_DIMENSIONS,
    MIN_EXAMPLES,
    AssetFeatures,
    Configuration,
    Episode,
    Lens,
    Outcome,
    attach_outcomes,
    coverage_note,
    features_from,
    find_extremes,
    match,
    outcome_index,
    search,
)

THEN = datetime(2020, 6, 1, tzinfo=UTC)
NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _features(asset: str, when: datetime, **kwargs) -> AssetFeatures:
    base = {"trend": 1.1, "volatility": 0.30, "drawdown": -0.05}
    return AssetFeatures(asset_id=asset, observed_at=when, **{**base, **kwargs})


# --------------------------------------------------------------------------- #
# #43 — outcome-blind by construction
# --------------------------------------------------------------------------- #


def test_features_cannot_hold_an_outcome():
    """§9.3: do not use eventual success as a matching criterion. A field that
    exists gets used, so none exists."""
    fields = set(AssetFeatures.__dataclass_fields__)

    for forbidden in ("return", "outcome", "succeeded", "outperformed", "forward_return"):
        assert forbidden not in fields


def test_the_matcher_has_no_parameter_an_outcome_could_reach():
    """Enforcement rather than a promise: there is no ordering of these calls
    that lets a similarity score depend on what happened next."""
    parameters = set(_inspect.signature(match).parameters)

    assert parameters == {"subject", "candidates", "limit", "same_capability_only"}
    assert not any("outcome" in name for name in parameters)


def test_outcomes_are_joined_only_after_matching():
    subject = _features("now", NOW)
    candidate = _features("past", THEN)
    matches = match(subject, [candidate])

    outcome = Outcome(episode=Episode(asset_id="past", observed_at=THEN), returns={"24m": 4.0})
    joined = attach_outcomes(matches, outcome_index([outcome]))

    assert len(joined) == 1
    # The Match itself never carried it.
    assert not hasattr(joined[0].match, "outcome")
    assert joined[0].outcome.returns["24m"] == 4.0


def test_a_match_with_no_recorded_outcome_is_dropped_not_nulled():
    """A match whose outcome is unknown is not evidence about outcomes, and
    keeping it would let it be counted in a distribution as if it were."""
    matches = match(_features("now", NOW), [_features("past", THEN)])

    assert attach_outcomes(matches, {}) == []


def test_candidates_from_the_future_are_excluded():
    """A 'historical' analogue from the future is not one."""
    later = _features("later", NOW + timedelta(days=30))

    assert match(_features("now", NOW), [later]) == []


def test_an_asset_does_not_match_itself():
    earlier_self = _features("same", THEN)

    assert match(_features("same", NOW), [earlier_self]) == []


def test_similarity_reports_which_dimensions_it_used():
    """A score of 0.9 over three dimensions and one over ten are different
    claims, and the reader needs both numbers."""
    subject = _features("now", NOW)
    close = _features("close", THEN)
    partial = AssetFeatures(asset_id="partial", observed_at=THEN, trend=1.1)

    results = match(subject, [close, partial])

    by_asset = {m.candidate.asset_id: m for m in results}
    assert by_asset["close"].dimensions == (
        "technical_state",
        "volatility_regime",
        "drawdown_state",
    )
    assert by_asset["partial"].dimensions == ("technical_state",)
    assert by_asset["partial"].is_thin is True
    assert by_asset["close"].is_thin is False


def test_a_closer_asset_scores_higher():
    subject = _features("now", NOW, trend=1.20)
    near = _features("near", THEN, trend=1.19)
    far = _features("far", THEN, trend=0.70)

    results = match(subject, [far, near])

    assert results[0].candidate.asset_id == "near"
    assert results[0].similarity > results[1].similarity


def test_the_dimensions_that_cannot_be_matched_are_declared():
    """A similarity over three dimensions presented as covering ten is a worse
    artefact than a thin one that says so."""
    missing = dict(coverage_note())

    assert {"valuation", "growth", "market_share", "market_regime"} <= set(missing)
    assert all(reason for reason in missing.values())
    assert MIN_DIMENSIONS == 3


def test_features_are_read_through_the_lens():
    """So they cannot include a revision of an in-window bar recorded later."""
    day = THEN - timedelta(days=10)
    prices = pl.DataFrame(
        {
            "observed_at": [day, day],
            "recorded_at": [day, NOW],
            "adj_close": [100.0, 50.0],
        }
    )

    result = features_from(Episode(asset_id="a", observed_at=THEN), prices, Lens(as_of=THEN))

    # Only one version was knowable; too few bars for a trend, and crucially the
    # later revision was not silently used.
    assert result.asset_id == "a"
    assert result.trend is None


# --------------------------------------------------------------------------- #
# #46 — pattern discovery, and it says so
# --------------------------------------------------------------------------- #


def _outcome(asset: str, value: float, when: datetime = THEN) -> Outcome:
    return Outcome(episode=Episode(asset_id=asset, observed_at=when), returns={"24m": value})


def test_extremes_use_an_absolute_threshold_not_a_percentile():
    """A percentile finds its own top decile in any sample, however
    unremarkable that decile is."""
    modest = [_outcome(f"a{i}", 0.05 * i) for i in range(10)]

    assert find_extremes(modest) == []

    with_a_winner = [*modest, _outcome("winner", 4.0)]
    found = find_extremes(with_a_winner)
    assert [item.asset_id for item in found] == ["winner"]
    assert found[0].multiple == pytest.approx(5.0)


def test_a_configuration_with_no_process_context_says_what_is_missing():
    """The Process slots are present rather than omitted, so the shape of the
    answer is visible before #37 lands."""
    empty = Configuration()

    assert empty.has_process_context is False
    assert set(empty.missing) == {"archetype", "state", "process_features"}


def test_the_search_reports_that_it_is_not_a_configuration_search_yet():
    """Without the historical Process half this is a search over market
    configurations, which is a weaker question than §17 asks — stated rather
    than implied."""
    extremes = find_extremes([_outcome("w", 4.0)])
    result = search(
        extremes, [("p1", "Minerals", "commodity_supply_cycle", "supply_tightness", 8.0)]
    )

    assert result.extremes_found == 1
    # No historical configuration has an archetype, so nothing is comparable.
    assert result.matches[0].analog_strength == 0.0
    assert result.matches[0].based_on == 0
    reasons = dict(result.unavailable)
    assert "historical_process_context" in reasons
    assert "#37" in reasons["historical_process_context"]


def test_every_result_carries_a_human_review_flag():
    """Agent doc §23. A field rather than a UI convention, so a client cannot
    render the table without it."""
    result = search([], [("p1", "Minerals", "commodity_supply_cycle", "supply_tightness", 8.0)])

    assert all(item.requires_human_review for item in result.matches)


def test_each_row_carries_its_own_caveat():
    """A header is read on arrival and forgotten by the third row."""
    result = search([], [("p1", "Minerals", None, None, None)])

    caveat = result.matches[0].caveat()
    assert "not a forecast" in caveat
    assert "not a promise" in caveat
    assert "anecdote" in caveat  # fewer than MIN_EXAMPLES


def test_a_well_supported_pattern_drops_the_anecdote_warning():
    extremes = [
        find_extremes(
            [_outcome(f"w{i}", 4.0, THEN - timedelta(days=i))],
            configurations={
                f"w{i}@{(THEN - timedelta(days=i)).isoformat()}": Configuration(
                    archetype="commodity_supply_cycle", state="supply_tightness"
                )
            },
        )[0]
        for i in range(MIN_EXAMPLES)
    ]

    result = search(
        extremes,
        [("p1", "Minerals", "commodity_supply_cycle", "supply_tightness", 8.0)],
    )

    row = result.matches[0]
    assert row.based_on == MIN_EXAMPLES
    assert row.analog_strength > 0
    assert "anecdote" not in row.caveat()
    assert result.is_configuration_search is True
