"""Provenance primitives.

Every material statement in the system must be traceable back to a source
location in a document (agent doc §2.4), and every agent-produced object must
record what produced it (agent doc §21). These types are the mechanism.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import Field, model_validator

from econiq_ontology.base import Confidence, OntologyModel, utcnow
from econiq_ontology.enums import EntityType


class SourceLocation(OntologyModel):
    """Where inside a Document a Claim came from.

    At least one locator must be present — a Claim that cannot be pointed at is
    not attributable, and attribution is the point.
    """

    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    paragraph: int | None = Field(default=None, ge=0)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    quote: str | None = Field(default=None, description="Verbatim span supporting the claim.")

    @model_validator(mode="after")
    def _at_least_one_locator(self) -> Self:
        if not any(
            v is not None
            for v in (
                self.page,
                self.section,
                self.paragraph,
                self.char_start,
                self.quote,
            )
        ):
            raise ValueError("SourceLocation requires at least one locator")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must not precede char_start")
        return self


class AgentAttribution(OntologyModel):
    """The versioning envelope required on every agent output (agent doc §21).

    Prompts are code: a prompt change can flip a Process classification, so the
    prompt version is recorded against the output it produced, not looked up
    later from whatever is current.
    """

    agent_name: str
    agent_version: str
    model: str = Field(description="Provider-qualified model id, e.g. 'anthropic:...'.")
    prompt_version: str
    timestamp: datetime = Field(default_factory=utcnow)
    input_object_versions: dict[str, str] = Field(
        default_factory=dict,
        description="Schema versions of the input objects, keyed by field name.",
    )
    output_schema_version: str
    agent_run_id: uuid.UUID | None = Field(
        default=None, description="FK to agent_runs; set once the run is persisted."
    )


class EntityRef(OntologyModel):
    """A typed pointer to another node in the economic graph."""

    entity_type: EntityType
    entity_id: uuid.UUID


class EvidenceRef(OntologyModel):
    """A single piece of support for (or against) a statement.

    ``supports=False`` records contradicting evidence, which the ontology treats
    as first-class: contradiction is a scored dimension of Thesis Quality
    (ontology §17), not something to be filtered out.
    """

    ref: EntityRef
    supports: bool = True
    weight: Confidence = 1.0
    note: str | None = None
