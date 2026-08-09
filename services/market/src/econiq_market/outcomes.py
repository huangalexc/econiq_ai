"""The historical outcome engine (issue #38; agent doc §9.4).

Deterministic by requirement. §9.4 says so in one line and the reason is that
everything downstream — analog retrieval, forward-return distributions, the
eventual calibration work — is only meaningful if the same episode computes to
the same numbers every time. No model touches anything here.

**The observation date is frozen before any outcome is computed.** §9.4 calls
this the critical rule and it is enforced structurally rather than by
convention: an :class:`Episode` is constructed with its observation date, and
the outcome functions take an episode. There is no call that accepts a date and
a horizon together, because that is the shape that lets somebody slide the date
until the numbers improve — which is not fraud, it is what anybody does when the
first answer looks wrong and the interface makes retrying free.

**The asymmetry between features and outcomes.** Features at the observation
date must use only what was knowable then (agent doc §20), and
:func:`econiq_market.warehouse.as_known_at` enforces that. Outcomes are
deliberately the opposite: they are what happened *after*, so they read the best
available data. Confusing the two in either direction is the failure mode —
using later data for features is leakage, and using only-then-known data for
outcomes means measuring the future with a stale ruler.

Adjusted prices throughout. A return series computed from raw closes reports a
two-for-one split as a fifty percent loss, and §9.4's metric list includes
corporate-action adjustment accuracy for exactly that reason.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import polars as pl

#: The horizons ontology §36 standardises on. Trading days rather than calendar
#: months so a horizon is the same amount of market whichever month it starts in.
HORIZONS: dict[str, int] = {"1m": 21, "3m": 63, "6m": 126, "12m": 252, "24m": 504}

#: A horizon needs most of its bars to mean anything. Below this the window is
#: reported as unavailable rather than computed from what happened to be there —
#: a "12-month return" from four months of data is a different statistic wearing
#: the same label.
MIN_COVERAGE = 0.8


@dataclass(frozen=True, slots=True)
class Episode:
    """One Asset observed at one instant.

    Immutable, and the observation date is set at construction. That is the
    enforcement of §9.4's critical rule: nothing in this module accepts a date
    alongside a horizon, so an observation date cannot be adjusted after seeing
    the outcome it produces.
    """

    asset_id: str
    observed_at: datetime
    #: What the episode is an example *of* — a Process State, usually. Carried
    #: so a distribution can say what its members had in common, which is the
    #: difference between "comparable situations" and "some things that happened".
    label: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observation dates must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Outcome:
    """What happened after an episode. Everything §9.4 lists that prices support."""

    episode: Episode
    returns: dict[str, float] = field(default_factory=dict)
    max_drawdown: float | None = None
    max_upside: float | None = None
    volatility: float | None = None
    benchmark_relative: dict[str, float] = field(default_factory=dict)
    bars_after: int = 0
    #: Horizons that had too little data. Named rather than absent, so an
    #: aggregate can say how many of its members could answer.
    unavailable: tuple[str, ...] = ()

    @property
    def censored(self) -> bool:
        """True where the episode is too recent for its longest horizon.

        Censoring is not missingness. An episode from eight months ago has no
        12-month return *yet*, and dropping it silently biases a distribution
        toward older episodes — which are systematically different, because they
        are the ones that already resolved.
        """
        return bool(self.unavailable)


def compute(
    episode: Episode,
    prices: pl.DataFrame,
    *,
    benchmark: pl.DataFrame | None = None,
) -> Outcome:
    """Outcomes for one episode.

    ``prices`` is the full history for the Asset — columns ``observed_at`` and
    ``adj_close``. Rows at or before the observation are ignored: the outcome is
    what happened after, and including the observation bar itself would put a
    zero-return day at the start of every window.
    """
    after = _after(prices, episode.observed_at)
    base = _price_at(prices, episode.observed_at)
    if base is None or after.is_empty():
        return Outcome(
            episode=episode,
            unavailable=tuple(HORIZONS),
            bars_after=after.height,
        )

    series = after["adj_close"].to_list()
    returns: dict[str, float] = {}
    unavailable: list[str] = []
    for name, span in HORIZONS.items():
        if len(series) < span * MIN_COVERAGE:
            unavailable.append(name)
            continue
        end = series[min(span, len(series)) - 1]
        returns[name] = (end / base) - 1.0

    relative: dict[str, float] = {}
    if benchmark is not None:
        benchmark_after = _after(benchmark, episode.observed_at)
        benchmark_base = _price_at(benchmark, episode.observed_at)
        if benchmark_base is not None and not benchmark_after.is_empty():
            marks = benchmark_after["adj_close"].to_list()
            for name, span in HORIZONS.items():
                if name not in returns or len(marks) < span * MIN_COVERAGE:
                    continue
                mark = marks[min(span, len(marks)) - 1]
                # Arithmetic difference, not a ratio. §9.4 asks for
                # benchmark-relative return, and the reader compares these
                # against the absolute figures beside them.
                relative[name] = returns[name] - ((mark / benchmark_base) - 1.0)

    return Outcome(
        episode=episode,
        returns=returns,
        max_drawdown=_max_drawdown(series),
        max_upside=_max_upside(series, base),
        volatility=_volatility(series),
        benchmark_relative=relative,
        bars_after=len(series),
        unavailable=tuple(unavailable),
    )


def _after(prices: pl.DataFrame, moment: datetime) -> pl.DataFrame:
    return prices.filter(pl.col("observed_at") > moment).sort("observed_at").drop_nulls("adj_close")


def _price_at(prices: pl.DataFrame, moment: datetime) -> float | None:
    """The last close at or before the observation — the base every return uses.

    At or before, not the nearest: a market closed on the observation date makes
    the previous close the right base, and reaching forward for the next one
    would take a price from after the moment being observed.
    """
    at = prices.filter(pl.col("observed_at") <= moment).drop_nulls("adj_close").sort("observed_at")
    if at.is_empty():
        return None
    value = at["adj_close"][-1]
    return float(value) if value is not None and value > 0 else None


def _max_drawdown(series: Sequence[float]) -> float | None:
    if len(series) < 2:
        return None
    peak = series[0]
    worst = 0.0
    for price in series:
        peak = max(peak, price)
        if peak > 0:
            worst = min(worst, (price / peak) - 1.0)
    return worst


def _max_upside(series: Sequence[float], base: float) -> float | None:
    """The best return available at any point, not just at the horizon.

    Worth keeping separate from the horizon returns: a thesis that was right for
    six months and gave it all back is a different outcome from one that never
    worked, and a 12-month return alone cannot tell them apart.
    """
    if not series or base <= 0:
        return None
    return (max(series) / base) - 1.0


def _volatility(series: Sequence[float]) -> float | None:
    if len(series) < 21:
        return None
    returns = [
        (series[i] / series[i - 1]) - 1.0 for i in range(1, len(series)) if series[i - 1] > 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def frozen_before(episode: Episode, computed_at: datetime | None = None) -> bool:
    """Whether an episode's observation precedes the moment it was computed.

    §9.4's critical rule, checkable. An episode observed *after* the run that
    computed it is not an observation, it is a selection — and the fault
    injection suite (#16) should be able to assert this fires.
    """
    return episode.observed_at < (computed_at or datetime.now(UTC))


def episodes_from(
    asset_id: str,
    dates: Sequence[date],
    *,
    label: str | None = None,
) -> list[Episode]:
    """Build episodes from observation dates, frozen at construction."""
    return [
        Episode(
            asset_id=asset_id,
            observed_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            label=label,
        )
        for day in dates
    ]


def window_end(observed_at: datetime, horizon: str) -> datetime:
    """When a horizon closes, in calendar terms. For display only.

    The returns above are computed in trading days; this is the approximate
    calendar date a reader would recognise, and it is deliberately not used in
    any calculation.
    """
    return observed_at + timedelta(days=round(HORIZONS[horizon] * 365 / 252))
