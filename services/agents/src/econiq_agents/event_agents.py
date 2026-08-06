"""Event Resolution and Event Significance agents (issue #7, agent doc §5).

The compression layer. Everything upstream is per-document; everything
downstream is per-Event, and the ratio between them is the whole point:
one hundred documents become twenty-five Claims become one Event (ontology §6).

Two things are deliberately taken away from the model:

* **How many independent sources back a cluster.** The agent names publishers;
  ``econiq_agents.independence`` decides what that is worth.
* **Whether an Event propagates.** The agent scores significance;
  ``PropagationPolicy`` applies the threshold. A model that could set its own
  trigger bar would drift it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from econiq_llm import Agent, EvaluationCheck, Evaluator, ModelTier
from econiq_schemas import (
    AgentInput,
    AgentOutput,
    EventResolutionInput,
    EventResolutionOutput,
    EventSignificanceInput,
    EventSignificanceOutput,
)

from econiq_agents.prompts import EVENT_RESOLUTION_V1, EVENT_SIGNIFICANCE_V1


class EventResolutionAgent(Agent[EventResolutionInput, EventResolutionOutput]):
    """Claims → canonical Events (agent doc §5.1).

    Runs on the reasoning tier: a false merge silently destroys evidence and a
    false split silently inflates it, and both are hard to detect downstream.
    """

    name = "event_resolution"
    version = "1.0.0"
    ontology_layer = "Claim → Event"
    tier = ModelTier.REASONING

    input_schema = EventResolutionInput
    output_schema = EventResolutionOutput
    prompt = EVENT_RESOLUTION_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (ClusterPartitionEvaluator(),)

    def build_user_content(self, payload: EventResolutionInput) -> str:
        lines = ["Claims:"]
        for claim in payload.claims:
            entities = ", ".join(entity.text for entity in claim.entities)
            lines.append(
                f"- [{claim.claim_id}] ({claim.publisher or 'unknown publisher'}, "
                f"{claim.publication_time.date().isoformat()}) {claim.text}"
                + (f" [entities: {entities}]" if entities else "")
            )
        if payload.known_events:
            lines.append("")
            lines.append("Known Events this evidence might belong to:")
            for event in payload.known_events:
                lines.append(
                    f"- [{event.event_id}] ({event.event_type.value}, "
                    f"{event.timestamp.date().isoformat()}) {event.title}"
                )
        return "\n".join(lines)


class ClusterPartitionEvaluator:
    """Every Claim shown must be accounted for exactly once.

    A Claim that appears in two clusters has been double-counted as evidence; a
    Claim that appears in none has been silently dropped. Both are checkable, so
    neither is left to review.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(payload, EventResolutionInput) or not isinstance(
            output, EventResolutionOutput
        ):
            return ()

        supplied = {claim.claim_id for claim in payload.claims}
        assigned: list[str] = []
        for event in output.events:
            assigned.extend(event.supporting_claim_ids)
        assigned.extend(output.unassigned_claim_ids)

        duplicated = sorted({cid for cid in assigned if assigned.count(cid) > 1})
        invented = sorted(set(assigned) - supplied)
        dropped = sorted(supplied - set(assigned))

        return (
            EventResolutionCheck.no_double_counting(duplicated),
            EventResolutionCheck.no_invented_claims(invented),
            EventResolutionCheck.nothing_dropped(dropped),
        )


class EventResolutionCheck:
    """Named constructors for the partition checks, so failures read clearly."""

    @staticmethod
    def no_double_counting(duplicated: list[str]) -> EvaluationCheck:
        return EvaluationCheck(
            name="claims_assigned_once",
            passed=not duplicated,
            detail=None if not duplicated else f"claims in more than one cluster: {duplicated}",
        )

    @staticmethod
    def no_invented_claims(invented: list[str]) -> EvaluationCheck:
        return EvaluationCheck(
            name="claim_ids_resolve",
            passed=not invented,
            detail=None if not invented else f"claim ids not supplied to the agent: {invented}",
        )

    @staticmethod
    def nothing_dropped(dropped: list[str]) -> EvaluationCheck:
        return EvaluationCheck(
            name="claims_accounted_for",
            passed=not dropped,
            detail=None if not dropped else f"claims neither clustered nor unassigned: {dropped}",
        )


class EventSignificanceAgent(Agent[EventSignificanceInput, EventSignificanceOutput]):
    """Decides whether an Event is worth propagating (agent doc §5.2).

    Standard tier: it runs on every Event, and its output is scores that a
    deterministic policy then acts on.
    """

    name = "event_significance"
    version = "1.0.0"
    ontology_layer = "Event"
    tier = ModelTier.STANDARD

    input_schema = EventSignificanceInput
    output_schema = EventSignificanceOutput
    prompt = EVENT_SIGNIFICANCE_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return ()

    def build_user_content(self, payload: EventSignificanceInput) -> str:
        lines = [
            f"Event: {payload.title}",
            f"Type: {payload.event_type.value}",
            f"Occurred: {payload.timestamp.isoformat()}",
            f"Independent sources: {payload.independent_source_count}",
            "",
            payload.description,
        ]
        if payload.related_process_summaries:
            lines += ["", "Processes this may bear on:"]
            lines += [f"- {summary}" for summary in payload.related_process_summaries]
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class PropagationDecision:
    propagate: bool
    reason: str
    materiality: float
    novelty: float
    credibility: float


@dataclass(frozen=True, slots=True)
class PropagationPolicy:
    """The deterministic gate on Process updates (ontology §46).

    The agent's recommendation is necessary but not sufficient. Thresholds live
    here — in code, versioned, and tunable against the evaluation corpus —
    because a trigger bar that drifts with prompt wording is a trigger bar
    nobody can reason about.

    A single-source Event is held back regardless of how material it looks:
    "Events should accumulate documents until a materiality threshold is
    reached" (ontology §46), and one report is not accumulation. The Event is
    still stored; only propagation waits.
    """

    min_materiality: float = 5.0
    min_credibility: float = 5.0
    min_novelty: float = 3.0
    min_independent_sources: int = 2
    #: Materiality high enough to propagate on a single source anyway. A
    #: regulator publishing a final rule needs no corroboration.
    single_source_materiality_override: float = 8.5

    def decide(
        self, significance: EventSignificanceOutput, *, independent_source_count: int
    ) -> PropagationDecision:
        materiality = significance.economic_materiality.value
        novelty = significance.novelty.value
        credibility = significance.credibility.value

        def held(reason: str) -> PropagationDecision:
            return PropagationDecision(False, reason, materiality, novelty, credibility)

        if not significance.should_trigger_update:
            return held("the significance agent did not recommend an update")
        if credibility < self.min_credibility:
            return held(f"credibility {credibility:.1f} below {self.min_credibility:.1f}")
        if materiality < self.min_materiality:
            return held(f"materiality {materiality:.1f} below {self.min_materiality:.1f}")
        if novelty < self.min_novelty:
            return held(f"novelty {novelty:.1f} below {self.min_novelty:.1f} — already known")
        if (
            independent_source_count < self.min_independent_sources
            and materiality < self.single_source_materiality_override
        ):
            return held(f"only {independent_source_count} independent source(s); accumulating")
        return PropagationDecision(
            True,
            f"materiality {materiality:.1f}, credibility {credibility:.1f}, "
            f"{independent_source_count} independent source(s)",
            materiality,
            novelty,
            credibility,
        )
