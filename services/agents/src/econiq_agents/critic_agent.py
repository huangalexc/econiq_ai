"""The Process Critic (issue #10, agent doc §6.5).

Independent critique exists to counter one specific failure: language models
build coherent narratives, and a coherent narrative is persuasive whether or not
it is true. Every other Process agent is trying to make sense of the evidence.
This one is trying to break the result.

Independence is structural, not a request. It is a separate agent with a
separate prompt, seeing the evidence rather than the reasoning that was built on
it — asking the same model "are you sure?" is not an independence mechanism
(agent doc §15). Where a second model family exists, ``LLMSettings.critic_model``
points the critic at it; until then the outcome records that independence was
prompt-level only rather than pretending otherwise.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from econiq_llm import Agent, CitationEvaluator, EvaluationCheck, Evaluator, ModelTier
from econiq_ontology import CritiqueKind
from econiq_schemas import AgentInput, AgentOutput, ProcessCriticInput, ProcessCriticOutput

from econiq_agents.prompts import PROCESS_CRITIC_V1

#: Phrases that walk a critique back. The critic's output is the attack; the
#: weighing happens elsewhere, so a finding that argues itself down has both
#: overstepped and weakened the signal the scorer depends on.
_RESCUE_LANGUAGE = re.compile(
    r"\b(?:however[, ]+(?:this|the thesis|it) (?:is|remains|still)|"
    r"on balance|nonetheless the (?:thesis|process)|"
    r"this is (?:likely )?(?:mitigated|offset|outweighed)|"
    r"overall[, ]+the (?:thesis|process|case) (?:remains|is|holds)|"
    r"the (?:thesis|process|case) (?:remains|is still) (?:sound|strong|intact|valid)|"
    r"does not (?:materially )?(?:undermine|weaken|affect) the (?:thesis|process)|"
    r"unlikely to (?:matter|be material)|"
    r"this concern is (?:minor|overstated|unlikely))\b",
    re.IGNORECASE,
)


class Independence(StrEnum):
    """How independent a critique run actually was.

    Recorded rather than assumed, so the Research Quality Auditor (issue #57)
    can measure whether critiques that came from the same model as the thesis
    find fewer problems than those that did not.
    """

    DISTINCT_MODEL = "distinct_model"
    PROMPT_ONLY = "prompt_only"


class ProcessCriticAgent(Agent[ProcessCriticInput, ProcessCriticOutput]):
    """Adversarial critique of a Process.

    Reasoning tier and, where configured, a different model from the one that
    built the thesis. Note what the output schema does *not* contain: no
    mitigations field, no overall verdict, nothing in which the thesis can be
    defended. The structure enforces what the prompt asks for.
    """

    name = "process_critic"
    version = "1.0.0"
    ontology_layer = "Process"
    tier = ModelTier.REASONING
    effort = "high"

    input_schema = ProcessCriticInput
    output_schema = ProcessCriticOutput
    prompt = PROCESS_CRITIC_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (
            CitationEvaluator(),
            NoRescueEvaluator(),
            MostDamagingEvaluator(),
            TestabilityEvaluator(),
        )

    def build_user_content(self, payload: ProcessCriticInput) -> str:
        lines = [
            f"Process: {payload.process.name}",
            f"  {payload.process.description}",
        ]
        if payload.process.archetype:
            lines.append(f"  archetype: {payload.process.archetype.value}")
        if payload.process.current_state:
            lines.append(f"  current State: {payload.process.current_state.value}")
        lines += ["", "Thesis:", f"  {payload.thesis_statement}"]
        if payload.supporting_event_summaries:
            lines += ["", "Evidence the thesis rests on:"]
            lines += [f"- {summary}" for summary in payload.supporting_event_summaries]
        if payload.claim_texts:
            lines += ["", "Underlying Claims:"]
            lines += [f"- [{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)


class NoRescueEvaluator:
    """Catches a critic that talks itself out of its own finding.

    "This is a real gap, however the thesis remains sound" is not a critique; it
    is a critique and a rebuttal, and the rebuttal is not this agent's to make.
    Adjudication happens downstream with the full picture (agent doc §15).
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, ProcessCriticOutput):
            return ()
        rescued = sorted(
            {
                match.group(0).lower()
                for critique in output.critiques
                for field in (critique.statement, critique.rationale)
                for match in [_RESCUE_LANGUAGE.search(field)]
                if match
            }
        )
        return (
            EvaluationCheck(
                name="no_rescue_language",
                passed=not rescued,
                detail=None if not rescued else f"critiques argue themselves down: {rescued}",
            ),
        )


class MostDamagingEvaluator:
    """The nominated critique must actually be the most severe one.

    The scorer and the UI both lead with it, so a mismatch between the label and
    the severities is a quietly misleading summary rather than a harmless
    inconsistency.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, ProcessCriticOutput) or not output.critiques:
            return ()
        index = output.most_damaging_critique_index
        if index is None:
            return ()
        highest = max(critique.severity for critique in output.critiques)
        nominated = output.critiques[index].severity
        return (
            EvaluationCheck(
                name="most_damaging_is_most_severe",
                passed=nominated >= highest,
                detail=(
                    None
                    if nominated >= highest
                    else f"nominated severity {nominated:.1f} below the maximum {highest:.1f}"
                ),
            ),
        )


class TestabilityEvaluator:
    """A falsifying indicator has to name what would falsify it.

    Every critique benefits from being testable, but for
    ``falsifying_indicator`` it is the entire content of the finding: without an
    observation attached it is a restatement of doubt, and it cannot become the
    monitoring condition that makes the critique useful later (issue #32).
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, ProcessCriticOutput):
            return ()
        untestable = [
            critique.statement[:60]
            for critique in output.critiques
            if critique.kind is CritiqueKind.FALSIFYING_INDICATOR and not critique.testable_with
        ]
        return (
            EvaluationCheck(
                name="falsifying_indicators_are_testable",
                passed=not untestable,
                detail=(
                    None
                    if not untestable
                    else f"falsifying indicators with nothing to observe: {untestable}"
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Which lines of attack the critic actually took.

    An adversarial pass that only ever finds contradictory evidence has not
    attacked the thesis from seven directions, and that is measurable without a
    human — one of issue #10's eval hooks.
    """

    attempted: frozenset[CritiqueKind]

    @property
    def missing(self) -> tuple[CritiqueKind, ...]:
        return tuple(sorted(set(CritiqueKind) - self.attempted, key=lambda k: k.value))

    @property
    def ratio(self) -> float:
        return len(self.attempted) / len(CritiqueKind)


def coverage_of(output: ProcessCriticOutput) -> CoverageReport:
    return CoverageReport(attempted=frozenset(c.kind for c in output.critiques))
