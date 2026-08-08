"""The Counterfactual / Falsification agent (issue #66, agent doc §10.1).

Distinct from the Process Critic, and the distinction is worth stating because
the two look similar from outside. The Critic attacks the evidence and the
reasoning: *this step is unsupported, that correlation may not be causal*. This
agent accepts both and asks a different question — what else could have produced
this evidence, and what would have to be true instead for the Process to fail?

A thesis can survive every critique and still be wrong because the world took a
different path, and nothing in the Critic's seven lines of attack asks about
that.

**"Do not use straw men" is enforced, not requested.** §10.1 says it and a
prompt cannot make it so; a model asked for counterfactuals will happily produce
five it can dismiss, which makes the thesis look tested when it has not been.
Three deterministic checks catch the usual shapes:

* an alternative world with no observable indicator — nobody could ever tell
  whether it happened, which is the most common form;
* several counterfactuals removing the same assumption, which is one
  counterfactual written out several times;
* a counterfactual the agent itself scores as implausible, which is a straw man
  by the agent's own admission.

None of these can prove a counterfactual is strong. They catch the failures that
are cheap to detect and would otherwise inflate the robustness score computed
downstream.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from econiq_llm import Agent, CitationEvaluator, EvaluationCheck, Evaluator, ModelTier
from econiq_schemas import AgentInput, AgentOutput, CounterfactualInput, CounterfactualOutput

from econiq_agents.prompts import COUNTERFACTUAL_V1

#: Below this, the agent has said the world is not worth considering. Including
#: it anyway pads the count, and the count feeds a score.
MIN_PLAUSIBILITY = 2.0

#: Two assumptions this similar are the same assumption. Compared on normalised
#: word sets rather than strings, because "permitting timelines hold" and
#: "timelines for permitting will hold" are not two ideas.
ASSUMPTION_OVERLAP = 0.7

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "is",
        "are",
        "will",
        "would",
        "that",
        "this",
        "and",
        "or",
        "be",
        "been",
        "as",
        "by",
        "it",
        "its",
        "not",
        "no",
        "with",
        "from",
        "remain",
        "remains",
    }
)


def _keywords(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS)


def _overlap(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


class FalsifiabilityEvaluator:
    """Every alternative world must be recognisable if it happens.

    The schema already requires at least one indicator, so this checks the
    quality of it: an indicator that merely restates the alternative world tells
    nobody what to look for. Advisory rather than blocking, because the line
    between a vague indicator and a genuinely hard-to-observe one is a judgement
    and blocking on it would throw away real findings.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, CounterfactualOutput):
            return ()

        vague: list[str] = []
        for counterfactual in output.counterfactuals:
            world = _keywords(counterfactual.alternative_world)
            for indicator in counterfactual.observable_indicators:
                if _overlap(_keywords(indicator), world) > 0.85:
                    vague.append(indicator)

        return (
            EvaluationCheck(
                name="indicators_are_observations",
                passed=not vague,
                detail=(
                    "every indicator names something to look for"
                    if not vague
                    else f"{len(vague)} indicator(s) restate the world rather than "
                    f"naming an observation: {vague[:2]}"
                ),
                blocking=False,
            ),
        )


class DiversityEvaluator:
    """Counterfactuals must challenge different assumptions.

    Blocking. This is not a quality preference: the robustness score is computed
    from the *set*, so three restatements of one assumption would make a thesis
    look attacked from three directions when it was attacked from one, and the
    score would be wrong rather than merely generous.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, CounterfactualOutput):
            return ()

        keywords = [_keywords(c.challenged_assumption) for c in output.counterfactuals]
        duplicates: list[tuple[int, int]] = []
        for i in range(len(keywords)):
            for j in range(i + 1, len(keywords)):
                if _overlap(keywords[i], keywords[j]) >= ASSUMPTION_OVERLAP:
                    duplicates.append((i, j))

        return (
            EvaluationCheck(
                name="assumptions_are_distinct",
                passed=not duplicates,
                detail=(
                    f"{len(output.counterfactuals)} counterfactual(s) challenge "
                    "distinct assumptions"
                    if not duplicates
                    else f"counterfactuals {duplicates[0]} remove the same assumption"
                ),
            ),
        )


class PlausibilityEvaluator:
    """No world the agent itself calls implausible.

    Blocking, and for the same reason as diversity: a counterfactual scored 1/10
    for plausibility is a straw man by the agent's own admission, and it would
    still count toward the robustness denominator.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, CounterfactualOutput):
            return ()

        weak = [
            c.challenged_assumption
            for c in output.counterfactuals
            if c.plausibility < MIN_PLAUSIBILITY
        ]
        return (
            EvaluationCheck(
                name="no_straw_men",
                passed=not weak,
                detail=(
                    "no counterfactual is dismissed by its own plausibility score"
                    if not weak
                    else f"{len(weak)} counterfactual(s) scored below "
                    f"{MIN_PLAUSIBILITY} for plausibility: {weak[:2]}"
                ),
            ),
        )


class CounterfactualAgent(Agent[CounterfactualInput, CounterfactualOutput]):
    """Constructs the alternative worlds a Process has to survive.

    Runs on the reasoning tier and, where a second model family is configured,
    on the critic model — the same independence argument as the Process Critic
    (agent doc §15, §22). Asking the model that built the thesis to imagine it
    failing is not an independent reasoning path.
    """

    name = "counterfactual"
    version = "1.0.0"
    ontology_layer = "Process"
    tier = ModelTier.REASONING
    effort = "high"

    input_schema = CounterfactualInput
    output_schema = CounterfactualOutput
    prompt = COUNTERFACTUAL_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (
            CitationEvaluator(),
            DiversityEvaluator(),
            PlausibilityEvaluator(),
            FalsifiabilityEvaluator(),
        )

    def build_user_content(self, payload: CounterfactualInput) -> str:
        lines = [
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
        if payload.supporting_event_summaries:
            lines += ["", "Evidence the thesis rests on:"]
            lines += [f"- {summary}" for summary in payload.supporting_event_summaries]
        # Supplied so this agent does not spend its output restating the Critic.
        if payload.known_critiques:
            lines += ["", "Objections the Process Critic has already made:"]
            lines += [f"- {critique}" for critique in payload.known_critiques]
        if payload.claim_texts:
            lines += ["", "Claims available for citation:"]
            lines += [f"[{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)
