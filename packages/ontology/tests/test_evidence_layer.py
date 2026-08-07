"""Document, Claim and Event invariants."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_ontology import (
    Claim,
    ClaimType,
    Document,
    DocumentType,
    Event,
    EventType,
    SourceLocation,
)
from pydantic import ValidationError

PUB = datetime(2026, 7, 14, tzinfo=UTC)


def _document(**kw):
    defaults = dict(
        source="reuters-feed",
        title="US government acquires stake in MP Materials",
        document_type=DocumentType.NEWS_ARTICLE,
        publication_time=PUB,
        retrieved_at=PUB + timedelta(minutes=5),
    )
    return Document(**{**defaults, **kw})


def test_a_document_cannot_be_retrieved_before_it_was_published():
    _document()
    with pytest.raises(ValidationError, match="retrieved_at"):
        _document(retrieved_at=PUB - timedelta(days=1))


def test_a_claim_requires_a_source_location():
    with pytest.raises(ValidationError):
        Claim(
            document_id=uuid.uuid4(),
            text="The US government acquired a stake in MP Materials.",
            claim_type=ClaimType.REPORTED_CLAIM,
            extraction_confidence=0.9,
        )


def test_source_location_needs_at_least_one_locator():
    SourceLocation(paragraph=3, quote="acquired a stake")
    with pytest.raises(ValidationError, match="at least one locator"):
        SourceLocation()


def _event(**kw):
    defaults = dict(
        event_type=EventType.GOVERNMENT_FUNDING,
        title="US government acquires stake in MP Materials",
        description="…",
        timestamp=PUB,
        supporting_claims=[uuid.uuid4(), uuid.uuid4()],
        novelty=8.0,
        materiality=7.5,
        confidence=0.9,
    )
    return Event(**{**defaults, **kw})


def test_an_event_needs_at_least_one_supporting_claim():
    with pytest.raises(ValidationError):
        _event(supporting_claims=[])


def test_independent_sources_cannot_exceed_supporting_claims():
    """Twenty syndications of one wire story are not twenty sources."""
    _event(independent_source_count=2)
    with pytest.raises(ValidationError, match="independent_source_count"):
        _event(independent_source_count=5)
