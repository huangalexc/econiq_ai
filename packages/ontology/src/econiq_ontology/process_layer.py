"""Process → State → Bottleneck → Capability (ontology §7–§13).

Processes, not stocks, are the unit of research. A Process is a persistent
latent object that accumulates evidence over time; its State says where it sits
in its lifecycle; its Bottlenecks say what constrains it; Capabilities are the
bridge from the constraint to something investable.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from econiq_ontology.archetypes import ProcessStateLabel, state_machine
from econiq_ontology.base import (
    Confidence,
    Entity,
    OntologyModel,
    Score10,
    TemporalObservation,
    Weight,
)
from econiq_ontology.enums import (
    BottleneckKind,
    EntityType,
    LogicOperator,
    Necessity,
    ProcessArchetype,
    ProcessStatus,
)
from econiq_ontology.provenance import AgentAttribution, EvidenceRef


class Process(Entity):
    """An evolving real-world causal or structural development (ontology §7).

    ``archetype`` is what makes the State meaningful, so it is classified before
    State estimation (agent doc §6.3 → §6.4). Drivers and Mechanisms are *not*
    fields here: they are roles in relationships between Processes (ontology
    §9), so a Process can be a Driver in one edge and a Mechanism in another
    without duplicating nodes.
    """

    entity_type: Literal[EntityType.PROCESS] = EntityType.PROCESS

    name: str = Field(min_length=1)
    slug: str = Field(
        pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$",
        description="Stable human-readable key, e.g. 'ai-infrastructure-expansion'.",
    )
    description: str
    archetype: ProcessArchetype | None = Field(
        default=None, description="None until the Archetype agent has classified it."
    )
    archetype_confidence: Confidence | None = None
    status: ProcessStatus = ProcessStatus.CANDIDATE
    originating_event_ids: list[uuid.UUID] = Field(default_factory=list)
    merged_into: uuid.UUID | None = Field(
        default=None, description="Set when this Process is merged into another."
    )
    attribution: AgentAttribution | None = None

    @model_validator(mode="after")
    def _archetype_confidence_requires_archetype(self) -> Self:
        if self.archetype_confidence is not None and self.archetype is None:
            raise ValueError("archetype_confidence set without an archetype")
        if self.status is ProcessStatus.MERGED and self.merged_into is None:
            raise ValueError("merged Process must record merged_into")
        return self


class StateFeature(OntologyModel):
    """One observable characteristic of a Process State (ontology §10).

    Example: ``capex_acceleration = 8.7``. Features are quantitative
    observations; the LLM may identify which features matter and interpret them,
    but the values should come from measurement wherever measurement is
    possible (ontology §2.4).
    """

    name: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    value: Score10
    basis: Literal["measured", "estimated"] = Field(
        default="estimated",
        description="'measured' means computed from data, not asserted by an LLM.",
    )
    rationale: str | None = None


class ProcessState(TemporalObservation):
    """Where a Process sits in its lifecycle, as believed at a point in time.

    Append-only: a new estimate never overwrites an old one, which is what makes
    the State history reconstructible (ui_concept §32).

    ``transition_beliefs`` is deliberately *not* named "transition_probabilities"
    as in ontology §10: until the calibration framework (P3.09) validates them,
    these are model beliefs and must not be described as probabilities
    (ontology §35, agent doc §2.5). Rename when calibration lands.
    """

    process_id: uuid.UUID
    archetype: ProcessArchetype
    categorical_state: ProcessStateLabel
    state_confidence: Confidence
    features: list[StateFeature] = Field(default_factory=list)
    transition_beliefs: dict[ProcessStateLabel, Confidence] = Field(
        default_factory=dict,
        description="Belief that the Process moves to each State next. Uncalibrated.",
    )
    evidence: list[EvidenceRef] = Field(default_factory=list)
    previous_state_id: uuid.UUID | None = None
    attribution: AgentAttribution | None = None

    @model_validator(mode="after")
    def _state_legal_for_archetype(self) -> Self:
        machine = state_machine(self.archetype)
        machine.require(self.categorical_state)
        for target in self.transition_beliefs:
            machine.require(target)
            if not machine.can_transition(self.categorical_state, target):
                raise ValueError(
                    f"{self.categorical_state.value!r} cannot transition to "
                    f"{target.value!r} under archetype {self.archetype.value!r}"
                )
        names = [f.name for f in self.features]
        if len(names) != len(set(names)):
            raise ValueError("duplicate state feature names")
        return self


class BottleneckMetrics(OntologyModel):
    """The Bottleneck scorecard shown in the Bottleneck view (ui_concept §10)."""

    demand_pressure: Score10 | None = None
    supply_elasticity: Score10 | None = None
    time_to_expand: Score10 | None = None
    current_constraint: Score10 | None = None


class Bottleneck(Entity):
    """What constrains further progression of a Process (ontology §11).

    Made explicit as its own layer rather than hidden inside Asset selection —
    "what prevents the Process from scaling" is often more actionable than the
    Process itself.
    """

    entity_type: Literal[EntityType.BOTTLENECK] = EntityType.BOTTLENECK

    process_id: uuid.UUID
    name: str = Field(min_length=1)
    description: str
    kind: BottleneckKind
    metrics: BottleneckMetrics = Field(default_factory=BottleneckMetrics)
    confidence: Confidence
    evidence: list[EvidenceRef] = Field(default_factory=list)
    resolved: bool = Field(default=False, description="True once the constraint no longer binds.")
    attribution: AgentAttribution | None = None


class Capability(Entity):
    """A concrete economic capability required to satisfy a Bottleneck or
    participate in a Process (ontology §12).

    Capabilities are shared nodes: multiple upstream Processes may feed one
    Capability, and that confluence (ontology §13) is only visible if the graph
    structure is preserved rather than collapsed into a single thesis. Which is
    why upstream Processes are edges, not a field here.
    """

    entity_type: Literal[EntityType.CAPABILITY] = EntityType.CAPABILITY

    name: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    description: str
    aliases: list[str] = Field(default_factory=list)
    attribution: AgentAttribution | None = None


class CapabilityLeaf(OntologyModel):
    """A single Capability inside a requirement tree."""

    node: Literal["capability"] = "capability"
    capability_id: uuid.UUID
    necessity: Necessity = Necessity.REQUIRED
    weight: Weight = Field(default=1.0, description="Relative importance within its parent group.")
    rationale: str | None = None


class RequirementGroup(OntologyModel):
    """A logical combination of requirements.

    Ontology §12 is explicit that ``A AND B`` must be representable, not only
    ``A OR B``: domestic strategic-mineral security requires domestic production
    *and* mineral processing, and an Asset satisfying only one of them is a
    different investment case.
    """

    node: Literal["group"] = "group"
    operator: LogicOperator
    children: list[RequirementNode] = Field(min_length=1)
    necessity: Necessity = Necessity.REQUIRED
    weight: Weight = 1.0
    label: str | None = None


RequirementNode = Annotated[CapabilityLeaf | RequirementGroup, Field(discriminator="node")]

RequirementGroup.model_rebuild()


def _iter_leaves(node: RequirementNode) -> Iterator[CapabilityLeaf]:
    if isinstance(node, CapabilityLeaf):
        yield node
        return
    for child in node.children:
        yield from _iter_leaves(child)


def _satisfied(node: RequirementNode, available: frozenset[uuid.UUID]) -> bool:
    if isinstance(node, CapabilityLeaf):
        return node.capability_id in available
    required = [c for c in node.children if c.necessity is Necessity.REQUIRED]
    # An OPTIONAL child never blocks satisfaction; a group of only optional
    # children is vacuously satisfied.
    if not required:
        return True
    if node.operator is LogicOperator.AND:
        return all(_satisfied(c, available) for c in required)
    return any(_satisfied(c, available) for c in required)


def _coverage(node: RequirementNode, available: frozenset[uuid.UUID]) -> float:
    """Weighted fraction of the tree that ``available`` covers, in [0, 1]."""
    if isinstance(node, CapabilityLeaf):
        return 1.0 if node.capability_id in available else 0.0
    total = sum(c.weight for c in node.children)
    if total == 0:
        return 0.0
    scores = [(c.weight / total, _coverage(c, available)) for c in node.children]
    if node.operator is LogicOperator.AND:
        return sum(w * s for w, s in scores)
    return max(s for _, s in scores)


class CapabilityRequirement(Entity):
    """The requirement structure attached to a Bottleneck or a Process.

    Evaluation is deterministic (``is_satisfied_by`` / ``coverage``): the LLM
    proposes the structure, code decides whether a candidate satisfies it
    (agent doc §2.3).
    """

    bottleneck_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None
    root: RequirementNode
    attribution: AgentAttribution | None = None

    @model_validator(mode="after")
    def _anchored(self) -> Self:
        if self.bottleneck_id is None and self.process_id is None:
            raise ValueError("a CapabilityRequirement must anchor to a Bottleneck or Process")
        return self

    def leaves(self) -> tuple[CapabilityLeaf, ...]:
        return tuple(_iter_leaves(self.root))

    def capability_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(leaf.capability_id for leaf in self.leaves())

    def is_satisfied_by(self, capability_ids: frozenset[uuid.UUID]) -> bool:
        """Whether a set of Capabilities satisfies the required structure."""
        return _satisfied(self.root, capability_ids)

    def coverage(self, capability_ids: frozenset[uuid.UUID]) -> float:
        """Weighted coverage in [0, 1] — a partial-fit measure for ranking."""
        return _coverage(self.root, capability_ids)
