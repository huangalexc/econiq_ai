"""Reproducible Asset metrics (issue #75, agent doc §8.3).

§8.3's instruction is blunt — *"do not manually calculate values in prose"* — and
its headline metric is reproducibility. So every number here is computed by code
from stored price rows. The agent's job is to select and interpret; it never
produces a figure.

**What Phase 1 can actually compute.** §8.3 lists nine analyses. Tiingo daily
gives prices and volume and nothing else, so:

=========================  ==================================================
§8.3 analysis              Status
=========================  ==================================================
relative strength          computed
volatility                 computed
technicals                 computed (trend, drawdown, momentum)
growth                     **absent** — needs a fundamentals source
margins                    **absent** — needs a fundamentals source
valuation                  **absent** — needs earnings and share count
balance sheet              **absent** — needs a fundamentals source
ownership / crowding       **absent** — needs holdings data
=========================  ==================================================

Five of nine are unavailable and are reported as such rather than estimated
from price action. A valuation inferred from a price chart is not a valuation,
and the Asset comparison matrix (#29) showing one would be worse than showing a
gap: the reader cannot tell a measured multiple from a guessed one once both
are rendered as a number.

Every metric carries the window it was computed over and the number of bars it
saw, because §8.3 also asks for data timestamps and missing data. A momentum
figure from eleven bars is not the same claim as one from two hundred.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

#: Trading days. Roughly one, three, six and twelve months.
WINDOWS: dict[str, int] = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}

#: Below this many bars a window is not computed at all. A "12-month return"
#: from thirty bars is a different statistic wearing the same label, and the
#: comparison matrix would rank it against real ones.
MIN_COVERAGE = 0.6

#: Quant analyses §8.3 asks for that no source in this deployment provides.
UNAVAILABLE: tuple[tuple[str, str], ...] = (
    ("growth", "Needs a fundamentals source; Tiingo daily is prices only (#77)."),
    ("margins", "Needs a fundamentals source."),
    ("valuation", "Needs earnings and share count. Never inferred from price."),
    ("balance_sheet", "Needs a fundamentals source."),
    ("ownership_crowding", "Needs holdings data. No source in the stack."),
)


@dataclass(frozen=True, slots=True)
class Bar:
    """One stored trading day, reduced to what the metrics need."""

    trade_date: date
    close: float
    adj_close: float | None = None
    volume: float | None = None

    @property
    def price(self) -> float:
        """The adjusted close where present.

        Adjusted, because a return series computed from raw closes reports a
        two-for-one split as a fifty percent loss. The raw close is kept in
        storage for point-in-time reasons (#77); analysis wants the adjusted one.
        """
        return self.adj_close if self.adj_close is not None else self.close


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    value: float
    unit: str
    window_days: int | None = None
    bars: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": round(self.value, 6),
            "unit": self.unit,
            "window_days": self.window_days,
            "bars": self.bars,
        }


@dataclass(frozen=True, slots=True)
class MetricSet:
    """Everything computable for one Asset, with what was missing."""

    metrics: dict[str, Metric] = field(default_factory=dict)
    bars: int = 0
    first_date: date | None = None
    last_date: date | None = None
    missing: tuple[str, ...] = ()

    def get(self, name: str) -> float | None:
        metric = self.metrics.get(name)
        return metric.value if metric is not None else None

    def as_inputs(self) -> dict[str, float]:
        """Flat form for a scorecard dimension's `inputs` (#25)."""
        return {name: round(metric.value, 6) for name, metric in self.metrics.items()}


def compute(bars: Sequence[Bar]) -> MetricSet:
    """Metrics from a price history, oldest first."""
    ordered = sorted(bars, key=lambda bar: bar.trade_date)
    if len(ordered) < 2:
        return MetricSet(
            bars=len(ordered),
            first_date=ordered[0].trade_date if ordered else None,
            last_date=ordered[-1].trade_date if ordered else None,
            missing=(*(name for name, _ in UNAVAILABLE), "insufficient_history"),
        )

    prices = [bar.price for bar in ordered]
    metrics: dict[str, Metric] = {}

    for label, span in WINDOWS.items():
        if len(prices) < span * MIN_COVERAGE:
            continue
        window = prices[-span:]
        start, end = window[0], window[-1]
        if start > 0:
            metrics[f"return_{label}"] = Metric(
                name=f"return_{label}",
                value=(end / start) - 1.0,
                unit="ratio",
                window_days=span,
                bars=len(window),
            )

    returns = _daily_returns(prices)
    if len(returns) >= 20:
        metrics["volatility_annualised"] = Metric(
            name="volatility_annualised",
            # 252 trading days. Annualised so it is comparable across Assets,
            # which is the only reason this number exists.
            value=_stdev(returns) * math.sqrt(252),
            unit="ratio",
            bars=len(returns),
        )

    metrics["max_drawdown"] = Metric(
        name="max_drawdown",
        value=_max_drawdown(prices),
        unit="ratio",
        bars=len(prices),
    )

    if len(prices) >= 200:
        average = sum(prices[-200:]) / 200
        if average > 0:
            metrics["price_to_200d"] = Metric(
                name="price_to_200d",
                value=prices[-1] / average,
                unit="ratio",
                window_days=200,
                bars=200,
            )

    volumes = [bar.volume for bar in ordered if bar.volume is not None]
    if len(volumes) >= 40:
        recent = sum(volumes[-20:]) / 20
        prior = sum(volumes[-40:-20]) / 20
        if prior > 0:
            metrics["volume_trend"] = Metric(
                name="volume_trend",
                value=recent / prior,
                unit="ratio",
                window_days=20,
                bars=40,
            )

    missing = [name for name, _ in UNAVAILABLE]
    missing += [f"return_{label}" for label in WINDOWS if f"return_{label}" not in metrics]
    return MetricSet(
        metrics=metrics,
        bars=len(ordered),
        first_date=ordered[0].trade_date,
        last_date=ordered[-1].trade_date,
        missing=tuple(missing),
    )


def relative_strength(
    subject: MetricSet, peers: Sequence[MetricSet], *, window: str = "6m"
) -> Metric | None:
    """Where this Asset's return sits among its peers, 0–1.

    A percentile rather than a ratio to a benchmark, because the comparison
    §8.3 asks for is between Assets expressing one Capability — the peer set
    *is* the benchmark, and there is no index for "companies exposed to heavy
    rare-earth separation".
    """
    key = f"return_{window}"
    own = subject.get(key)
    if own is None:
        return None
    others = [peer.get(key) for peer in peers]
    values = [value for value in others if value is not None]
    if len(values) < 2:
        # A percentile against one other name is not a percentile.
        return None
    below = sum(1 for value in values if value < own)
    return Metric(
        name="relative_strength",
        value=below / len(values),
        unit="percentile",
        window_days=WINDOWS[window],
        bars=len(values),
    )


def technical_confirmation(metrics: MetricSet) -> tuple[float, dict[str, float]] | None:
    """A 0–10 technical score, computed rather than judged.

    Deliberately shallow: trend, drawdown and momentum. Technical confirmation
    in ontology §17 asks whether the market is behaving consistently with the
    thesis, not whether the chart predicts anything — and a richer indicator set
    would imply a predictive claim this system does not make.
    """
    trend = metrics.get("price_to_200d")
    drawdown = metrics.get("max_drawdown")
    momentum = metrics.get("return_6m")
    if trend is None and momentum is None:
        return None

    parts: dict[str, float] = {}
    score = 0.0
    weight = 0.0

    if trend is not None:
        # 1.0 is at the 200-day average; 1.2 and above saturates.
        component = min(max((trend - 0.9) / 0.3, 0.0), 1.0)
        parts["price_to_200d"] = round(trend, 4)
        score += component * 0.4
        weight += 0.4
    if momentum is not None:
        component = min(max((momentum + 0.2) / 0.6, 0.0), 1.0)
        parts["return_6m"] = round(momentum, 4)
        score += component * 0.4
        weight += 0.4
    if drawdown is not None:
        # Drawdown is negative; a shallower one scores better.
        component = min(max(1.0 + drawdown / 0.5, 0.0), 1.0)
        parts["max_drawdown"] = round(drawdown, 4)
        score += component * 0.2
        weight += 0.2

    if weight == 0.0:
        return None
    return round(10.0 * score / weight, 2), parts


def _daily_returns(prices: Sequence[float]) -> list[float]:
    return [(prices[i] / prices[i - 1]) - 1.0 for i in range(1, len(prices)) if prices[i - 1] > 0]


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _max_drawdown(prices: Sequence[float]) -> float:
    """Largest peak-to-trough fall, as a negative ratio."""
    peak = prices[0]
    worst = 0.0
    for price in prices:
        peak = max(peak, price)
        if peak > 0:
            worst = min(worst, (price / peak) - 1.0)
    return worst
