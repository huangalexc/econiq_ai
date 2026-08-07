"""The agent contract registry.

One place that knows, for every agent, which typed objects it consumes and
produces and where it sits in the ontology. The agent runtime, the evaluation
harness and the API all resolve schemas through here rather than importing
agent modules, which keeps the contract independent of any agent framework
(tech rec §13).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from econiq_schemas.asset_agents import (
    AssetDiscoveryInput,
    AssetDiscoveryOutput,
    AssetExposureInput,
    AssetExposureOutput,
)
from econiq_schemas.base import AgentInput, AgentOutput
from econiq_schemas.capability_agents import (
    BottleneckIdentificationInput,
    BottleneckIdentificationOutput,
    CapabilityConfluenceInput,
    CapabilityConfluenceOutput,
    CapabilityMappingInput,
    CapabilityMappingOutput,
)
from econiq_schemas.document_agents import (
    ClaimExtractionInput,
    ClaimExtractionOutput,
    DocumentClassifierInput,
    DocumentClassifierOutput,
)
from econiq_schemas.event_agents import (
    EventResolutionInput,
    EventResolutionOutput,
    EventSignificanceInput,
    EventSignificanceOutput,
)
from econiq_schemas.process_agents import (
    ProcessArchetypeInput,
    ProcessArchetypeOutput,
    ProcessCriticInput,
    ProcessCriticOutput,
    ProcessDiscoveryInput,
    ProcessDiscoveryOutput,
    ProcessStateInput,
    ProcessStateOutput,
    ProcessUpdateInput,
    ProcessUpdateOutput,
)


@dataclass(frozen=True)
class AgentContract:
    """What an agent is allowed to be asked and allowed to answer.

    ``ontology_layer`` is enforced by review and by the evaluation harness: an
    agent may only write objects at its own layer. The Bottleneck agent never
    says "buy MP Materials" (agent doc §2.1, §16).
    """

    name: str
    ontology_layer: str
    input_schema: type[AgentInput]
    output_schema: type[AgentOutput]
    phase: int
    issue: int
    summary: str


def _contracts() -> Mapping[str, AgentContract]:
    entries = (
        AgentContract(
            name="document_classifier",
            ontology_layer="Document",
            input_schema=DocumentClassifierInput,
            output_schema=DocumentClassifierOutput,
            phase=0,
            issue=6,
            summary="Route documents by type and information mode.",
        ),
        AgentContract(
            name="claim_extraction",
            ontology_layer="Document → Claim",
            input_schema=ClaimExtractionInput,
            output_schema=ClaimExtractionOutput,
            phase=0,
            issue=6,
            summary="Extract atomic factual Claims with exact source locations.",
        ),
        AgentContract(
            name="event_resolution",
            ontology_layer="Claim → Event",
            input_schema=EventResolutionInput,
            output_schema=EventResolutionOutput,
            phase=0,
            issue=7,
            summary="Cluster Claims into canonical Events and suppress duplicates.",
        ),
        AgentContract(
            name="event_significance",
            ontology_layer="Event",
            input_schema=EventSignificanceInput,
            output_schema=EventSignificanceOutput,
            phase=0,
            issue=7,
            summary="Decide whether an Event warrants propagation.",
        ),
        AgentContract(
            name="process_discovery",
            ontology_layer="Event → Process",
            input_schema=ProcessDiscoveryInput,
            output_schema=ProcessDiscoveryOutput,
            phase=0,
            issue=8,
            summary="Create or find the Processes an Event bears on.",
        ),
        AgentContract(
            name="process_update",
            ontology_layer="Event → Process",
            input_schema=ProcessUpdateInput,
            output_schema=ProcessUpdateOutput,
            phase=0,
            issue=8,
            summary="Apply an evidenced delta to an existing Process.",
        ),
        AgentContract(
            name="process_archetype",
            ontology_layer="Process",
            input_schema=ProcessArchetypeInput,
            output_schema=ProcessArchetypeOutput,
            phase=0,
            issue=9,
            summary="Classify the Process Archetype and reject the alternatives.",
        ),
        AgentContract(
            name="process_state",
            ontology_layer="Process → Process State",
            input_schema=ProcessStateInput,
            output_schema=ProcessStateOutput,
            phase=0,
            issue=9,
            summary="Estimate the current State within the archetype's State machine.",
        ),
        AgentContract(
            name="process_critic",
            ontology_layer="Process",
            input_schema=ProcessCriticInput,
            output_schema=ProcessCriticOutput,
            phase=0,
            issue=10,
            summary="Attempt to falsify the Process. Never rescue it.",
        ),
        AgentContract(
            name="bottleneck_identification",
            ontology_layer="Process → Bottleneck",
            input_schema=BottleneckIdentificationInput,
            output_schema=BottleneckIdentificationOutput,
            phase=0,
            issue=11,
            summary="Identify the constraint limiting the Process.",
        ),
        AgentContract(
            name="capability_mapping",
            ontology_layer="Bottleneck → Capability Requirement",
            input_schema=CapabilityMappingInput,
            output_schema=CapabilityMappingOutput,
            phase=0,
            issue=11,
            summary="Translate a Bottleneck into an AND/OR Capability structure.",
        ),
        AgentContract(
            name="capability_confluence",
            ontology_layer="Capability",
            input_schema=CapabilityConfluenceInput,
            output_schema=CapabilityConfluenceOutput,
            phase=0,
            issue=11,
            summary="Classify independence of the Processes supporting a Capability.",
        ),
        AgentContract(
            name="asset_discovery",
            ontology_layer="Capability → Asset Candidate",
            input_schema=AssetDiscoveryInput,
            output_schema=AssetDiscoveryOutput,
            phase=0,
            issue=12,
            summary="Find the investable Asset universe for a Capability.",
        ),
        AgentContract(
            name="asset_exposure",
            ontology_layer="Asset",
            input_schema=AssetExposureInput,
            output_schema=AssetExposureOutput,
            phase=0,
            issue=12,
            summary="Estimate the strength and type of an Asset's exposure.",
        ),
    )
    return MappingProxyType({c.name: c for c in entries})


AGENT_CONTRACTS: Mapping[str, AgentContract] = _contracts()


def contract_for(agent_name: str) -> AgentContract:
    try:
        return AGENT_CONTRACTS[agent_name]
    except KeyError:
        raise KeyError(
            f"unknown agent {agent_name!r}; known agents: {sorted(AGENT_CONTRACTS)}"
        ) from None
