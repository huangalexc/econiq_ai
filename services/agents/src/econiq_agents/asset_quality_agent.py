"""The Asset Quality agent (issue #76, agent doc §8.4).

Judges what standard financial metrics do not capture, for an Asset *as an
expression of one Capability*. The Capability is not context — the same company
is a strong expression of one and a weak expression of another, and a score with
no Capability attached is a company rating rather than a thesis expression
(ontology §17).

Split from the Quant agent (#75) the same way the Thesis scorer's computed and
judged axes are split: technical confirmation is measured from prices and passed
in, and this agent is told not to score it. A judged number and a measured one
should never be indistinguishable on a scorecard.
"""

from __future__ import annotations

from collections.abc import Sequence

from econiq_llm import Agent, CitationEvaluator, EvaluationCheck, Evaluator, ModelTier
from econiq_ontology import AssetQualityDimension as Axis
from econiq_schemas import AgentInput, AgentOutput, AssetQualityInput, AssetQualityOutput

from econiq_agents.prompts import ASSET_QUALITY_V1

#: Measured from price rows (#75), never judged.
COMPUTED_AXES: frozenset[Axis] = frozenset({Axis.TECHNICAL_CONFIRMATION})

#: Need a fundamentals or holdings source that does not exist yet (#77 covers
#: prices only). Scored by nobody rather than guessed from price action.
UNAVAILABLE_AXES: frozenset[Axis] = frozenset(
    {Axis.VALUATION, Axis.BALANCE_SHEET, Axis.INSTITUTIONAL_POSITIONING}
)

#: What is left: the characteristics §8.4 exists to assess.
JUDGED_AXES: tuple[Axis, ...] = tuple(
    axis for axis in Axis if axis not in COMPUTED_AXES and axis not in UNAVAILABLE_AXES
)


class AxisCoverageEvaluator:
    """Every judged axis, and nothing the system measured or cannot source.

    Blocking both ways, for the reasons the Thesis scorer's equivalent is: a
    missing axis leaves a hole the comparison matrix renders as "awaiting", and
    an extra one is either a second producer on one dimension or a valuation
    inferred from nothing.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, AssetQualityOutput):
            return ()
        scored = {axis.dimension for axis in output.axes}
        expected = set(JUDGED_AXES)
        missing = sorted(a.value for a in expected - scored)
        extra = sorted(a.value for a in scored - expected)
        return (
            EvaluationCheck(
                name="all_judged_axes_scored",
                passed=not missing,
                detail=f"scored all {len(expected)} axes" if not missing else f"missing: {missing}",
            ),
            EvaluationCheck(
                name="no_unsourced_axis_scored",
                passed=not extra,
                detail=(
                    "scored nothing measured elsewhere or unsourceable"
                    if not extra
                    else f"scored axes it should not have: {extra}"
                ),
            ),
        )


class CounterargumentEvaluator:
    """§8.4 asks for counterarguments; an assessment without one is a pitch.

    Advisory rather than blocking. A genuinely uncontested characteristic
    exists — a company that is the only licensed operator has few counterpoints
    on market share — and blocking would push the agent into inventing them,
    which is worse than the silence.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, AssetQualityOutput):
            return ()
        bare = [axis.dimension.value for axis in output.axes if not axis.counterarguments]
        return (
            EvaluationCheck(
                name="axes_state_the_case_against",
                passed=not bare,
                detail=(
                    "every axis names a counterargument"
                    if not bare
                    else f"axes with no case against: {bare}"
                ),
                blocking=False,
            ),
        )


class SeparationEvaluator:
    """No valuation or price language, however it arrives.

    Blocking. §8.4 says to exclude it and ontology §17 makes the separation
    structural; an axis that reasons about cheapness has produced Asset Quality
    contaminated with something the family is defined to exclude, and no reader
    downstream could tell.
    """

    _BANNED = (
        "valuation",
        "multiple",
        "p/e",
        "price target",
        "cheap",
        "expensive",
        "overvalued",
        "undervalued",
    )

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, AssetQualityOutput):
            return ()
        hits: list[str] = []
        for axis in output.axes:
            text = " ".join(
                [axis.why_not_higher, *axis.facts, *axis.inferences, *axis.counterarguments]
            ).lower()
            hits += [f"{axis.dimension.value}: {word}" for word in self._BANNED if word in text]
        return (
            EvaluationCheck(
                name="no_valuation_reasoning",
                passed=not hits,
                detail=(
                    "no axis reasons about price or valuation"
                    if not hits
                    else f"valuation language in {hits[:3]}"
                ),
            ),
        )


class AssetQualityAgent(Agent[AssetQualityInput, AssetQualityOutput]):
    """Qualitative characteristics of an Asset as a Capability expression."""

    name = "asset_quality"
    version = "1.0.0"
    ontology_layer = "Asset"
    tier = ModelTier.REASONING
    effort = "high"

    input_schema = AssetQualityInput
    output_schema = AssetQualityOutput
    prompt = ASSET_QUALITY_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (
            CitationEvaluator(),
            AxisCoverageEvaluator(),
            SeparationEvaluator(),
            CounterargumentEvaluator(),
        )

    def build_user_content(self, payload: AssetQualityInput) -> str:
        lines = [
            "Score exactly these axes:",
            *[f"- {axis.value}" for axis in JUDGED_AXES],
            "",
            f"Asset: {payload.asset_name}" + (f" ({payload.ticker})" if payload.ticker else ""),
            f"  class: {payload.asset_class}",
            "",
            f"As an expression of: {payload.capability_name}",
            f"  {payload.capability_description}",
            f"  required by: {payload.process_name}",
        ]
        if payload.exposure_summaries:
            lines += ["", "Recorded exposures:"]
            lines += [f"- {summary}" for summary in payload.exposure_summaries]
        if payload.computed_axes:
            lines += ["", "Already measured from price data — do not score these:"]
            lines += [
                f"- {name}: {value:.1f}" for name, value in sorted(payload.computed_axes.items())
            ]
        if payload.claim_texts:
            lines += ["", "Claims available for citation:"]
            lines += [f"[{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)
