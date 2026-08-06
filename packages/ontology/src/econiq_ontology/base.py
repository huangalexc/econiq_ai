"""Base model conventions shared by every ontology object.

Schema versioning (issue #3): every ontology object carries the version of the
schema it was produced under, so that a stored object can always be interpreted
with the contract that created it. See ``agent_architecture_and_evaluation.md``
§21 — versions are attached to outputs, not inferred later.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Version of the ontology contract. Bump the minor version for additive
#: changes, the major version for anything that invalidates stored objects.
ONTOLOGY_SCHEMA_VERSION = "1.0.0"

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
"""Model belief in [0, 1]. NOT a probability until the calibration framework
(issue #55 / P3.09) validates it — see ontology §35."""

Score10 = Annotated[float, Field(ge=0.0, le=10.0)]
"""Bounded 0-10 feature score, the scale used throughout the specs
(e.g. ontology §10 'Demand acceleration: 8.3')."""

Weight = Annotated[float, Field(ge=0.0, le=1.0)]


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class OntologyModel(BaseModel):
    """Base for all ontology objects.

    ``extra="forbid"`` is deliberate: these models validate LLM output, and a
    hallucinated field must fail loudly rather than be silently dropped.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    schema_version: str = Field(
        default=ONTOLOGY_SCHEMA_VERSION,
        description="Ontology contract version this object was produced under.",
    )


class Entity(OntologyModel):
    """An ontology object with identity in the graph.

    ``id`` is stable across revisions; ``revision`` increments whenever an agent
    revises the object. Revisions are append-only in the system of record — see
    ``economic_process_asset_ontology.md`` §33 and PRD §21/§30.
    """

    id: uuid.UUID = Field(default_factory=new_id)
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utcnow)
    valid_from: datetime = Field(
        default_factory=utcnow,
        description="Start of this revision's validity window (system time).",
    )
    valid_to: datetime | None = Field(
        default=None,
        description="End of validity; None means this is the current revision.",
    )

    @model_validator(mode="after")
    def _validity_window_ordered(self) -> Self:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        return self

    @property
    def is_current(self) -> bool:
        return self.valid_to is None


class TemporalObservation(OntologyModel):
    """An append-only observation about an entity at a point in time.

    Observations are never mutated. A later observation supersedes an earlier
    one by being more recent, which is what makes "what did the system believe
    on July 14?" answerable (ui_concept §32).
    """

    id: uuid.UUID = Field(default_factory=new_id)
    observed_at: datetime = Field(
        description="The point in time the observation describes (as-of date)."
    )
    recorded_at: datetime = Field(
        default_factory=utcnow,
        description="When the system recorded it. recorded_at >= observed_at.",
    )

    @model_validator(mode="after")
    def _recorded_after_observed(self) -> Self:
        if self.recorded_at < self.observed_at:
            raise ValueError("recorded_at must not precede observed_at")
        return self
