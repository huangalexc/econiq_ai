"""Thesis Quality, Asset Quality and Trade Quality (ontology §17).

These three are never collapsed into one number, anywhere. A great thesis
expressed through a bad vehicle is not a good idea, and a single blended score
would hide exactly that. ``Scorecard`` enforces the separation structurally: a
scorecard belongs to one family and may only carry that family's dimensions.

Every dimension records the inputs it was computed from, because the UI's
universal [Explain] primitive (issue #25) must be able to decompose any score
shown anywhere.
"""

from __future__ import annotations

import uuid
from typing import Self

from pydantic import Field, model_validator

from econiq_ontology.base import Confidence, OntologyModel, Score10, TemporalObservation
from econiq_ontology.enums import (
    AssetQualityDimension,
    EntityType,
    ScoreFamily,
    ThesisQualityDimension,
)
from econiq_ontology.provenance import AgentAttribution, EntityRef, EvidenceRef

#: Which dimension vocabulary each family may use. Trade Quality is V2: it has
#: no dimensions in V1, so any attempt to write one fails loudly.
FAMILY_DIMENSIONS: dict[ScoreFamily, frozenset[str]] = {
    ScoreFamily.THESIS_QUALITY: frozenset(d.value for d in ThesisQualityDimension),
    ScoreFamily.ASSET_QUALITY: frozenset(d.value for d in AssetQualityDimension),
    ScoreFamily.TRADE_QUALITY: frozenset(),
}

#: Subject types each family may score.
FAMILY_SUBJECTS: dict[ScoreFamily, frozenset[EntityType]] = {
    ScoreFamily.THESIS_QUALITY: frozenset({EntityType.PROCESS}),
    ScoreFamily.ASSET_QUALITY: frozenset({EntityType.ASSET}),
    ScoreFamily.TRADE_QUALITY: frozenset(),
}


class DimensionScore(OntologyModel):
    """One axis of a scorecard, with its decomposition.

    ``inputs`` holds the named quantities the value was computed from, so the
    score can be explained rather than asserted. ``method`` distinguishes a
    deterministic computation from an LLM judgement — a distinction the
    provenance inspector surfaces directly.
    """

    dimension: str
    value: Score10
    confidence: Confidence
    method: str = Field(
        description="'deterministic' | 'llm_judgement' | 'hybrid' — how it was produced."
    )
    inputs: dict[str, float] = Field(
        default_factory=dict, description="Named inputs behind the value."
    )
    rationale: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class Scorecard(TemporalObservation):
    """A point-in-time set of scores of one family about one subject.

    Append-only, like every other observation: score history is how the UI shows
    that Thesis Quality strengthened as evidence accumulated.
    """

    subject: EntityRef
    family: ScoreFamily
    dimensions: list[DimensionScore] = Field(min_length=1)
    composite: Score10 | None = Field(
        default=None,
        description=("Optional summary *within* one family. Never a blend across families."),
    )
    composite_method: str | None = Field(
        default=None, description="How the composite was derived, if present."
    )
    attribution: AgentAttribution | None = None
    process_state_id: uuid.UUID | None = Field(
        default=None,
        description="State the subject was in when scored — scores are state-conditioned.",
    )

    @model_validator(mode="after")
    def _dimensions_belong_to_family(self) -> Self:
        allowed = FAMILY_DIMENSIONS[self.family]
        if not allowed:
            raise ValueError(f"{self.family.value} has no dimensions in V1 (ontology §17)")
        unknown = {d.dimension for d in self.dimensions} - allowed
        if unknown:
            raise ValueError(f"dimensions not in family {self.family.value}: {sorted(unknown)}")
        names = [d.dimension for d in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("duplicate dimensions in scorecard")
        subjects = FAMILY_SUBJECTS[self.family]
        if self.subject.entity_type not in subjects:
            raise ValueError(
                f"{self.family.value} may not score a {self.subject.entity_type.value}"
            )
        if self.composite is not None and self.composite_method is None:
            raise ValueError("a composite score must record how it was derived")
        return self
