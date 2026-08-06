"""Asset Discovery and Asset Exposure agents (agent doc §8.1–§8.2).

The last layer of Phase 0. Note what is absent: no ranking, no return estimate,
no recommendation. §8.1 ends with "Do not rank Assets yet" and ranking is a
Phase 3 concern (issue #53) that depends on quantitative data these agents do
not have.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from econiq_ontology import AssetClass, Confidence, ExposureKind, Score10
from pydantic import Field, model_validator

from econiq_schemas.base import AgentInput, AgentIO, AgentOutput, Cited


class ExposureDirectness(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    OPTIONALITY = "optionality"


class ExposureMateriality(StrEnum):
    """§8.1 — "assess whether exposure is material or incidental"."""

    MATERIAL = "material"
    INCIDENTAL = "incidental"


class ProposedAssetCandidate(Cited):
    """A candidate Asset, named but not resolved.

    The agent proposes a ticker; it does not assert one. Identifier resolution
    is deterministic (agent doc §2.3), and an unresolvable candidate is dropped
    rather than entering the graph on the model's word.
    """

    proposed_name: str = Field(min_length=1)
    proposed_ticker: str | None = None
    proposed_exchange: str | None = None
    asset_class: AssetClass
    exposure_pathway: str = Field(
        min_length=1, description="How the Capability reaches this Asset's economics."
    )
    directness: ExposureDirectness
    materiality: ExposureMateriality
    geography: str | None = None
    dependencies: list[str] = Field(
        default_factory=list, description="What the exposure depends on holding."
    )
    confidence: Confidence


class AssetDiscoveryInput(AgentInput):
    capability_id: str
    capability_name: str
    capability_description: str
    process_names: list[str] = Field(
        default_factory=list, description="Upstream Processes, for context only."
    )
    geographic_constraint: str | None = None
    known_asset_names: list[str] = Field(default_factory=list)


class AssetDiscoveryOutput(AgentOutput):
    candidates: list[ProposedAssetCandidate] = Field(default_factory=list)


class ProposedExposure(Cited):
    """One exposure of one Asset to one Capability or Process.

    ``offsetting_exposures`` matters as much as the positive case: a company
    that supplies the bottleneck and also consumes it is a weaker expression of
    the Process than its revenue share suggests.
    """

    exposure_kind: ExposureKind
    directness: ExposureDirectness
    magnitude: Score10
    revenue_share: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Only when supported by quantitative evidence, never inferred from marketing.",
    )
    rationale: str = Field(min_length=1)
    quantitative_basis: str | None = Field(
        default=None, description="The figure or filing the estimate rests on, if any."
    )
    confidence: Confidence

    @model_validator(mode="after")
    def _revenue_share_needs_a_basis(self) -> Self:
        if self.revenue_share is not None and not self.quantitative_basis:
            raise ValueError("revenue_share requires a quantitative_basis")
        return self


class AssetExposureInput(AgentInput):
    asset_id: str
    asset_name: str
    capability_id: str
    capability_name: str
    business_description: str | None = None
    claim_texts: dict[str, str] = Field(default_factory=dict)
    reported_segment_data: dict[str, float] = Field(
        default_factory=dict, description="Segment revenues etc., when available."
    )


class AssetExposureOutput(AgentOutput):
    exposures: list[ProposedExposure] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    offsetting_exposures: list[str] = Field(
        default_factory=list, description="Ways the Process also hurts this Asset."
    )


class AgentBoundaryViolation(AgentIO):
    """Recorded by the evaluation harness when an agent crosses its layer.

    Kept in the contract package because the boundary is part of the contract:
    the Bottleneck agent naming a ticker is a schema-level failure, not a
    quality issue (agent doc §2.1, §16).
    """

    agent_name: str
    expected_layer: str
    observed_reference: str
    detail: str
