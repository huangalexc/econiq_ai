"""Process Archetype and Process State agents (issue #9, agent doc §6.3–§6.4).

The Archetype determines which State model applies, which historical analogs are
comparable, and which evidence matters — so it is classified before State is
estimated, and a Process without one gets no State at all.

The State machines in ``econiq_ontology.archetypes`` are enforced twice: the
schema rejects a State that does not belong to the Archetype, and
``StateTransitionEvaluator`` rejects a move the machine does not permit from
where the Process already was. A model cannot teleport a Process from Discovery
to Maturity, whatever the prose says.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from econiq_llm import Agent, CitationEvaluator, EvaluationCheck, Evaluator, ModelTier
from econiq_ontology import ProcessStateLabel, state_machine
from econiq_schemas import (
    AgentInput,
    AgentOutput,
    ProcessArchetypeInput,
    ProcessArchetypeOutput,
    ProcessStateInput,
    ProcessStateOutput,
)

from econiq_agents.process_agents import LayerBoundaryEvaluator
from econiq_agents.prompts import PROCESS_ARCHETYPE_V1, PROCESS_STATE_V1


class ProcessArchetypeAgent(Agent[ProcessArchetypeInput, ProcessArchetypeOutput]):
    """Process → Archetype (agent doc §6.3).

    Reasoning tier. Getting this wrong is expensive in a way that is hard to
    see: every State estimate, every historical analog and every comparison
    afterwards is drawn from the wrong model, and each individual step looks
    reasonable.
    """

    name = "process_archetype"
    version = "1.0.0"
    ontology_layer = "Process"
    tier = ModelTier.REASONING

    input_schema = ProcessArchetypeInput
    output_schema = ProcessArchetypeOutput
    prompt = PROCESS_ARCHETYPE_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (CitationEvaluator(), LayerBoundaryEvaluator(layer="Process"))

    def build_user_content(self, payload: ProcessArchetypeInput) -> str:
        lines = [
            f"Process: {payload.process.name}",
            f"  {payload.process.description}",
        ]
        if payload.recent_event_summaries:
            lines += ["", "Recent Events:"]
            lines += [f"- {summary}" for summary in payload.recent_event_summaries]
        if payload.claim_texts:
            lines += ["", "Supporting Claims:"]
            lines += [f"- [{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)


class ProcessStateAgent(Agent[ProcessStateInput, ProcessStateOutput]):
    """Process → Process State (agent doc §6.4, ontology §10)."""

    name = "process_state"
    version = "1.0.0"
    ontology_layer = "Process → Process State"
    tier = ModelTier.REASONING

    input_schema = ProcessStateInput
    output_schema = ProcessStateOutput
    prompt = PROCESS_STATE_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (
            CitationEvaluator(),
            LayerBoundaryEvaluator(layer="Process State"),
            StateTransitionEvaluator(),
            MeasuredFeatureEvaluator(),
        )

    def build_user_content(self, payload: ProcessStateInput) -> str:
        machine = state_machine(payload.archetype)
        lines = [
            f"Process: {payload.process.name}",
            f"  {payload.process.description}",
            f"  archetype: {payload.archetype.value}",
            "",
            "Permitted States, in developmental order:",
        ]
        for position, state in enumerate(payload.permitted_states, start=1):
            marker = " (current)" if state is payload.prior_state else ""
            lines.append(f"  {position}. {state.value}{marker}")

        if payload.prior_state is not None:
            reachable = sorted(
                target.value for target in machine.transitions.get(payload.prior_state, frozenset())
            )
            lines += [
                "",
                f"From {payload.prior_state.value} the Process may move to: "
                + (", ".join(reachable) if reachable else "(no onward transition)")
                + ". It may also stay where it is.",
            ]
        if payload.measured_features:
            lines += ["", "Measured features (interpret; do not restate as your own estimate):"]
            lines += [
                f"- {name}: {value:.2f}"
                for name, value in sorted(payload.measured_features.items())
            ]
        if payload.claim_texts:
            lines += ["", "Evidence:"]
            lines += [f"- [{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)


class StateTransitionEvaluator:
    """The proposed State must be reachable from where the Process was.

    The schema already rejects a State that does not belong to the Archetype.
    This is the other half: a Process in Discovery cannot appear in Maturity
    next week. Staying put is always permitted — and is the common, informative
    case.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(payload, ProcessStateInput) or not isinstance(output, ProcessStateOutput):
            return ()

        checks: list[EvaluationCheck] = []
        machine = state_machine(payload.archetype)
        proposed = output.categorical_state
        prior = payload.prior_state

        offered = set(payload.permitted_states)
        checks.append(
            EvaluationCheck(
                name="state_within_offered_vocabulary",
                passed=proposed in offered,
                detail=(
                    None
                    if proposed in offered
                    else f"{proposed.value!r} was not among the permitted States"
                ),
            )
        )

        if prior is not None:
            legal = proposed is prior or machine.can_transition(prior, proposed)
            checks.append(
                EvaluationCheck(
                    name="transition_is_reachable",
                    passed=legal,
                    detail=(
                        None
                        if legal
                        else f"{prior.value!r} → {proposed.value!r} is not a permitted "
                        f"transition under {payload.archetype.value!r}"
                    ),
                )
            )
        return tuple(checks)


class MeasuredFeatureEvaluator:
    """A measured feature must not be quietly restated as a different number.

    Deterministic code computes the quantities; the agent interprets them
    (ontology §2.4). An agent that returns ``capex_acceleration = 6.0`` when the
    measurement said 8.7 has replaced an observation with an opinion, and the
    two look identical once stored.
    """

    def __init__(self, *, tolerance: float = 0.5) -> None:
        self.tolerance = tolerance

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(payload, ProcessStateInput) or not isinstance(output, ProcessStateOutput):
            return ()
        if not payload.measured_features:
            return ()

        contradicted = [
            f"{feature.name}: measured {payload.measured_features[feature.name]:.2f}, "
            f"returned {feature.value:.2f}"
            for feature in output.features
            if feature.name in payload.measured_features
            and abs(feature.value - payload.measured_features[feature.name]) > self.tolerance
        ]
        return (
            EvaluationCheck(
                name="measured_features_preserved",
                passed=not contradicted,
                detail=None if not contradicted else "; ".join(contradicted),
            ),
        )


@dataclass(frozen=True, slots=True)
class TransitionSignificance:
    """How big a move a State change is.

    Used for the human-review hook of agent doc §23: State determines historical
    analog selection, so a large or backward move is where an error propagates
    furthest.
    """

    changed: bool
    steps: int
    backwards: bool

    @property
    def major(self) -> bool:
        return self.backwards or self.steps > 1


def classify_transition(
    archetype_states: Sequence[ProcessStateLabel],
    prior: ProcessStateLabel | None,
    proposed: ProcessStateLabel,
) -> TransitionSignificance:
    """Measure a State change along the developmental sequence."""
    if prior is None or prior is proposed:
        return TransitionSignificance(
            changed=prior is not None and prior is not proposed, steps=0, backwards=False
        )
    order = list(archetype_states)
    delta = order.index(proposed) - order.index(prior)
    return TransitionSignificance(changed=True, steps=abs(delta), backwards=delta < 0)
