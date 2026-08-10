"""Historical Asset matching (issue #43; agent doc §9.3; ontology §32).

The question is *"what did assets look like at the equivalent historical Process
State?"* — never *"which companies became winners"*. §9.3 states the rule
plainly: **do not use eventual success as a matching criterion.**

That rule is easy to agree with and easy to violate by accident, because the
outcome is right there in the same dataset. A matcher that takes an episode and
has access to its outcome will eventually use it — through a feature derived
from a later price, through a filter that drops the ones that went nowhere,
through a threshold tuned until the matches look good. None of those feel like
cheating while you are doing them.

**So the matcher cannot see outcomes.** :class:`AssetFeatures` has no field that
could hold one, :func:`match` accepts only features, and outcomes are joined
afterwards by :func:`attach_outcomes`, which takes matches that already exist.
There is no ordering of these calls that lets a similarity score depend on what
happened next.

**What can actually be matched.** §9.3 lists ten dimensions. Price history
supports three of them; the rest need fundamentals, capability mappings or a
market-regime series that this deployment does not have. They are declared, not
imputed — a similarity score computed over three dimensions and presented as if
it covered ten is a worse artefact than a thin one that says so.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from econiq_market.outcomes import Episode, Outcome
from econiq_market.pointintime import Lens

#: §9.3's dimensions, and whether this deployment can compute them.
DIMENSIONS: dict[str, bool] = {
    "technical_state": True,
    "volatility_regime": True,
    "drawdown_state": True,
    "capability": False,
    "exposure": False,
    "market_share": False,
    "growth": False,
    "valuation": False,
    "operating_leverage": False,
    "balance_sheet": False,
    "competitive_position": False,
    "market_regime": False,
}

UNAVAILABLE_REASONS: dict[str, str] = {
    "capability": "Needs the historical Capability snapshots of #37.",
    "exposure": "Needs historical exposure records; the current graph has them, history does not.",
    "market_share": "Needs a fundamentals source (#75, #77).",
    "growth": "Needs a fundamentals source.",
    "valuation": "Needs earnings and share count. Never inferred from price.",
    "operating_leverage": "Needs a fundamentals source.",
    "balance_sheet": "Needs a fundamentals source.",
    "competitive_position": "A judgement the Asset Quality agent makes for current "
    "Assets (#76); no historical equivalent exists.",
    "market_regime": "Needs a macro series. FRED would serve it.",
}

#: Below this many computable dimensions a similarity number is not worth
#: producing. Three price-derived features can say two Assets behaved alike;
#: they cannot say the businesses resembled each other, and a score presented
#: without that caveat will be read as the second thing.
MIN_DIMENSIONS = 3


@dataclass(frozen=True, slots=True)
class AssetFeatures:
    """One Asset as it looked at one moment, and nothing about what followed.

    Deliberately outcome-free. There is no `return`, no `succeeded`, no
    `outperformed` — not because a caller would obviously misuse them, but
    because a field that exists gets used, and §9.3's rule is the one thing this
    module cannot afford to violate quietly.

    Every field here is derived from prices at or before ``observed_at``.
    """

    asset_id: str
    observed_at: datetime
    #: Price relative to its own trailing average. Where in its own history the
    #: Asset was standing, not where it went.
    trend: float | None = None
    #: Annualised, from the trailing window only.
    volatility: float | None = None
    #: How far below its own prior peak it was sitting.
    drawdown: float | None = None
    #: What the Asset was an expression of, where known. Carried for grouping,
    #: never as a similarity input — matching on a label rather than on
    #: behaviour would make every Asset in one Capability look alike.
    capability: str | None = None

    @property
    def computable(self) -> tuple[str, ...]:
        present = []
        if self.trend is not None:
            present.append("technical_state")
        if self.volatility is not None:
            present.append("volatility_regime")
        if self.drawdown is not None:
            present.append("drawdown_state")
        return tuple(present)


@dataclass(frozen=True, slots=True)
class Match:
    """One historical Asset that resembled the subject, and on what.

    ``similarity`` is over the dimensions both sides could compute, and
    ``dimensions`` says which those were. A score of 0.9 over three dimensions
    and one over ten are different claims, and the reader needs both numbers to
    tell them apart.
    """

    subject: AssetFeatures
    candidate: AssetFeatures
    similarity: float
    dimensions: tuple[str, ...]
    per_dimension: dict[str, float] = field(default_factory=dict)

    @property
    def is_thin(self) -> bool:
        return len(self.dimensions) < MIN_DIMENSIONS


@dataclass(frozen=True, slots=True)
class MatchedOutcome:
    """A match, with what happened to the candidate — joined after matching.

    A separate type from :class:`Match` on purpose. The existence of two types
    is what makes it visible in review that outcomes arrived late, and makes it
    impossible for a function that computes similarity to have been handed one.
    """

    match: Match
    outcome: Outcome


def features_from(
    episode: Episode,
    prices: object,
    lens: Lens,
) -> AssetFeatures:
    """Point-in-time features for one episode.

    Reads through the Lens, so the features cannot include a bar the episode's
    date does not permit — including a *revision* of an in-window bar that was
    only recorded later (#39).
    """
    import polars as pl

    frame = lens.view(prices)  # type: ignore[arg-type]
    series = (
        frame.sort("observed_at").drop_nulls("adj_close")["adj_close"].to_list()
        if isinstance(frame, pl.DataFrame)
        else []
    )
    if len(series) < 2:
        return AssetFeatures(
            asset_id=episode.asset_id,
            observed_at=episode.observed_at,
            capability=episode.label,
        )

    window = series[-200:]
    average = sum(window) / len(window)
    peak = max(window)
    returns = [
        (series[i] / series[i - 1]) - 1.0 for i in range(1, len(series)) if series[i - 1] > 0
    ]

    return AssetFeatures(
        asset_id=episode.asset_id,
        observed_at=episode.observed_at,
        trend=series[-1] / average if average > 0 else None,
        volatility=_stdev(returns) * math.sqrt(252) if len(returns) >= 20 else None,
        drawdown=(series[-1] / peak) - 1.0 if peak > 0 else None,
        capability=episode.label,
    )


def match(
    subject: AssetFeatures,
    candidates: Sequence[AssetFeatures],
    *,
    limit: int = 10,
    same_capability_only: bool = False,
) -> list[Match]:
    """Historical Assets that resembled the subject at their own observation.

    Takes features only. There is no parameter through which an outcome could
    reach this function, which is the enforcement of §9.3's rule rather than a
    promise about it.

    Candidates observed at or after the subject are excluded: a "historical"
    analogue from the future is not one, and the subject's own episode would
    otherwise match itself perfectly.
    """
    usable = [
        candidate
        for candidate in candidates
        if candidate.observed_at < subject.observed_at
        and candidate.asset_id != subject.asset_id
        and (not same_capability_only or candidate.capability == subject.capability)
    ]

    scored: list[Match] = []
    for candidate in usable:
        shared = tuple(
            dimension for dimension in subject.computable if dimension in candidate.computable
        )
        if not shared:
            continue
        per_dimension = {
            dimension: _closeness(
                getattr(subject, _FIELD[dimension]),
                getattr(candidate, _FIELD[dimension]),
                scale=_SCALE[dimension],
            )
            for dimension in shared
        }
        scored.append(
            Match(
                subject=subject,
                candidate=candidate,
                similarity=sum(per_dimension.values()) / len(per_dimension),
                dimensions=shared,
                per_dimension=per_dimension,
            )
        )

    scored.sort(key=lambda item: item.similarity, reverse=True)
    return scored[:limit]


def attach_outcomes(matches: Sequence[Match], outcomes: dict[str, Outcome]) -> list[MatchedOutcome]:
    """Join what happened, after the matching is finished.

    Keyed by asset id and observation, so an outcome cannot be attached to a
    match it does not belong to. Matches with no recorded outcome are dropped
    here rather than carried with a null — a match whose outcome is unknown is
    not evidence about outcomes, and keeping it would let it be counted in a
    distribution as if it were.
    """
    joined: list[MatchedOutcome] = []
    for item in matches:
        key = _key(item.candidate.asset_id, item.candidate.observed_at)
        outcome = outcomes.get(key)
        if outcome is not None:
            joined.append(MatchedOutcome(match=item, outcome=outcome))
    return joined


def outcome_index(outcomes: Sequence[Outcome]) -> dict[str, Outcome]:
    return {_key(o.episode.asset_id, o.episode.observed_at): o for o in outcomes}


def coverage_note() -> list[tuple[str, str]]:
    """The §9.3 dimensions this deployment cannot match on, with reasons."""
    return [
        (name, UNAVAILABLE_REASONS[name]) for name, available in DIMENSIONS.items() if not available
    ]


_FIELD = {
    "technical_state": "trend",
    "volatility_regime": "volatility",
    "drawdown_state": "drawdown",
}

#: How much difference makes two values dissimilar, per dimension. A 20% gap in
#: trend is a lot; a 20-point gap in annualised volatility is ordinary.
_SCALE = {
    "technical_state": 0.25,
    "volatility_regime": 0.35,
    "drawdown_state": 0.30,
}


def _closeness(left: float | None, right: float | None, *, scale: float) -> float:
    if left is None or right is None:
        return 0.0
    # Exponential decay rather than a linear one, so a near-identical pair scores
    # distinctly higher than a merely similar one instead of both landing near 1.
    return math.exp(-abs(left - right) / scale)


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _key(asset_id: str, observed_at: datetime) -> str:
    return f"{asset_id}@{observed_at.isoformat()}"
