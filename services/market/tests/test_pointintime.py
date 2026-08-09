"""Point-in-time enforcement and leakage detection (issue #39; agent doc §20)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from econiq_market import (
    LeakageError,
    Lens,
    assert_clean,
    inspect,
    lenses,
)

CUT = datetime(2026, 3, 15, tzinfo=UTC)


def _frame(rows: list[tuple[datetime, datetime, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "observed_at": [r[0] for r in rows],
            "recorded_at": [r[1] for r in rows],
            "adj_close": [r[2] for r in rows],
        }
    )


def test_a_cut_off_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        Lens(as_of=datetime(2026, 3, 15))


def test_a_view_excludes_days_after_the_cut_off():
    frame = _frame(
        [
            (datetime(2026, 3, 10, tzinfo=UTC), datetime(2026, 3, 10, tzinfo=UTC), 100.0),
            (datetime(2026, 3, 20, tzinfo=UTC), datetime(2026, 3, 20, tzinfo=UTC), 200.0),
        ]
    )

    assert Lens(CUT).view(frame).height == 1


def test_a_view_takes_the_version_known_then_not_the_newest():
    """The subtle failure §20 names: a row observed before the cut-off but
    *recorded* after it is the value as it looks today, not as it looked then."""
    day = datetime(2026, 3, 10, tzinfo=UTC)
    frame = _frame(
        [
            (day, datetime(2026, 3, 10, tzinfo=UTC), 100.0),
            # The same day, re-fetched after a split revised its adjustment.
            (day, datetime(2026, 4, 1, tzinfo=UTC), 50.0),
        ]
    )

    view = Lens(CUT).view(frame)

    assert view.height == 1
    assert view["adj_close"][0] == 100.0


def test_a_later_view_sees_the_revision():
    day = datetime(2026, 3, 10, tzinfo=UTC)
    frame = _frame(
        [
            (day, datetime(2026, 3, 10, tzinfo=UTC), 100.0),
            (day, datetime(2026, 4, 1, tzinfo=UTC), 50.0),
        ]
    )

    view = Lens(datetime(2026, 5, 1, tzinfo=UTC)).view(frame)

    assert view["adj_close"][0] == 50.0


def test_a_frame_missing_a_clock_cannot_be_viewed_at_all():
    """Guessing at the missing one is how a 'point-in-time' read stops being
    one."""
    frame = pl.DataFrame({"observed_at": [CUT], "adj_close": [100.0]})

    with pytest.raises(LeakageError, match="both clocks"):
        Lens(CUT).view(frame)


def test_a_lens_has_no_way_to_return_unfiltered_data():
    """Analysis written against a Lens cannot read the future by omission, only
    by deliberately reaching around it."""
    methods = {name for name in dir(Lens) if not name.startswith("_")}

    assert methods == {"as_of", "view", "check", "permits"}
    assert not any("raw" in name or "all" in name for name in methods)


def test_check_refuses_a_date_past_the_cut_off():
    """For the values a frame filter cannot cover — §20's list is longer than
    prices."""
    lens = Lens(CUT)

    lens.check(CUT - timedelta(days=1), what="document publication")
    with pytest.raises(LeakageError, match="after the cut-off"):
        lens.check(CUT + timedelta(days=1), what="document publication")


# --------------------------------------------------------------------------- #
# Detection — a check that has never fired is indistinguishable from a broken one
# --------------------------------------------------------------------------- #


def test_a_clean_frame_produces_no_findings():
    frame = _frame([(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC), 100.0)])

    assert inspect(frame, Lens(CUT)) == []
    assert_clean(frame, Lens(CUT))


def test_a_future_observation_is_detected():
    frame = _frame([(datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC), 100.0)])

    findings = inspect(frame, Lens(CUT))

    assert [f.kind for f in findings] == ["future_observation"]
    assert findings[0].rows == 1


def test_a_later_revision_is_detected_separately():
    """This is the one that makes a backtest look brilliant, and it is invisible
    to a naive 'no future dates' check — the observation date is in range."""
    frame = _frame([(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC), 50.0)])

    findings = inspect(frame, Lens(CUT))

    assert [f.kind for f in findings] == ["later_revision"]
    # The observation itself is inside the window, which is why a date check
    # alone would pass it.
    assert frame["observed_at"][0] < CUT


def test_a_frame_that_cannot_be_checked_says_so_rather_than_passing():
    frame = pl.DataFrame({"adj_close": [100.0]})

    findings = inspect(frame, Lens(CUT))

    assert [f.kind for f in findings] == ["missing_clock"]
    with pytest.raises(LeakageError):
        assert_clean(frame, Lens(CUT))


def test_walk_forward_lenses_are_built_before_the_walk_runs():
    """Every step bounded up front, for the same reason an Episode freezes its
    date at construction (#38)."""
    days = [CUT + timedelta(days=i) for i in range(3)]

    built = lenses(days)

    assert [lens.as_of for lens in built] == days
    assert all(isinstance(lens, Lens) for lens in built)
