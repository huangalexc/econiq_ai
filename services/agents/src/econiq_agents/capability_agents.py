"""Bottleneck, Capability Mapping and Confluence agents (issue #11, agent doc §7).

The layer between "what is happening" and "what could express it". Bottleneck
Identification asks what stops the Process scaling; Capability Mapping turns
that constraint into the abilities that would resolve it; Confluence asks how
many genuinely independent Processes need the same ability.

None of these three may name a company. That prohibition is the reason the layer
exists: without it, an Event becomes a ticker in one step and nothing in between
is inspectable.
"""

from __future__ import annotations

from collections.abc import Sequence

from econiq_llm import Agent, CitationEvaluator, EvaluationCheck, Evaluator, ModelTier
from econiq_schemas import (
    AgentInput,
    AgentOutput,
    BottleneckIdentificationInput,
    BottleneckIdentificationOutput,
    CapabilityConfluenceInput,
    CapabilityConfluenceOutput,
    CapabilityMappingInput,
    CapabilityMappingOutput,
    CapabilityRole,
    ProposedGroup,
    ProposedLeaf,
    ProposedRequirement,
    SupportIndependence,
)

from econiq_agents.process_agents import LayerBoundaryEvaluator
from econiq_agents.prompts import (
    BOTTLENECK_IDENTIFICATION_V1,
    CAPABILITY_CONFLUENCE_V1,
    CAPABILITY_MAPPING_V1,
)


class BottleneckIdentificationAgent(
    Agent[BottleneckIdentificationInput, BottleneckIdentificationOutput]
):
    """Process → Bottleneck (agent doc §7.1)."""

    name = "bottleneck_identification"
    version = "1.0.0"
    ontology_layer = "Process → Bottleneck"
    tier = ModelTier.REASONING

    input_schema = BottleneckIdentificationInput
    output_schema = BottleneckIdentificationOutput
    prompt = BOTTLENECK_IDENTIFICATION_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (
            CitationEvaluator(),
            LayerBoundaryEvaluator(layer="Bottleneck"),
            BindingClarityEvaluator(),
        )

    def build_user_content(self, payload: BottleneckIdentificationInput) -> str:
        process = payload.process
        lines = [
            f"Process: {process.name}",
            f"  {process.description}",
            f"  archetype: {process.archetype.value if process.archetype else 'unclassified'}",
        ]
        if process.current_state:
            lines.append(f"  current State: {process.current_state.value}")
        if payload.state_features:
            lines += ["", "State features:"]
            lines += [
                f"- {name}: {value:.2f}" for name, value in sorted(payload.state_features.items())
            ]
        if payload.known_bottleneck_names:
            lines += [
                "",
                "Bottlenecks already recorded for this Process (reuse the name if you "
                "mean the same constraint): " + ", ".join(payload.known_bottleneck_names),
            ]
        if payload.claim_texts:
            lines += ["", "Evidence:"]
            lines += [f"- [{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)


class BindingClarityEvaluator:
    """A binding constraint needs an observation that would relieve it.

    "What would show this is no longer the constraint" is what turns a
    Bottleneck from a label into something the system can later watch and close
    out. For a constraint that only binds in future, the answer is less
    load-bearing, so it is required only of the binding ones.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, BottleneckIdentificationOutput):
            return ()
        missing = [
            candidate.name
            for candidate in output.candidates
            if candidate.currently_binding and not candidate.relief_indicators
        ]
        return (
            EvaluationCheck(
                name="binding_bottlenecks_have_relief_indicators",
                passed=not missing,
                detail=(
                    None if not missing else f"binding constraints with nothing to watch: {missing}"
                ),
            ),
        )


class CapabilityMappingAgent(Agent[CapabilityMappingInput, CapabilityMappingOutput]):
    """Bottleneck → Capability Requirement (agent doc §7.2, ontology §12)."""

    name = "capability_mapping"
    version = "1.0.0"
    ontology_layer = "Bottleneck → Capability Requirement"
    tier = ModelTier.REASONING

    input_schema = CapabilityMappingInput
    output_schema = CapabilityMappingOutput
    prompt = CAPABILITY_MAPPING_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (
            CitationEvaluator(),
            LayerBoundaryEvaluator(layer="Capability"),
            RequirementStructureEvaluator(),
        )

    def build_user_content(self, payload: CapabilityMappingInput) -> str:
        lines = [
            f"Process: {payload.process.name}",
            f"  {payload.process.description}",
            "",
            f"Bottleneck: {payload.bottleneck_name} ({payload.bottleneck_kind.value})",
            f"  {payload.bottleneck_description}",
        ]
        if payload.known_capabilities:
            lines += [
                "",
                "Existing Capabilities — reuse the exact name where one already means "
                "what you mean:",
            ]
            lines += [f"- {name}" for name in payload.known_capabilities]
        if payload.claim_texts:
            lines += ["", "Evidence:"]
            lines += [f"- [{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)


class RequirementStructureEvaluator:
    """The requirement tree has to carry information a flat list would not.

    A tree of one OR group over everything says "any of these will do", which is
    almost never true of a real Bottleneck and is what a model produces when it
    has not thought about structure. Flagging it is cheap; discovering it later
    through a nonsensical Asset universe is not.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, CapabilityMappingOutput):
            return ()
        tree = output.requirement_tree
        if tree is None:
            return ()

        necessary = [c.ref for c in output.capabilities if c.role is CapabilityRole.NECESSARY]
        leaves = {leaf.ref: leaf for leaf in _leaves(tree)}
        optional_necessary = sorted(
            ref for ref in necessary if ref in leaves and leaves[ref].necessity.value == "optional"
        )
        return (
            EvaluationCheck(
                name="necessary_capabilities_are_not_optional",
                passed=not optional_necessary,
                detail=(
                    None
                    if not optional_necessary
                    else f"declared necessary but optional in the tree: {optional_necessary}"
                ),
            ),
            EvaluationCheck(
                name="requirement_tree_is_not_a_flat_or",
                passed=not _is_flat_or(tree, len(output.capabilities)),
                detail=(
                    None
                    if not _is_flat_or(tree, len(output.capabilities))
                    else "every Capability sits under a single OR — no structure was expressed"
                ),
            ),
        )


def _leaves(node: ProposedRequirement) -> list[ProposedLeaf]:
    if isinstance(node, ProposedLeaf):
        return [node]
    out: list[ProposedLeaf] = []
    for child in node.children:
        out.extend(_leaves(child))
    return out


def _is_flat_or(node: ProposedRequirement, capability_count: int) -> bool:
    if capability_count < 2 or not isinstance(node, ProposedGroup):
        return False
    return (
        node.operator.value == "or"
        and len(node.children) == capability_count
        and all(isinstance(child, ProposedLeaf) for child in node.children)
    )


class CapabilityConfluenceAgent(Agent[CapabilityConfluenceInput, CapabilityConfluenceOutput]):
    """Capability → upstream independence (agent doc §7.3, ontology §13).

    A Capability required by three independent Processes is a different object
    from one required by three facets of the same development, and only the
    graph structure makes that visible — which is why Capabilities are shared
    nodes rather than being duplicated per Process.
    """

    name = "capability_confluence"
    version = "1.0.0"
    ontology_layer = "Capability"
    tier = ModelTier.STANDARD

    input_schema = CapabilityConfluenceInput
    output_schema = CapabilityConfluenceOutput
    prompt = CAPABILITY_CONFLUENCE_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (LayerBoundaryEvaluator(layer="Capability"), ConfluenceScopeEvaluator())

    def build_user_content(self, payload: CapabilityConfluenceInput) -> str:
        lines = [
            f"Capability: {payload.capability_name}",
            f"  {payload.capability_description}",
            "",
            "Processes that require it:",
        ]
        for process in payload.candidate_processes:
            archetype = process.archetype.value if process.archetype else "unclassified"
            lines.append(
                f"- [{process.process_id}] {process.name} ({archetype})\n    {process.description}"
            )
        return "\n".join(lines)


class ConfluenceScopeEvaluator:
    """The agent may only classify Processes it was shown.

    Independence is counted from this classification, so a Process that appears
    in the answer but not the question would inflate the count with something
    nobody can check.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(payload, CapabilityConfluenceInput) or not isinstance(
            output, CapabilityConfluenceOutput
        ):
            return ()
        offered = {process.process_id for process in payload.candidate_processes}
        invented = sorted({u.process_id for u in output.upstream} - offered)
        unpaired = sorted(
            {
                process_id
                for interaction in output.interactions
                for process_id in (interaction.process_id_a, interaction.process_id_b)
            }
            - offered
        )
        return (
            EvaluationCheck(
                name="upstream_processes_were_offered",
                passed=not invented,
                detail=None if not invented else f"processes not supplied: {invented}",
            ),
            EvaluationCheck(
                name="interactions_reference_offered_processes",
                passed=not unpaired,
                detail=None if not unpaired else f"interactions reference unknown: {unpaired}",
            ),
        )


def independent_support(output: CapabilityConfluenceOutput) -> tuple[int, tuple[str, ...]]:
    """Count independent upstream support, and name who provided it.

    Derived from the agent's classification rather than taken from it (ontology
    §13): correlated and redundant support does not count, which is the same
    rule the Event layer applies to syndicated reporting.
    """
    independent = tuple(
        support.process_id
        for support in output.upstream
        if support.independence is SupportIndependence.INDEPENDENT
    )
    return len(independent), independent
