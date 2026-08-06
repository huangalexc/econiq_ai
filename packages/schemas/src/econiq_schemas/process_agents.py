"""Process Discovery, Update, Archetype, State and Critic agents (agent doc §6).

Each of these agents stops at the Process layer. None of them names an Asset —
that boundary is the reason the ontology has intermediate layers at all
(agent doc §2.1).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from econiq_ontology import (
    Confidence,
    CritiqueKind,
    ProcessArchetype,
    ProcessStateLabel,
    Score10,
    state_machine,
)
from pydantic import Field, model_validator

from econiq_schemas.base import AgentInput, AgentIO, AgentOutput, Cited


class ProcessSummary(AgentIO):
    """An existing Process as shown to an agent, in the form it may reason about."""

    process_id: str
    name: str
    description: str
    archetype: ProcessArchetype | None = None
    current_state: ProcessStateLabel | None = None
    state_confidence: Confidence | None = None


class EventSummary(AgentIO):
    event_id: str
    title: str
    description: str
    timestamp: datetime
    materiality: Score10
    novelty: Score10
    supporting_claim_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 6.1 Process Discovery
# --------------------------------------------------------------------------- #


class ProcessImplication(StrEnum):
    """The four possible verdicts of §6.1."""

    CREATES_NEW_PROCESS = "creates_new_process"
    MATERIALLY_CHANGES = "materially_changes"
    PROVIDES_EVIDENCE = "provides_evidence"
    NO_IMPLICATION = "no_implication"


class ProposedProcess(Cited):
    """A Process the agent believes should exist but does not yet."""

    name: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    description: str = Field(min_length=1)
    suggested_archetype: ProcessArchetype | None = Field(
        default=None,
        description="A hint only. Archetype classification is §6.3's job, not this agent's.",
    )
    causal_mechanism: str = Field(
        min_length=1, description="How the Event gives rise to this Process."
    )
    confidence: Confidence


class ProcessAffected(Cited):
    """An existing Process the Event bears on."""

    process_id: str
    implication: ProcessImplication
    causal_mechanism: str = Field(min_length=1)
    direction: str = Field(description="Whether the Event advances or retards the Process.")
    confidence: Confidence

    @model_validator(mode="after")
    def _implication_is_actually_an_effect(self) -> Self:
        if self.implication is ProcessImplication.CREATES_NEW_PROCESS:
            raise ValueError("use ProposedProcess for new Processes")
        return self


class ProcessDiscoveryInput(AgentInput):
    event: EventSummary
    claim_texts: dict[str, str] = Field(
        default_factory=dict, description="Claim id → text, for citation."
    )
    existing_processes: list[ProcessSummary] = Field(default_factory=list)


class ProcessDiscoveryOutput(AgentOutput):
    """§6.1: "Do not identify stocks yet." There is no Asset field here."""

    new_processes: list[ProposedProcess] = Field(default_factory=list)
    affected_processes: list[ProcessAffected] = Field(default_factory=list)
    unaffected_process_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 6.2 Process Update
# --------------------------------------------------------------------------- #


class FeatureDelta(AgentIO):
    """A change to one State feature, e.g. ``demand_acceleration +0.08``."""

    name: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    delta: float = Field(ge=-10.0, le=10.0)
    rationale: str = Field(min_length=1)


class BeliefChange(AgentIO):
    statement: str = Field(min_length=1)
    direction: str = Field(description="strengthened | weakened | unchanged")
    rationale: str = Field(min_length=1)


class ProcessUpdateInput(AgentInput):
    process: ProcessSummary
    current_features: dict[str, Score10] = Field(default_factory=dict)
    event: EventSummary
    claim_texts: dict[str, str] = Field(default_factory=dict)
    open_bottleneck_names: list[str] = Field(default_factory=list)


class ProcessUpdateOutput(AgentOutput, Cited):
    """A delta, never a rewrite (agent doc §6.2).

    Applying deltas rather than regenerating the thesis is what makes the belief
    history meaningful: a Process that has held the same State through fifteen
    Events is a different object from one re-derived fifteen times.
    """

    belief_changes: list[BeliefChange] = Field(default_factory=list)
    feature_deltas: list[FeatureDelta] = Field(default_factory=list)
    state_change_recommended: bool = False
    proposed_state: ProcessStateLabel | None = None
    confidence_after: Confidence
    bottlenecks_may_have_changed: bool = False
    capabilities_may_have_changed: bool = False
    contradicts_existing_beliefs: bool = False

    @model_validator(mode="after")
    def _changes_are_cited_and_coherent(self) -> Self:
        changed = bool(self.belief_changes or self.feature_deltas) or self.state_change_recommended
        if changed and not self.supporting_claim_ids:
            # §6.2: "Every update must cite supporting Claims."
            raise ValueError("a Process update must cite supporting Claims")
        if self.state_change_recommended and self.proposed_state is None:
            raise ValueError("state_change_recommended requires proposed_state")
        if self.proposed_state is not None and not self.state_change_recommended:
            raise ValueError("proposed_state set without recommending a state change")
        names = [d.name for d in self.feature_deltas]
        if len(names) != len(set(names)):
            raise ValueError("duplicate feature deltas")
        return self


# --------------------------------------------------------------------------- #
# 6.3 Process Archetype
# --------------------------------------------------------------------------- #


class RejectedArchetype(AgentIO):
    archetype: ProcessArchetype
    reason: str = Field(min_length=1)


class ProcessArchetypeInput(AgentInput):
    process: ProcessSummary
    recent_event_summaries: list[str] = Field(default_factory=list)
    claim_texts: dict[str, str] = Field(default_factory=dict)


class ProcessArchetypeOutput(AgentOutput, Cited):
    """§6.3 requires rejected alternatives, not just a pick.

    Forcing the model to say why the other four archetypes are wrong is the
    check against choosing whichever archetype yields the nicest narrative.
    """

    primary_archetype: ProcessArchetype
    secondary_archetypes: list[ProcessArchetype] = Field(default_factory=list)
    rejected: list[RejectedArchetype] = Field(min_length=1)
    reasons: str = Field(min_length=1)
    confidence: Confidence

    @model_validator(mode="after")
    def _primary_not_also_rejected(self) -> Self:
        rejected = {r.archetype for r in self.rejected}
        if self.primary_archetype in rejected:
            raise ValueError("primary archetype appears in rejected list")
        if self.primary_archetype in self.secondary_archetypes:
            raise ValueError("primary archetype repeated as secondary")
        if rejected & set(self.secondary_archetypes):
            raise ValueError("an archetype cannot be both secondary and rejected")
        return self


# --------------------------------------------------------------------------- #
# 6.4 Process State
# --------------------------------------------------------------------------- #


class ProposedFeature(AgentIO):
    name: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    value: Score10
    rationale: str = Field(min_length=1)


class ProcessStateInput(AgentInput):
    process: ProcessSummary
    archetype: ProcessArchetype
    permitted_states: list[ProcessStateLabel] = Field(
        min_length=1, description="The archetype's State vocabulary — the only legal answers."
    )
    measured_features: dict[str, float] = Field(
        default_factory=dict,
        description="Quantitatively measured features. The agent interprets, it does not invent.",
    )
    claim_texts: dict[str, str] = Field(default_factory=dict)
    prior_state: ProcessStateLabel | None = None


class ProcessStateOutput(AgentOutput, Cited):
    """§6.4: "Do not estimate stock returns."

    ``transition_beliefs`` are model beliefs, not probabilities, until
    calibration (ontology §35). Every entry is validated against the archetype's
    State machine, so an illegal transition fails at the boundary rather than
    reaching the database.
    """

    archetype: ProcessArchetype
    categorical_state: ProcessStateLabel
    state_confidence: Confidence
    features: list[ProposedFeature] = Field(default_factory=list)
    transition_beliefs: dict[ProcessStateLabel, Confidence] = Field(default_factory=dict)
    transition_indicators: list[str] = Field(
        default_factory=list, description="What would signal the next State is arriving."
    )
    reversal_indicators: list[str] = Field(
        default_factory=list, description="What would signal the Process is regressing."
    )

    @model_validator(mode="after")
    def _state_legal_for_archetype(self) -> Self:
        machine = state_machine(self.archetype)
        machine.require(self.categorical_state)
        for target in self.transition_beliefs:
            if not machine.can_transition(self.categorical_state, target):
                raise ValueError(
                    f"{self.categorical_state.value!r} cannot transition to {target.value!r} "
                    f"under archetype {self.archetype.value!r}"
                )
        names = [f.name for f in self.features]
        if len(names) != len(set(names)):
            raise ValueError("duplicate features")
        return self


# --------------------------------------------------------------------------- #
# 6.5 Process Critic
# --------------------------------------------------------------------------- #


class Critique(Cited):
    kind: CritiqueKind
    statement: str = Field(min_length=1)
    severity: Score10 = Field(description="How much this would damage the thesis if true.")
    rationale: str = Field(min_length=1)
    testable_with: str | None = Field(default=None, description="What observation would settle it.")


class ProcessCriticInput(AgentInput):
    process: ProcessSummary
    thesis_statement: str
    supporting_event_summaries: list[str] = Field(default_factory=list)
    claim_texts: dict[str, str] = Field(default_factory=dict)


class ProcessCriticOutput(AgentOutput):
    """Adversarial by construction (agent doc §6.5).

    There is deliberately no field in which the critic can rescue the thesis:
    the schema has no "mitigations" and no overall verdict in the thesis's
    favour. LLMs are good at building coherent narratives, so the critic's only
    permitted move is to attack.
    """

    critiques: list[Critique] = Field(default_factory=list)
    falsification_risk: Score10 = Field(
        description="How exposed the Process is to being wrong, given the critiques."
    )
    most_damaging_critique_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _index_in_range(self) -> Self:
        idx = self.most_damaging_critique_index
        if idx is not None and idx >= len(self.critiques):
            raise ValueError("most_damaging_critique_index out of range")
        if self.critiques and idx is None:
            raise ValueError("name the most damaging critique when critiques are present")
        return self
