"""The outcome engine (#38) and forward-return analysis (#44)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from econiq_market import (
    HORIZONS,
    INDICATIVE_BELOW,
    Episode,
    Outcome,
    across_horizons,
    compute,
    dispersion,
    frozen_before,
    summarise,
)
from econiq_market.distribution import Distribution

START = datetime(2024, 1, 1, tzinfo=UTC)


def _prices(values: list[float], *, start: datetime = START) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "observed_at": [start + timedelta(days=i) for i in range(len(values))],
            "adj_close": values,
        }
    )


def _episode(day: int = 0, label: str | None = "supply_tightness") -> Episode:
    return Episode(asset_id="a1", observed_at=START + timedelta(days=day), label=label)


# --------------------------------------------------------------------------- #
# #38 — deterministic, and frozen before computation
# --------------------------------------------------------------------------- #


def test_an_episode_must_carry_a_timezone():
    """A naive observation date silently means 'local', and a historical engine
    that mixes timezones compares episodes that did not happen together."""
    with pytest.raises(ValueError, match="timezone-aware"):
        Episode(asset_id="a1", observed_at=datetime(2024, 1, 1))


def test_the_same_episode_computes_to_the_same_numbers():
    """§9.4: deterministic. Everything downstream depends on it."""
    prices = _prices([100.0 + i for i in range(300)])

    first = compute(_episode(), prices)
    second = compute(_episode(), prices)

    assert first.returns == second.returns
    assert first.max_drawdown == second.max_drawdown


def test_returns_are_measured_from_the_close_at_or_before_the_observation():
    """Reaching forward for the next close would take a price from after the
    moment being observed."""
    prices = _prices([100.0] * 5 + [110.0] * 300)

    outcome = compute(_episode(day=2), prices)

    # Base is 100 (the observation-day close), not 110.
    assert outcome.returns["1m"] == pytest.approx(0.10)


def test_the_observation_bar_itself_is_not_part_of_the_forward_window():
    """Including it would put a zero-return day at the start of every window."""
    prices = _prices([100.0] + [200.0] * 300)

    outcome = compute(_episode(day=0), prices)

    assert outcome.returns["1m"] == pytest.approx(1.0)


def test_a_horizon_with_too_little_history_is_censored_not_computed():
    """A '12-month return' from four months is a different statistic wearing the
    same label."""
    prices = _prices([100.0 + i for i in range(60)])

    outcome = compute(_episode(), prices)

    assert "1m" in outcome.returns
    assert "12m" not in outcome.returns
    assert "12m" in outcome.unavailable
    assert outcome.censored is True


def test_max_upside_is_kept_apart_from_the_horizon_return():
    """A thesis that was right for six months and gave it all back is a
    different outcome from one that never worked, and a 12-month return alone
    cannot tell them apart."""
    prices = _prices([100.0] + [200.0] * 100 + [100.0] * 200)

    outcome = compute(_episode(), prices)

    assert outcome.returns["12m"] == pytest.approx(0.0, abs=1e-9)
    assert outcome.max_upside == pytest.approx(1.0)
    assert outcome.max_drawdown == pytest.approx(-0.5)


def test_benchmark_relative_is_a_difference_not_a_ratio():
    prices = _prices([100.0] + [120.0] * 300)
    benchmark = _prices([100.0] + [110.0] * 300)

    outcome = compute(_episode(), prices, benchmark=benchmark)

    assert outcome.returns["1m"] == pytest.approx(0.20)
    assert outcome.benchmark_relative["1m"] == pytest.approx(0.10)


def test_an_episode_observed_after_the_run_is_a_selection_not_an_observation():
    """§9.4's critical rule, made checkable."""
    future = Episode(asset_id="a1", observed_at=datetime(2030, 1, 1, tzinfo=UTC))

    assert frozen_before(future, datetime(2026, 1, 1, tzinfo=UTC)) is False
    assert frozen_before(_episode(), datetime(2026, 1, 1, tzinfo=UTC)) is True


def test_an_asset_with_no_history_after_the_observation_returns_nothing():
    outcome = compute(_episode(day=400), _prices([100.0] * 10))

    assert outcome.returns == {}
    assert set(outcome.unavailable) == set(HORIZONS)


# --------------------------------------------------------------------------- #
# #44 — empirical, never probabilistic
# --------------------------------------------------------------------------- #


def _outcome(value: float, horizon: str = "12m") -> Outcome:
    return Outcome(episode=_episode(), returns={horizon: value})


def test_the_distribution_has_no_probability_field():
    """Ontology §35: 'there is an 84% probability' requires calibration that has
    not been done. The type is shaped so that reading is hard to reach for."""
    fields = set(Distribution.__dataclass_fields__)

    assert "probability" not in fields
    assert "expected_return" not in fields
    assert "share_positive" in fields


def test_the_sentence_is_about_what_happened_not_what_will():
    result = summarise(
        [_outcome(v) for v in (0.1, 0.2, 0.3)], horizon="12m", basis="supply tightness"
    )

    sentence = result.describe()
    assert sentence.startswith("Among 3 historically comparable situations")
    assert "the subsequent 12m return was" in sentence
    assert "probability" not in sentence.lower()
    assert "will" not in sentence.lower()


def test_a_small_sample_says_so_in_its_own_sentence():
    """A percentile from three episodes is mostly noise, and the reader should
    not have to check the sample size to learn that."""
    result = summarise([_outcome(0.1)], horizon="12m", basis="…")

    assert result.is_indicative is True
    assert "not a rate" in result.describe()
    assert f"{INDICATIVE_BELOW}" in result.describe()


def test_censored_episodes_are_counted_rather_than_dropped():
    """Excluding them biases the distribution toward episodes that already
    resolved, which are systematically the older ones."""
    resolved = [_outcome(0.1), _outcome(0.2)]
    open_still = [Outcome(episode=_episode(), unavailable=("12m",))]

    result = summarise(resolved + open_still, horizon="12m", basis="…")

    assert result.sample_size == 2
    assert result.censored == 1
    assert result.coverage == pytest.approx(2 / 3)
    assert "have not yet resolved" in result.describe()


def test_a_horizon_nothing_has_reached_is_reported_rather_than_omitted():
    """A missing key and a horizon nothing has reached look identical to a
    caller, and only one of them means 'wait'."""
    result = across_horizons([_outcome(0.1, "1m")], basis="…")

    assert set(result) == set(HORIZONS)
    assert result["24m"].sample_size == 0
    assert "No comparable situation" in result["24m"].describe()


def test_dispersion_flags_analogues_that_disagreed():
    """Six episodes at +8% and six split between +60% and −40% have similar
    medians and are entirely different findings."""
    tight = summarise([_outcome(v) for v in (0.07, 0.08, 0.09)], horizon="12m", basis="…")
    wide = summarise([_outcome(v) for v in (-0.4, 0.08, 0.6)], horizon="12m", basis="…")

    assert dispersion(tight).agreement == "narrow"
    assert dispersion(wide).worth_flagging is True


def test_a_single_episode_still_produces_a_distribution():
    """With its sample size attached, which is what stops it being mistaken for
    a rate."""
    result = summarise([_outcome(0.15)], horizon="12m", basis="…")

    assert result.sample_size == 1
    assert result.percentiles["p50"] == pytest.approx(0.15)
    assert result.is_indicative is True


def test_an_unknown_horizon_is_refused():
    with pytest.raises(ValueError, match="unknown horizon"):
        summarise([], horizon="18m", basis="…")


def test_the_basis_travels_with_the_distribution():
    """A distribution whose basis cannot be stated is not a comparison, it is a
    pile of numbers."""
    result = summarise([_outcome(0.1)], horizon="12m", basis="commodity supply tightness")

    assert result.basis == "commodity supply tightness"
    assert "commodity supply tightness" in result.describe()
