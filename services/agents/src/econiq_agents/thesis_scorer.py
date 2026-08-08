"""The Thesis Scoring agent (issue #65, agent doc §11.1; ontology §42).

Scores the Process, never an Asset. §11.1 is explicit — "do not consider
valuation or technical setup" — and ontology §17 makes that separation
structural, so the schema has no field a valuation could occupy and the score
family would reject it if it did.

**Only the axes that need judgement are judged.** Of the ten axes, five are
measurable from rows the system already has:

=========================  ==================================================
Axis                       Where it comes from
=========================  ==================================================
state_confidence           the ProcessState. It *is* a number already.
accumulated_evidence       count and recency of supporting evidence
evidence_independence      independent sources against document count (§47)
contradiction              the Critic's falsification risk
counterfactual_robustness  computed from the counterfactuals (#66)
=========================  ==================================================

Asking a model to re-judge a number the system computed is not a second opinion,
it is an opportunity for the two to disagree — and when they do, nothing says
which is right. So the computed axes are passed in as context and the prompt
tells the agent not to score them; the writer merges both sets.

``historical_precedent`` is scored by nobody. It needs the Phase 2 retrieval
engine, and an axis scored on vibes is worse than an axis marked absent: the
scorecard renders "awaiting" for it, which is true, rather than a 6.5 that
looks like a measurement.

**No composite, anywhere.** §42 requires the dimensions be preserved even if a
composite is eventually calculated; PRD §10 forbids reducing them to one
unexplained number. The output schema has no field for one and the writer does
not compute one.
"""

from __future__ import annotations

from collections.abc import Sequence

from econiq_llm import Agent, CitationEvaluator, EvaluationCheck, Evaluator, ModelTier
from econiq_ontology import ThesisQualityDimension as Axis
from econiq_schemas import AgentInput, AgentOutput, ThesisScoringInput, ThesisScoringOutput

from econiq_agents.prompts import THESIS_SCORING_V1

#: Axes computed from rows rather than judged. Not offered to the agent.
COMPUTED_AXES: frozenset[Axis] = frozenset(
    {
        Axis.STATE_CONFIDENCE,
        Axis.ACCUMULATED_EVIDENCE,
        Axis.EVIDENCE_INDEPENDENCE,
        Axis.CONTRADICTION,
        Axis.COUNTERFACTUAL_ROBUSTNESS,
    }
)

#: Needs the Phase 2 historical engine. Scored by nobody until then.
UNAVAILABLE_AXES: frozenset[Axis] = frozenset({Axis.HISTORICAL_PRECEDENT})

#: What is left for the model: the axes that are genuinely judgements about
#: whether the argument holds together.
JUDGED_AXES: tuple[Axis, ...] = tuple(
    axis for axis in Axis if axis not in COMPUTED_AXES and axis not in UNAVAILABLE_AXES
)


class AxisCoverageEvaluator:
    """The agent must score every axis it was asked for, and no others.

    Blocking in both directions. A missing axis leaves a hole the scorecard
    renders as "awaiting an agent", which would be a lie once this agent exists.
    An extra axis means it scored something the system measured itself, and
    silently keeping it would put two producers on one dimension.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, ThesisScoringOutput) or not isinstance(
            payload, ThesisScoringInput
        ):
            return ()

        scored = {axis.dimension for axis in output.axes}
        expected = set(JUDGED_AXES)
        missing = sorted(a.value for a in expected - scored)
        extra = sorted(a.value for a in scored - expected)

        return (
            EvaluationCheck(
                name="all_judged_axes_scored",
                passed=not missing,
                detail=(
                    f"scored all {len(expected)} judgement axes"
                    if not missing
                    else f"missing: {missing}"
                ),
            ),
            EvaluationCheck(
                name="no_computed_axis_rescored",
                passed=not extra,
                detail=(
                    "scored nothing the system measures itself"
                    if not extra
                    else f"re-scored computed or unavailable axes: {extra}"
                ),
            ),
        )


class ReasoningEvaluator:
    """Every axis needs a stated ceiling reason, and facts kept from inferences.

    §11.1 asks for both. The first is blocking because a score with no reason it
    is not higher is an assertion, and the whole scorecard exists to stop those.
    The second is advisory: an axis resting entirely on inference is a weak
    score rather than an invalid one, and the reader can see that for
    themselves once the two lists are separate.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, ThesisScoringOutput):
            return ()

        # `why_not_higher` is required by the schema, so what is left to catch
        # is the version that says nothing.
        empty = [
            axis.dimension.value for axis in output.axes if len(axis.why_not_higher.split()) < 4
        ]
        inference_only = [
            axis.dimension.value for axis in output.axes if axis.inferences and not axis.facts
        ]

        return (
            EvaluationCheck(
                name="ceiling_reasons_are_substantive",
                passed=not empty,
                detail=(
                    "every axis says what keeps it below 10"
                    if not empty
                    else f"axes with a token ceiling reason: {empty}"
                ),
            ),
            EvaluationCheck(
                name="axes_rest_on_facts",
                passed=not inference_only,
                detail=(
                    "every scored axis cites at least one observation"
                    if not inference_only
                    else f"axes resting entirely on inference: {inference_only}"
                ),
                blocking=False,
            ),
        )


class ThesisScoringAgent(Agent[ThesisScoringInput, ThesisScoringOutput]):
    """Multidimensional Thesis Quality, judgement axes only."""

    name = "thesis_scoring"
    version = "1.0.0"
    ontology_layer = "Process"
    tier = ModelTier.REASONING
    effort = "high"

    input_schema = ThesisScoringInput
    output_schema = ThesisScoringOutput
    prompt = THESIS_SCORING_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (CitationEvaluator(), AxisCoverageEvaluator(), ReasoningEvaluator())

    def build_user_content(self, payload: ThesisScoringInput) -> str:
        lines = [
            "Score exactly these axes:",
            *[f"- {axis.value}" for axis in JUDGED_AXES],
            "",
            f"Process: {payload.process.name}",
            f"  {payload.process.description}",
        ]
        if payload.process.archetype:
            lines.append(f"  archetype: {payload.process.archetype.value}")
        if payload.process.current_state:
            lines.append(f"  current State: {payload.process.current_state.value}")
        lines += ["", "Thesis:", f"  {payload.thesis_statement}"]
        if payload.causal_mechanism:
            lines += ["", "Causal mechanism:", f"  {payload.causal_mechanism}"]

        if payload.computed_axes:
            # Shown so the agent has the full picture, and named as measured so
            # it does not treat them as scores to be consistent with.
            lines += ["", "Already measured by the system — do not score these:"]
            lines += [
                f"- {name}: {value:.1f}" for name, value in sorted(payload.computed_axes.items())
            ]

        if payload.supporting_event_summaries:
            lines += ["", "Supporting evidence:"]
            lines += [f"- {summary}" for summary in payload.supporting_event_summaries]
        if payload.contradicting_event_summaries:
            lines += ["", "Contradicting evidence:"]
            lines += [f"- {summary}" for summary in payload.contradicting_event_summaries]
        if payload.open_critiques:
            lines += ["", "Open critiques:"]
            lines += [f"- {critique}" for critique in payload.open_critiques]
        if payload.claim_texts:
            lines += ["", "Claims available for citation:"]
            lines += [f"[{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)
