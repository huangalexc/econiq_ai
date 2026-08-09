"""Leakage faults for the historical path (issue #39)."""

from __future__ import annotations

from econiq_eval import leaks_missed, run_leak_injection
from econiq_eval.historical_faults import FAULTS


def test_every_injected_leak_is_caught_by_its_own_detector():
    """The argument from #16, applied where it matters most.

    Every other defect makes the output worse and is therefore visible. Leakage
    makes it *better* — a backtest reading tomorrow's adjustment factors looks
    excellent and nothing downstream complains.
    """
    results = run_leak_injection()

    assert results
    assert leaks_missed(results) == [], [r.detail for r in leaks_missed(results)]
    assert {r.fault for r in results} == {f.name for f in FAULTS}


def test_the_restated_adjustment_leak_would_pass_a_date_check():
    """§20 says the point-in-time boundary matters more than a 'no future dates'
    convention, and this is why: the observation is inside the window, and only
    the version of it comes from later."""
    from econiq_eval.historical_faults import CUT, restated_adjustment

    frame = restated_adjustment()

    assert frame["observed_at"][0] < CUT  # a date check passes
    assert frame["recorded_at"][0] > CUT  # the leak is in the other clock

    result = next(r for r in run_leak_injection() if r.fault == "restated_adjustment")
    assert result.detected is True


def test_a_detector_firing_for_the_wrong_reason_is_not_a_pass():
    """Matched on the expected finding, so a noisy detector cannot turn the
    benchmark green."""
    results = {r.fault: r for r in run_leak_injection()}

    assert results["future_price"].expected_kind == "future_observation"
    assert results["restated_adjustment"].expected_kind == "later_revision"
    assert results["unverifiable_frame"].expected_kind == "missing_clock"


def test_an_unverifiable_frame_does_not_pass_silently():
    """A frame that cannot be checked is not a frame that checked out."""
    result = next(r for r in run_leak_injection() if r.fault == "unverifiable_frame")

    assert result.detected is True
