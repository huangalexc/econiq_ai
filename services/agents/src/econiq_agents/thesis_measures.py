"""Thesis Quality axes computed from rows (issues #65, #66).

Agent doc §2.3: LLMs propose, deterministic systems verify. Five of the ten
Thesis Quality axes are measurable from data the system already holds, and
measuring them is strictly better than judging them — the number is reproducible,
it moves only when the evidence moves, and nobody has to wonder whether a
half-point change was a real change or a different sampling of the model.

Each function returns the value *and the inputs it came from*, because the
scorecard is required to decompose (issue #25). A measured axis that arrives as
a bare float is no more inspectable than a judged one.

The scales are this repository's, not the ontology's. §42 says the axes are
0–10 and stops there, so the shape of each curve below is a decision, and the
inputs are returned so the decision can be argued with.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from econiq_ontology import ThesisQualityDimension as Axis


@dataclass(frozen=True, slots=True)
class Measure:
    """One computed axis, with the arithmetic behind it."""

    axis: Axis
    value: float
    inputs: dict[str, float]
    rationale: str


def state_confidence(
    confidence: float | None, *, observed_at: datetime | None, now: datetime
) -> Measure | None:
    """The State estimate's own confidence, aged.

    Not re-judged: it is already a number the State agent produced against the
    archetype's machine. What is added is decay — a confident State estimate
    from eight months ago is not a confident statement about today, and the
    axis is supposed to describe the thesis now.
    """
    if confidence is None:
        return None
    age_days = (now - observed_at).total_seconds() / 86400.0 if observed_at else 0.0
    # Half-life of roughly six months: still meaningful at three, thin at a year.
    freshness = 0.5 ** (age_days / 180.0) if age_days > 0 else 1.0
    value = confidence * 10.0 * (0.5 + 0.5 * freshness)
    return Measure(
        axis=Axis.STATE_CONFIDENCE,
        value=round(min(value, 10.0), 2),
        inputs={
            "state_confidence": round(confidence, 4),
            "age_days": round(age_days, 1),
            "freshness": round(freshness, 4),
        },
        rationale=(
            f"State estimated at {confidence:.2f} confidence, {age_days:.0f} days ago. "
            "Aged because a confident estimate about July is not a confident "
            "statement about today."
        ),
    )


def accumulated_evidence(*, supporting: int, recent: int, window_days: int = 90) -> Measure:
    """How much evidence stands behind the thesis, and how much of it is current.

    Saturating rather than linear: the tenth supporting Event says much less
    than the second, and a linear scale would let a Process with forty routine
    mentions outrank one with six decisive ones.
    """
    depth = min(supporting / 8.0, 1.0)
    currency = min(recent / 4.0, 1.0) if supporting else 0.0
    value = 10.0 * (0.65 * depth + 0.35 * currency)
    return Measure(
        axis=Axis.ACCUMULATED_EVIDENCE,
        value=round(value, 2),
        inputs={
            "supporting_events": float(supporting),
            "recent_events": float(recent),
            "window_days": float(window_days),
        },
        rationale=(
            f"{supporting} supporting Event(s), {recent} in the last {window_days} days. "
            "Saturating: the tenth says less than the second."
        ),
    )


def evidence_independence(*, independent_sources: int, documents: int) -> Measure | None:
    """How many genuinely separate reports stand behind the evidence (§47).

    The ratio matters as much as the count. Six documents collapsing to one
    source is a thesis resting on a single report however impressive the
    document count looks, and this axis exists to say so.
    """
    if documents == 0:
        return None
    ratio = independent_sources / documents
    breadth = min(independent_sources / 5.0, 1.0)
    value = 10.0 * (0.6 * breadth + 0.4 * ratio)
    return Measure(
        axis=Axis.EVIDENCE_INDEPENDENCE,
        value=round(value, 2),
        inputs={
            "independent_sources": float(independent_sources),
            "documents": float(documents),
            "collapse_ratio": round(ratio, 4),
        },
        rationale=(
            f"{independent_sources} independent source(s) across {documents} document(s). "
            f"{documents - independent_sources} added no independent source."
        ),
    )


def contradiction(*, falsification_risk: float | None, contradicting_events: int) -> Measure | None:
    """Contradiction burden, from the Critic's risk and the evidence against.

    Note the direction: this axis is *burden*, so a high number is bad. It is
    stored unreversed because inverting it here would make the stored value
    disagree with the Critic's, and two numbers describing the same thing in
    opposite directions is how a scorecard starts lying.
    """
    if falsification_risk is None and contradicting_events == 0:
        return None
    risk = falsification_risk if falsification_risk is not None else 0.0
    weight = min(contradicting_events / 4.0, 1.0)
    value = min(0.75 * risk + 2.5 * weight, 10.0)
    return Measure(
        axis=Axis.CONTRADICTION,
        value=round(value, 2),
        inputs={
            "falsification_risk": round(risk, 2),
            "contradicting_events": float(contradicting_events),
        },
        rationale=(
            f"Critic put falsification risk at {risk:.1f}; {contradicting_events} "
            "Event(s) recorded against the thesis. Higher is worse on this axis."
        ),
    )


def counterfactual_robustness(
    counterfactuals: list[tuple[float, float, int]],
) -> Measure | None:
    """How well the thesis survives its alternative worlds (issue #66).

    ``counterfactuals`` is ``(plausibility, severity_if_true, indicator_count)``
    per world.

    Computed here rather than asked of the agent that constructed them. An agent
    that both builds the attacks and grades its own attack quality has no reason
    to build good ones — the same argument that keeps the Process Critic from
    scoring its own critiques.

    A Process with *no* counterfactuals scores nothing rather than 10. Untested
    is not robust, and returning a perfect score for an unexamined thesis would
    invert the axis exactly where it matters most.
    """
    if not counterfactuals:
        return None

    # Each world's threat is plausibility × severity, normalised to 0-1. The
    # worst one dominates: a thesis is as robust as its most dangerous
    # unanswered alternative, not as robust as its average one.
    threats = [(p / 10.0) * (s / 10.0) for p, s, _ in counterfactuals]
    worst = max(threats)
    mean = sum(threats) / len(threats)
    observable = sum(1 for _, _, indicators in counterfactuals if indicators > 0)

    # Coverage: worlds that can be watched for are worlds that can be ruled out,
    # so a set nobody can monitor supports a weaker conclusion either way.
    coverage = observable / len(counterfactuals)
    value = 10.0 * (1.0 - (0.7 * worst + 0.3 * mean)) * (0.7 + 0.3 * coverage)
    return Measure(
        axis=Axis.COUNTERFACTUAL_ROBUSTNESS,
        value=round(max(value, 0.0), 2),
        inputs={
            "counterfactuals": float(len(counterfactuals)),
            "worst_threat": round(worst, 4),
            "mean_threat": round(mean, 4),
            "observable_coverage": round(coverage, 4),
        },
        rationale=(
            f"Survived {len(counterfactuals)} alternative world(s); the most "
            f"dangerous scores {worst:.2f} on plausibility times severity. "
            f"{observable} of {len(counterfactuals)} carry an observable indicator."
        ),
    )


def within(moment: datetime, *, now: datetime, days: int) -> bool:
    return now - moment <= timedelta(days=days)
