"""Document Classifier and Document Extraction agents (agent doc §4.1–§4.2)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from econiq_ontology import (
    ClaimType,
    Confidence,
    DocumentType,
    EntityMention,
    EventType,
    SourceLocation,
)
from pydantic import Field

from econiq_schemas.base import AgentInput, AgentIO, AgentOutput


class InformationMode(StrEnum):
    """Routing decision: textual content goes to Claim extraction, quantitative
    content goes to the deterministic ETL service (agent doc §4.3)."""

    TEXTUAL = "textual"
    QUANTITATIVE = "quantitative"
    MIXED = "mixed"


class AssertionSource(StrEnum):
    """Who is asserting a Claim (agent doc §4.2).

    Finer-grained than ``ClaimType``: a company forecast and a government
    forecast are both hypotheses, but they carry different weight, and the
    distinction is lost forever if it is not captured at extraction time.
    """

    OBSERVED_FACT = "observed_fact"
    REPORTED_STATEMENT = "reported_statement"
    COMPANY_FORECAST = "company_forecast"
    GOVERNMENT_FORECAST = "government_forecast"
    ANALYST_OPINION = "analyst_opinion"
    INFERENCE = "inference"


#: How an ``AssertionSource`` maps onto the ontology's epistemic ``ClaimType``
#: (ontology §5). Deterministic, so the agent never picks the ontology type
#: directly — it reports what it saw and code assigns the epistemic class.
ASSERTION_TO_CLAIM_TYPE: dict[AssertionSource, ClaimType] = {
    AssertionSource.OBSERVED_FACT: ClaimType.DERIVED_FACT,
    AssertionSource.REPORTED_STATEMENT: ClaimType.REPORTED_CLAIM,
    AssertionSource.COMPANY_FORECAST: ClaimType.HYPOTHESIS,
    AssertionSource.GOVERNMENT_FORECAST: ClaimType.HYPOTHESIS,
    AssertionSource.ANALYST_OPINION: ClaimType.HYPOTHESIS,
    AssertionSource.INFERENCE: ClaimType.INFERENCE,
}


class DocumentClassifierInput(AgentInput):
    document_id: str
    title: str
    publisher: str | None = None
    source: str
    publication_time: datetime
    text: str = Field(description="Full or truncated document text.")


class DocumentClassifierOutput(AgentOutput):
    """Routing only. The classifier must not infer investment implications."""

    document_type: DocumentType
    source_type: str = Field(description="e.g. wire_service, regulator, issuer, vendor.")
    primary_information_mode: InformationMode
    named_entities: list[EntityMention] = Field(default_factory=list)
    likely_event_types: list[EventType] = Field(default_factory=list)
    extraction_strategy: str = Field(
        description="Which extraction pipeline should handle this document."
    )
    confidence: Confidence


class ClaimExtractionInput(AgentInput):
    document_id: str
    document_type: DocumentType
    publisher: str | None = None
    publication_time: datetime
    text: str


class ProposedClaim(AgentIO):
    """An extracted proposition, before it becomes a ``Claim``.

    No id: the agent proposes, and persistence assigns identity. ``claim_type``
    is derived from ``assertion_source`` by code, not chosen by the model.
    """

    text: str = Field(min_length=1, description="The atomic proposition.")
    assertion_source: AssertionSource
    source_location: SourceLocation
    extraction_confidence: Confidence
    entities: list[EntityMention] = Field(default_factory=list)
    stated_at: datetime | None = Field(
        default=None, description="The date the claim is about, if stated."
    )
    attributed_to: str | None = Field(
        default=None, description="Who made the statement, if the document attributes it."
    )

    @property
    def claim_type(self) -> ClaimType:
        return ASSERTION_TO_CLAIM_TYPE[self.assertion_source]


class ClaimExtractionOutput(AgentOutput):
    """Extraction adds no facts not contained in the document (agent doc §4.2).

    The evaluation harness checks that against ``source_location.quote``.
    """

    claims: list[ProposedClaim] = Field(default_factory=list)
