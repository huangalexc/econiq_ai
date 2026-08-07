"""Document → Claim → Event (ontology §4–§6).

This is the deduplication layer of the system. Documents do not propagate
through the graph; Claims are clustered into canonical Events, and it is Events
that reach the Process layer. One hundred articles about one Reuters story are
one Event, not one hundred pieces of evidence (ontology §6).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from econiq_ontology.base import Confidence, Entity, OntologyModel, Score10
from econiq_ontology.enums import (
    ClaimType,
    DocumentType,
    EntityType,
    EpistemicStatus,
    EventType,
    ExtractionStatus,
)
from econiq_ontology.provenance import AgentAttribution, SourceLocation


class EntityMention(OntologyModel):
    """A named real-world entity referenced by a Claim or Event.

    ``resolved_id`` stays ``None`` until entity resolution links the mention to
    a known Asset/company/commodity. Resolution is deterministic work, not LLM
    work (agent doc §2.3) — the agent proposes the surface form, code resolves
    identifiers.
    """

    text: str
    kind: str = Field(description="company | government | commodity | technology | ...")
    resolved_id: str | None = Field(
        default=None, description="Canonical identifier once resolved (e.g. ticker)."
    )


class Document(Entity):
    """An external information source (ontology §4).

    A Document is evidence, never an Event or a Process. Its provenance fields
    are immutable in the system of record: ``raw_content`` lives in object
    storage and Postgres holds the reference (tech rec §8).
    """

    entity_type: Literal[EntityType.DOCUMENT] = EntityType.DOCUMENT

    source: str = Field(description="Feed or acquisition channel the document arrived on.")
    publisher: str | None = None
    author: str | None = None
    title: str
    url: HttpUrl | None = None
    document_type: DocumentType
    publication_time: datetime = Field(
        description="When the document was published, not when it was ingested."
    )
    retrieved_at: datetime
    language: str = "en"

    storage_uri: str | None = Field(default=None, description="s3:// URI of the raw artifact.")
    content_hash: str | None = Field(
        default=None, description="SHA-256 of raw bytes; the ingest dedup key."
    )
    raw_content: str | None = Field(
        default=None, description="Extracted text, when small enough to inline."
    )
    extraction_status: ExtractionStatus = ExtractionStatus.PENDING

    @model_validator(mode="after")
    def _retrieved_after_publication(self) -> Self:
        if self.retrieved_at < self.publication_time:
            raise ValueError("retrieved_at must not precede publication_time")
        return self


class Claim(Entity):
    """An atomic proposition extracted from a Document (ontology §5).

    Claims must be atomic enough to support later attribution, and must point
    back to an exact source location. ``claim_type`` preserves the epistemic
    distinction that the rest of the system depends on: a hypothesis extracted
    from an opinion column is not a reported fact.
    """

    entity_type: Literal[EntityType.CLAIM] = EntityType.CLAIM

    document_id: uuid.UUID
    text: str = Field(min_length=1)
    claim_type: ClaimType
    source_location: SourceLocation
    extraction_confidence: Confidence
    entities: list[EntityMention] = Field(default_factory=list)
    stated_at: datetime | None = Field(
        default=None,
        description="Time the claim is about, when it differs from publication.",
    )
    attribution: AgentAttribution | None = Field(
        default=None, description="The extraction agent run that produced this Claim."
    )


class Event(Entity):
    """A discrete real-world occurrence inferred from one or more Claims
    (ontology §6).

    Events are the compression layer. ``supporting_claims`` may span many
    Documents; ``independent_source_count`` is what makes accumulated evidence
    meaningful, since twenty syndications of one wire story are one source.
    """

    entity_type: Literal[EntityType.EVENT] = EntityType.EVENT

    event_type: EventType
    title: str
    description: str
    timestamp: datetime = Field(description="When the occurrence happened (as-of).")
    entities: list[EntityMention] = Field(default_factory=list)

    supporting_claims: list[uuid.UUID] = Field(
        default_factory=list, min_length=1, description="Claims clustered into this Event."
    )
    independent_source_count: int = Field(
        default=1, ge=1, description="Distinct publishers, after syndication collapse."
    )

    novelty: Score10 = Field(description="How much this changes what was already known.")
    materiality: Score10 = Field(description="Economic significance if true.")
    confidence: Confidence = Field(description="Belief the occurrence is real as described.")
    epistemic_status: EpistemicStatus = EpistemicStatus.OBSERVED

    attribution: AgentAttribution | None = None

    @model_validator(mode="after")
    def _sources_within_claims(self) -> Self:
        if self.independent_source_count > len(self.supporting_claims):
            raise ValueError(
                "independent_source_count cannot exceed the number of supporting claims"
            )
        return self
