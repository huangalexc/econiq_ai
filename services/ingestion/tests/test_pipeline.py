"""The pipeline end to end, against a real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from econiq_data_models import Document as DocumentRow
from econiq_data_models import Node
from econiq_ingestion import (
    Artifact,
    IngestionPipeline,
    IngestionStatus,
    InMemoryEventPublisher,
    InMemoryObjectStore,
    RawDocument,
    object_key,
    summarize,
)
from econiq_ontology import DocumentType, EntityType, ExtractionStatus
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

ARTICLE = (
    b"<html><head><title>US government acquires stake in MP Materials</title></head>"
    b"<body><p>The Pentagon took an equity position in the rare-earth producer.</p>"
    b"</body></html>"
)


def _raw(content: bytes = ARTICLE, **kw) -> RawDocument:
    defaults = dict(
        source="reuters-rss",
        title="US government acquires stake in MP Materials",
        content=content,
        content_type="text/html",
        publication_time=PUB,
        retrieved_at=PUB + timedelta(minutes=3),
        publisher="Reuters",
        url="https://example.com/mp-materials",
        document_type=DocumentType.NEWS_ARTICLE,
    )
    return RawDocument(**{**defaults, **kw})


@pytest.fixture
def pipeline(session_factory):
    store = InMemoryObjectStore()
    publisher = InMemoryEventPublisher()
    return (
        IngestionPipeline(store, session_factory, publisher=publisher),
        store,
        publisher,
    )


async def test_ingest_stores_bytes_text_and_metadata(pipeline, session_factory):
    pipe, store, publisher = pipeline
    raw = _raw()

    result = await pipe.ingest(raw)

    assert result.status is IngestionStatus.INGESTED
    assert store.exists(object_key(Artifact.RAW, raw.content_hash, extension=".html"))
    assert "Pentagon" in pipe.load_normalized_text(raw.content_hash)

    async with session_factory() as session:
        row = (await session.execute(select(DocumentRow))).scalar_one()
        assert row.document_id == result.document_id
        assert row.publisher == "Reuters"
        assert row.publication_time == PUB
        assert row.extraction_status is ExtractionStatus.PARSED
        assert row.content_hash == raw.content_hash
        assert row.storage_uri.startswith("s3://")
        # Small documents are mirrored inline so agents avoid an S3 round trip.
        assert "Pentagon" in (row.raw_content or "")

        node = (await session.execute(select(Node))).scalar_one()
        assert node.node_id == result.document_id
        assert node.node_type is EntityType.DOCUMENT

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert event.document_id == result.document_id
    assert event.publication_time == PUB


async def test_the_same_bytes_are_never_ingested_twice(pipeline, session_factory):
    """One wire story syndicated to two feeds is one Document."""
    pipe, _, publisher = pipeline

    first = await pipe.ingest(_raw(source="reuters-rss"))
    second = await pipe.ingest(_raw(source="yahoo-rss"))

    assert first.status is IngestionStatus.INGESTED
    assert second.status is IngestionStatus.DUPLICATE
    assert second.document_id == first.document_id

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(DocumentRow))).scalar_one()
    assert count == 1
    # A duplicate must not re-trigger downstream work.
    assert len(publisher.events) == 1


async def test_an_unparseable_document_is_still_stored_and_recorded(pipeline, session_factory):
    """Losing evidence to a parser failure would be a silent gap in the record."""
    pipe, store, publisher = pipeline
    raw = _raw(content=b"%PDF-1.4 not really a pdf", content_type="application/pdf")

    result = await pipe.ingest(raw)

    assert result.status is IngestionStatus.PARSE_FAILED
    assert result.error
    assert store.exists(object_key(Artifact.RAW, raw.content_hash, extension=".pdf"))

    async with session_factory() as session:
        row = (await session.execute(select(DocumentRow))).scalar_one()
        assert row.extraction_status is ExtractionStatus.FAILED
        assert row.raw_content is None

    # Nothing downstream should run on a document with no text.
    assert publisher.events == []


async def test_large_documents_are_not_mirrored_into_postgres(session_factory):
    store = InMemoryObjectStore()
    pipe = IngestionPipeline(store, session_factory, inline_text_limit=32)
    raw = _raw(content=b"<p>" + b"long content. " * 50 + b"</p>")

    await pipe.ingest(raw)

    async with session_factory() as session:
        row = (await session.execute(select(DocumentRow))).scalar_one()
    assert row.raw_content is None
    assert "long content" in pipe.load_normalized_text(raw.content_hash)


async def test_a_source_run_reports_per_status_counts(pipeline, tmp_path):
    pipe, _, _ = pipeline
    from econiq_ingestion import FilesystemSource

    (tmp_path / "a.txt").write_text("First document about grid capacity.")
    (tmp_path / "b.txt").write_text("Second document about transformers.")
    (tmp_path / "c.txt").write_text("First document about grid capacity.")  # duplicate bytes

    results = await pipe.ingest_source(FilesystemSource(tmp_path))

    assert summarize(results) == {
        "ingested": 2,
        "duplicate": 1,
        "parse_failed": 0,
        "total": 3,
    }
