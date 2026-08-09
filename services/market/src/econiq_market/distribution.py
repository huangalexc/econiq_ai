"""Forward-return analysis (issue #44; ontology §35, §36).

What happened, among historically comparable situations. Not what will happen.

Ontology §35 is unusually specific about the wording, and the distinction it
draws is the entire point of this module:

    "Among historically comparable situations, the subsequent 12-month return
    distribution was…"

rather than

    "There is an 84% probability the asset will rise."

The second requires calibration and statistical validation that has not been
done. So this module produces *empirical* summaries — percentiles of what
actually occurred in a named set of episodes — and the types are shaped so the
probabilistic reading is hard to reach for. There is no ``probability`` field,
no ``expected_return``, and :attr:`Distribution.share_positive` is named for a
share of a sample rather than a chance of an event.

**Small samples are labelled, not hidden.** A distribution over six episodes is
not wrong, but it is a different object from one over four hundred, and a
percentile computed from six is mostly noise. `sample_size` travels everywhere
and :attr:`Distribution.is_indicative` says plainly when the number is too small
to lean on.

**Censored episodes are counted, never dropped.** An episode from eight months
ago has no 12-month outcome yet. Silently excluding it biases the distribution
toward episodes that already resolved, which are systematically the older ones —
and in a fast-moving Process the older ones are the least comparable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from econiq_market.outcomes import HORIZONS, Outcome

#: Below this, a percentile is mostly an artefact of which episodes happened to
#: be in the set. Reported with the number attached rather than suppressed:
#: "three comparable situations, and here they are" is useful; a bare median
#: from three is not.
INDICATIVE_BELOW = 20


@dataclass(frozen=True, slots=True)
class Distribution:
    """What occurred, over one horizon, among a named set of episodes."""

    horizon: str
    #: What the members had in common. A distribution whose basis cannot be
    #: stated is not a comparison, it is a pile of numbers.
    basis: str
    sample_size: int
    censored: int = 0
    percentiles: dict[str, float] = field(default_factory=dict)
    share_positive: float | None = None
    best: float | None = None
    worst: float | None = None

    @property
    def is_indicative(self) -> bool:
        """Too small to lean on. Said out loud rather than left to the reader."""
        return self.sample_size < INDICATIVE_BELOW

    @property
    def coverage(self) -> float:
        """Share of candidate episodes that had resolved at this horizon."""
        total = self.sample_size + self.censored
        return self.sample_size / total if total else 0.0

    def describe(self) -> str:
        """§35's sentence, generated rather than written by hand each time.

        Phrased in the past tense and about a sample, because a reader skims the
        prose and not the field names, and the past tense is what stops this
        being read as a forecast.
        """
        if self.sample_size == 0:
            return f"No comparable situation has a resolved {self.horizon} outcome yet" + (
                f" ({self.censored} still open)." if self.censored else "."
            )
        median = self.percentiles.get("p50")
        low = self.percentiles.get("p25")
        high = self.percentiles.get("p75")
        head = (
            f"Among {self.sample_size} historically comparable situations "
            f"({self.basis}), the subsequent {self.horizon} return was "
            f"{_pct(median)} at the median, with the middle half between "
            f"{_pct(low)} and {_pct(high)}."
        )
        if self.censored:
            head += f" A further {self.censored} have not yet resolved."
        if self.is_indicative:
            head += (
                f" Fewer than {INDICATIVE_BELOW} observations: indicative of what "
                "happened in those cases, not a rate."
            )
        return head


def summarise(
    outcomes: Sequence[Outcome],
    *,
    horizon: str,
    basis: str,
) -> Distribution:
    """Empirical distribution of one horizon across episodes.

    Takes outcomes rather than episodes, so the observation dates were frozen
    before anything here ran (agent doc §9.4). This function cannot cause
    leakage because it never sees a date.
    """
    if horizon not in HORIZONS:
        raise ValueError(f"unknown horizon {horizon!r}; expected one of {sorted(HORIZONS)}")

    values = [outcome.returns[horizon] for outcome in outcomes if horizon in outcome.returns]
    censored = sum(1 for outcome in outcomes if horizon in outcome.unavailable)

    if not values:
        return Distribution(horizon=horizon, basis=basis, sample_size=0, censored=censored)

    ordered = sorted(values)
    return Distribution(
        horizon=horizon,
        basis=basis,
        sample_size=len(ordered),
        censored=censored,
        percentiles={
            "p10": _percentile(ordered, 0.10),
            "p25": _percentile(ordered, 0.25),
            "p50": _percentile(ordered, 0.50),
            "p75": _percentile(ordered, 0.75),
            "p90": _percentile(ordered, 0.90),
        },
        # A share of this sample. Deliberately not called `probability_positive`:
        # the name is what a reader carries away, and one of those names is a
        # claim the calibration work has not earned (§35).
        share_positive=sum(1 for value in ordered if value > 0) / len(ordered),
        best=ordered[-1],
        worst=ordered[0],
    )


def across_horizons(outcomes: Sequence[Outcome], *, basis: str) -> dict[str, Distribution]:
    """Every standard horizon (ontology §36), including empty ones.

    Empty horizons are returned rather than omitted, because a missing key and a
    horizon nothing has reached yet look identical to a caller, and only one of
    them means "wait".
    """
    return {horizon: summarise(outcomes, horizon=horizon, basis=basis) for horizon in HORIZONS}


@dataclass(frozen=True, slots=True)
class DispersionNote:
    """Whether the episodes agreed with each other.

    A median return says nothing about whether the comparable situations
    resembled each other in outcome. Six episodes at +8% and six split between
    +60% and −40% have similar medians and are entirely different findings, and
    the second is the one where "comparable" deserves scrutiny.
    """

    horizon: str
    spread: float | None
    agreement: str

    @property
    def worth_flagging(self) -> bool:
        return self.agreement == "wide"


def dispersion(distribution: Distribution) -> DispersionNote:
    percentiles = distribution.percentiles
    low, high = percentiles.get("p10"), percentiles.get("p90")
    if low is None or high is None or distribution.sample_size < 3:
        return DispersionNote(distribution.horizon, None, "unknown")
    spread = high - low
    # Chosen by this repository, not by the ontology. A 60-point spread between
    # the tenth and ninetieth percentile means the analogues disagreed more than
    # they agreed.
    agreement = "wide" if spread > 0.60 else "narrow" if spread < 0.20 else "moderate"
    return DispersionNote(distribution.horizon, spread, agreement)


def _percentile(ordered: Sequence[float], q: float) -> float:
    """Linear interpolation, matching `statistics.quantiles` behaviour.

    Written out rather than delegated because `quantiles` needs at least two
    points and raises otherwise, and a one-episode distribution is a legitimate
    thing to report — with its sample size attached, which is what stops it
    being mistaken for a rate.
    """
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f}%"


__all__ = [
    "INDICATIVE_BELOW",
    "DispersionNote",
    "Distribution",
    "across_horizons",
    "dispersion",
    "summarise",
]
