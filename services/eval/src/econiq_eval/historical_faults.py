"""Leakage faults for the historical path (issue #39; agent doc §19, §20).

The fault-injection suite in :mod:`econiq_eval.faults` proves the *ontology*
audits fire. This does the same for the historical engine, and the argument is
identical: a leakage check nobody has ever seen fire is a comment.

It matters more here than anywhere else in the system. Every other defect makes
the output worse and therefore visible. Leakage makes it *better* — a backtest
reading tomorrow's adjustment factors produces a strategy that looks excellent,
and nothing downstream complains. §20 says the point-in-time boundary matters
more than a "no future dates" convention precisely because the dangerous case
passes a date check: the observation is inside the window; only the *version* of
it comes from later.

These faults are frames rather than database rows, so they need no rollback —
the injected leak exists only for the length of the assertion.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import polars as pl
from econiq_market import Lens, inspect

CUT = datetime(2026, 3, 15, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class LeakFault:
    """A frame built to leak, and the finding that should catch it."""

    name: str
    description: str
    build: Callable[[], pl.DataFrame]
    expected_kind: str


@dataclass(frozen=True, slots=True)
class LeakResult:
    fault: str
    detected: bool
    expected_kind: str
    found: tuple[str, ...] = ()

    @property
    def detail(self) -> str:
        if self.detected:
            return f"caught by {self.expected_kind}"
        return f"NOT CAUGHT — {self.expected_kind} did not fire (found {self.found or 'nothing'})"


def _frame(rows: list[tuple[datetime, datetime, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "observed_at": [row[0] for row in rows],
            "recorded_at": [row[1] for row in rows],
            "adj_close": [row[2] for row in rows],
        }
    )


def future_price() -> pl.DataFrame:
    """A bar from after the cut-off. The obvious leak, and the rare one."""
    day = CUT + timedelta(days=10)
    return _frame([(day, day, 120.0)])


def restated_adjustment() -> pl.DataFrame:
    """§20's "restated numbers unavailable at t" — the dangerous case.

    The observation date is inside the window, so a date check passes it. Only
    the recording date betrays that this is the adjusted close as it looks after
    a later split, which is a number nobody had at the time.
    """
    day = CUT - timedelta(days=20)
    return _frame([(day, CUT + timedelta(days=30), 50.0)])


def missing_clock() -> pl.DataFrame:
    """A frame with one clock. Cannot be checked, so it must not pass silently."""
    return pl.DataFrame({"observed_at": [CUT - timedelta(days=1)], "adj_close": [100.0]})


FAULTS: tuple[LeakFault, ...] = (
    LeakFault(
        name="future_price",
        description="A price bar dated after the point-in-time cut-off",
        build=future_price,
        expected_kind="future_observation",
    ),
    LeakFault(
        name="restated_adjustment",
        description=(
            "A bar inside the window carrying an adjustment only learned later — "
            "passes a date check, and is the leak that flatters a backtest"
        ),
        build=restated_adjustment,
        expected_kind="later_revision",
    ),
    LeakFault(
        name="unverifiable_frame",
        description="A frame missing recorded_at, which cannot be checked at all",
        build=missing_clock,
        expected_kind="missing_clock",
    ),
)


def run(*, cut: datetime = CUT) -> list[LeakResult]:
    """Inject each leak and assert its own detector fires.

    Matched on the *expected* finding rather than on "any finding", for the same
    reason the ontology suite does: a detector firing for the wrong reason would
    make the benchmark agree with a broken system.
    """
    lens = Lens(as_of=cut)
    results: list[LeakResult] = []
    for fault in FAULTS:
        findings = inspect(fault.build(), lens)
        kinds = tuple(finding.kind for finding in findings)
        results.append(
            LeakResult(
                fault=fault.name,
                detected=fault.expected_kind in kinds,
                expected_kind=fault.expected_kind,
                found=kinds,
            )
        )
    return results


def missed(results: list[LeakResult]) -> list[LeakResult]:
    return [result for result in results if not result.detected]
