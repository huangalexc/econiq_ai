"""Point-in-time enforcement (issue #39; agent doc §20).

§20 lists what a historical analysis at date `t` may read and what it may not,
and ends with the instruction that matters: *"this should be enforced
programmatically wherever possible."*

`as_known_at` in the warehouse already gives a correct point-in-time read. The
problem it does not solve is that using it is optional. Every leakage bug in a
backtest is somebody forgetting one filter in one place, and the result looks
like a good model rather than a broken one — which is why leakage survives code
review in a way that a crash never does.

So this module inverts the default. A :class:`Lens` holds the cut-off and hands
out frames that have already been filtered; there is no method on it that
returns unfiltered data. Analysis code written against a Lens cannot read the
future by omission, only by deliberately reaching around it.

**The two clocks, again.** `observed_at` bounds which days existed;
`recorded_at` bounds which *version* of each day is used. Dropping the second is
the subtle failure — it silently hands every past day the adjustment factors
that only exist after later splits and dividends, and §20 names exactly this:
"restated numbers unavailable at t".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import polars as pl

#: Columns a frame must carry to be readable through a Lens. A frame without
#: both clocks cannot be filtered correctly, and guessing at the missing one is
#: how a "point-in-time" read stops being one.
REQUIRED_COLUMNS = ("observed_at", "recorded_at")


class LeakageError(RuntimeError):
    """An attempt to read data the cut-off does not permit.

    Raised rather than filtered silently. A caller that asked for something
    outside its window has a bug in its reasoning, not in its data, and quietly
    returning less than asked for hides it.
    """


@dataclass(frozen=True, slots=True)
class Lens:
    """A view of the world as of one instant.

    Every read through a Lens is already filtered. There is deliberately no
    escape hatch on this class — code that genuinely needs the full history
    reads the warehouse directly, which is visible in review in a way that a
    `raw=True` argument is not.
    """

    as_of: datetime

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("a point-in-time cut-off must be timezone-aware")

    def view(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Rows knowable at the cut-off, one row per observation.

        Where a day was fetched several times — which happens whenever a
        corporate action revised it — the newest version *recorded before the
        cut-off* wins. Not the newest version, which is the whole point.
        """
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            raise LeakageError(
                f"frame lacks {missing}; a point-in-time read needs both clocks (agent doc §20)"
            )
        # Grouped per asset where the frame has one, so a multi-asset frame
        # does not collapse two tickers' bars for the same day into one row.
        keys = ["asset_id", "observed_at"] if "asset_id" in frame.columns else ["observed_at"]
        return (
            frame.filter(
                (pl.col("observed_at") <= self.as_of) & (pl.col("recorded_at") <= self.as_of)
            )
            .sort(["observed_at", "recorded_at"])
            .group_by(keys)
            .last()
            .sort("observed_at")
        )

    def check(self, moment: datetime, *, what: str) -> None:
        """Refuse a read that reaches past the cut-off.

        For the values a frame filter cannot cover — an episode's horizon end, a
        document's publication date, a State observation. §20's list is longer
        than "prices".
        """
        if moment > self.as_of:
            raise LeakageError(
                f"{what} is dated {moment.isoformat()}, after the cut-off {self.as_of.isoformat()}"
            )

    def permits(self, moment: datetime) -> bool:
        return moment <= self.as_of


@dataclass(frozen=True, slots=True)
class LeakageFinding:
    """One place a frame carried something the cut-off forbids."""

    kind: str
    detail: str
    rows: int

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail} ({self.rows} row(s))"


def inspect(frame: pl.DataFrame, lens: Lens) -> list[LeakageFinding]:
    """What in this frame the cut-off would have excluded.

    The counterpart to :meth:`Lens.view` — used to *measure* leakage in a frame
    somebody else assembled, rather than to prevent it. The fault-injection
    suite (#16) needs this: a check that has never fired is indistinguishable
    from one that is broken, and the only way to fire this one is to hand it a
    frame that leaks.
    """
    findings: list[LeakageFinding] = []
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        return [
            LeakageFinding(
                kind="missing_clock",
                detail=f"frame has no {missing}; it cannot be checked at all",
                rows=frame.height,
            )
        ]

    future_observations = frame.filter(pl.col("observed_at") > lens.as_of).height
    if future_observations:
        findings.append(
            LeakageFinding(
                kind="future_observation",
                detail=f"rows describing days after {lens.as_of.date()}",
                rows=future_observations,
            )
        )

    # The subtle one. A row observed before the cut-off but *recorded* after it
    # is a revision — the adjusted close as it looks today, not as it looked
    # then. §20: "restated numbers unavailable at t".
    revisions = frame.filter(
        (pl.col("observed_at") <= lens.as_of) & (pl.col("recorded_at") > lens.as_of)
    ).height
    if revisions:
        findings.append(
            LeakageFinding(
                kind="later_revision",
                detail=(
                    "rows for days within the window whose values were only learned afterwards"
                ),
                rows=revisions,
            )
        )

    return findings


def assert_clean(frame: pl.DataFrame, lens: Lens) -> None:
    """Raise on any leakage. For use at the boundary of an analysis."""
    findings = inspect(frame, lens)
    if findings:
        raise LeakageError("; ".join(str(finding) for finding in findings))


def lenses(moments: Sequence[datetime]) -> list[Lens]:
    """A Lens per observation date, for a walk-forward analysis.

    Built up front so every step of a backtest is bounded before any of it runs
    — the same reason an Episode freezes its date at construction (#38).
    """
    return [Lens(as_of=moment) for moment in moments]
