"""Bottleneck, Capability Mapping and Confluence agents (agent doc §7).

These agents sit between the Process and Asset layers and must not cross into
either: §7.2 is explicit — "Do not identify companies yet."
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from econiq_ontology import (
    BottleneckKind,
    Confidence,
    LogicOperator,
    Necessity,
    ProcessArchetype,
    ProcessStateLabel,
    Score10,
    Weight,
)
from pydantic import Field, model_validator

from econiq_schemas.base import AgentInput, AgentIO, AgentOutput, Cited


class ProcessContext(AgentIO):
    process_id: str
    name: str
    description: str
    archetype: ProcessArchetype | None = None
    current_state: ProcessStateLabel | None = None


# --------------------------------------------------------------------------- #
# 7.1 Bottleneck Identification
# --------------------------------------------------------------------------- #


class ProposedBottleneck(Cited):
    """A candidate constraint.

    ``currently_binding`` is the distinction §7.1 insists on: a constraint that
    *will* bind in three years is a different object from one binding now, and
    conflating them is how a research system talks itself into early positions.
    """

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: BottleneckKind
    why_limiting: str = Field(min_length=1)
    currently_binding: bool
    demand_pressure: Score10 | None = None
    supply_elasticity: Score10 | None = None
    time_to_expand: Score10 | None = None
    current_constraint: Score10 | None = None
    relief_indicators: list[str] = Field(
        default_factory=list,
        description="Observations that would prove the constraint has been relieved.",
    )
    confidence: Confidence


class BottleneckIdentificationInput(AgentInput):
    process: ProcessContext
    state_features: dict[str, float] = Field(default_factory=dict)
    claim_texts: dict[str, str] = Field(default_factory=dict)
    known_bottleneck_names: list[str] = Field(default_factory=list)


class BottleneckIdentificationOutput(AgentOutput):
    candidates: list[ProposedBottleneck] = Field(default_factory=list)
    binding_candidate_index: int | None = Field(
        default=None, ge=0, description="The one the agent judges currently binding."
    )

    @model_validator(mode="after")
    def _binding_index_is_consistent(self) -> Self:
        idx = self.binding_candidate_index
        if idx is None:
            return self
        if idx >= len(self.candidates):
            raise ValueError("binding_candidate_index out of range")
        if not self.candidates[idx].currently_binding:
            raise ValueError("binding_candidate_index points at a non-binding candidate")
        return self


# --------------------------------------------------------------------------- #
# 7.2 Capability Mapping
# --------------------------------------------------------------------------- #


class CapabilityRole(StrEnum):
    """§7.2 — necessary / sufficient / complementary / substitute."""

    NECESSARY = "necessary"
    SUFFICIENT = "sufficient"
    COMPLEMENTARY = "complementary"
    SUBSTITUTE = "substitute"


class ProposedCapability(Cited):
    """A Capability proposed by name. Ids are assigned on persistence, after
    matching against existing Capabilities."""

    ref: str = Field(
        pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$",
        description="Local reference used by the requirement tree in this output.",
    )
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    role: CapabilityRole
    confidence: Confidence


class ProposedLeaf(AgentIO):
    node: Literal["capability"] = "capability"
    ref: str = Field(description="Must match a ProposedCapability.ref in the same output.")
    necessity: Necessity = Necessity.REQUIRED
    weight: Weight = 1.0


class ProposedGroup(AgentIO):
    node: Literal["group"] = "group"
    operator: LogicOperator
    children: list[ProposedRequirement] = Field(min_length=1)
    necessity: Necessity = Necessity.REQUIRED
    weight: Weight = 1.0
    label: str | None = None


ProposedRequirement = Annotated[ProposedLeaf | ProposedGroup, Field(discriminator="node")]

ProposedGroup.model_rebuild()


def _refs(node: ProposedRequirement) -> set[str]:
    if isinstance(node, ProposedLeaf):
        return {node.ref}
    out: set[str] = set()
    for child in node.children:
        out |= _refs(child)
    return out


class CapabilityMappingInput(AgentInput):
    process: ProcessContext
    bottleneck_name: str
    bottleneck_description: str
    bottleneck_kind: BottleneckKind
    claim_texts: dict[str, str] = Field(default_factory=dict)
    known_capabilities: list[str] = Field(
        default_factory=list, description="Existing Capability names, to encourage reuse."
    )


class CapabilityMappingOutput(AgentOutput):
    """The logical structure is the point (ontology §12).

    "Domestic production AND mineral processing" and "domestic production OR
    mineral processing" imply completely different Asset universes, so the tree
    is returned explicitly rather than as a flat list.
    """

    capabilities: list[ProposedCapability] = Field(default_factory=list)
    requirement_tree: ProposedRequirement | None = None

    @model_validator(mode="after")
    def _tree_refs_resolve(self) -> Self:
        declared = [c.ref for c in self.capabilities]
        if len(declared) != len(set(declared)):
            raise ValueError("duplicate capability refs")
        if self.requirement_tree is None:
            if self.capabilities:
                raise ValueError("capabilities proposed without a requirement structure")
            return self
        used = _refs(self.requirement_tree)
        unknown = used - set(declared)
        if unknown:
            raise ValueError(f"requirement tree references unknown refs: {sorted(unknown)}")
        unused = set(declared) - used
        if unused:
            raise ValueError(f"capabilities missing from the requirement tree: {sorted(unused)}")
        return self


# --------------------------------------------------------------------------- #
# 7.3 Capability Confluence
# --------------------------------------------------------------------------- #


class SupportIndependence(StrEnum):
    """§7.3 — "Do not count multiple reports from the same Process as
    independent support." """

    INDEPENDENT = "independent"
    CORRELATED = "correlated"
    REDUNDANT = "redundant"


class UpstreamSupport(Cited):
    process_id: str
    independence: SupportIndependence
    support_strength: Score10
    rationale: str = Field(min_length=1)


class ProcessInteraction(AgentIO):
    process_id_a: str
    process_id_b: str
    interaction: str = Field(description="reinforcing | interfering")
    rationale: str = Field(min_length=1)


class CapabilityConfluenceInput(AgentInput):
    capability_id: str
    capability_name: str
    capability_description: str
    candidate_processes: list[ProcessContext] = Field(default_factory=list)


class CapabilityConfluenceOutput(AgentOutput):
    """Confluence is a graph property, so the agent classifies independence and
    code counts it — never the reverse (ontology §13)."""

    upstream: list[UpstreamSupport] = Field(default_factory=list)
    interactions: list[ProcessInteraction] = Field(default_factory=list)

    @property
    def independent_support_count(self) -> int:
        """Derived, not asserted: how many genuinely independent Processes
        support this Capability."""
        return sum(1 for u in self.upstream if u.independence is SupportIndependence.INDEPENDENT)
