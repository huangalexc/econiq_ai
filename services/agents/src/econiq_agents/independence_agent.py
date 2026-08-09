"""The Evidence Independence agent (issue #67, agent doc §10.2).

Judges only the pairs :mod:`econiq_agents.dependence` could not settle
structurally. The structural pass has already decided anything resting on a
shared document or a shared publisher, and those are not matters of opinion —
sending them to a model would spend budget re-deriving a set intersection and
would let the model disagree with a fact.

The evaluators guard the failure that matters. §10.2's metric list ends with
"false-independence rate", but the more damaging error runs the other way: an
agent that marks genuine corroboration as dependent destroys exactly the signal
independence analysis exists to protect. Two separate observations of one
situation are what corroboration *is*, and a system that collapses them will
report a well-evidenced thesis as resting on a single source.
"""

from __future__ import annotations

from collections.abc import Sequence

from econiq_llm import Agent, EvaluationCheck, Evaluator, ModelTier
from econiq_schemas import (
    AgentInput,
    AgentOutput,
    EvidenceIndependenceInput,
    EvidenceIndependenceOutput,
)

from econiq_agents.prompts import EVIDENCE_INDEPENDENCE_V1

#: Above this share of undecided pairs called dependent, the agent is collapsing
#: corroboration rather than finding syndication. Advisory: a genuinely
#: derivative cluster can legitimately be dense, and the number to look at is
#: the rationale rather than the ratio.
COLLAPSE_RATIO = 0.6


class ScopeEvaluator:
    """Only the pairs the agent was asked about, in the direction it was given.

    Blocking. A dependence between Events that were not in the undecided set
    either contradicts the structural pass — which read the rows — or invents a
    pair, and both would corrupt the component grouping that the source count is
    computed from.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, EvidenceIndependenceOutput) or not isinstance(
            payload, EvidenceIndependenceInput
        ):
            return ()

        asked = {
            frozenset({pair.source_event_id, pair.dependent_event_id}) for pair in payload.undecided
        }
        stray = [
            (d.source_event_id, d.dependent_event_id)
            for d in output.dependencies
            if frozenset({d.source_event_id, d.dependent_event_id}) not in asked
        ]
        return (
            EvaluationCheck(
                name="pairs_were_asked_about",
                passed=not stray,
                detail=(
                    f"all {len(output.dependencies)} finding(s) are pairs the "
                    "structural pass left undecided"
                    if not stray
                    else f"{len(stray)} finding(s) about pairs not asked about: {stray[:2]}"
                ),
            ),
        )


class CorroborationEvaluator:
    """Watch for an agent collapsing independent corroboration.

    Advisory, and pointed at the more damaging of §10.2's two error directions.
    A false *dependence* silently reduces a well-evidenced thesis to one source,
    and nothing downstream reports that it happened.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, EvidenceIndependenceOutput) or not isinstance(
            payload, EvidenceIndependenceInput
        ):
            return ()
        if not payload.undecided:
            return ()

        ratio = len(output.dependencies) / len(payload.undecided)
        return (
            EvaluationCheck(
                name="corroboration_survived",
                passed=ratio <= COLLAPSE_RATIO,
                detail=(
                    f"{len(output.dependencies)} of {len(payload.undecided)} undecided "
                    f"pair(s) called dependent"
                    + (
                        ""
                        if ratio <= COLLAPSE_RATIO
                        else " — check these are syndication rather than separate "
                        "observations of one situation"
                    )
                ),
                blocking=False,
            ),
        )


class EvidenceIndependenceAgent(Agent[EvidenceIndependenceInput, EvidenceIndependenceOutput]):
    """Decides which Events rest on the same observation."""

    name = "evidence_independence"
    version = "1.0.0"
    ontology_layer = "Event"
    tier = ModelTier.REASONING

    input_schema = EvidenceIndependenceInput
    output_schema = EvidenceIndependenceOutput
    prompt = EVIDENCE_INDEPENDENCE_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (ScopeEvaluator(), CorroborationEvaluator())

    def build_user_content(self, payload: EvidenceIndependenceInput) -> str:
        lines = [f"Process: {payload.process_name}", "", "Events:"]
        for event_id, title in payload.events.items():
            lines.append(f"[{event_id}] {title}")
            publishers = payload.event_publishers.get(event_id, [])
            if publishers:
                lines.append(f"    carried by: {', '.join(publishers)}")
            for claim in payload.event_claims.get(event_id, []):
                lines.append(f"    claim: {claim}")

        lines += ["", "Decide these pairs:"]
        lines += [
            f"- {pair.source_event_id} and {pair.dependent_event_id}" for pair in payload.undecided
        ] or ["  (none — every pair was settled structurally)"]
        return "\n".join(lines)
