"""The ingestion pipeline (issue #5).

::

    RawDocument → dedupe → store raw → parse → store normalized
                → Document row → DocumentIngested

Two properties are load-bearing:

* **Idempotent.** The content hash is the identity. Re-running a source, or
  ingesting the same wire story from two feeds, produces one Document — which is
  the first of several places this system refuses to count repetition as
  evidence.
* **Non-destructive.** A document that fails to parse is still stored and still
  gets a row, marked ``failed``. Losing evidence because a parser choked would
  be a silent gap in the record.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from econiq_data_models import Document as DocumentRow
from econiq_data_models import Node
from econiq_ontology import EntityType, ExtractionStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_ingestion.errors import IngestionError
from econiq_ingestion.events import DocumentIngested, EventPublisher, NullEventPublisher
from econiq_ingestion.parsing import ParsedDocument, ParserRegistry
from econiq_ingestion.sources import DocumentSource, RawDocument
from econiq_ingestion.storage import Artifact, ObjectStore, object_key

logger = logging.getLogger("econiq.ingestion")

#: Normalized text below this size is mirrored into Postgres so that Phase 0
#: agents can read a document without a round trip to object storage. The bytes
#: in S3 remain authoritative.
INLINE_TEXT_LIMIT = 32_000


class IngestionStatus(StrEnum):
    INGESTED = "ingested"
    DUPLICATE = "duplicate"
    """Already ingested — same bytes, same content hash."""

    PARSE_FAILED = "parse_failed"
    """Stored and recorded, but no text could be extracted."""


@dataclass(frozen=True, slots=True)
class IngestionResult:
    status: IngestionStatus
    content_hash: str
    document_id: uuid.UUID | None = None
    parsed: ParsedDocument | None = None
    event: DocumentIngested | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is IngestionStatus.INGESTED


class IngestionPipeline:
    """Turns acquired documents into stored, parsed, recorded evidence."""

    def __init__(
        self,
        object_store: ObjectStore,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        parsers: ParserRegistry | None = None,
        publisher: EventPublisher | None = None,
        inline_text_limit: int = INLINE_TEXT_LIMIT,
    ) -> None:
        self.object_store = object_store
        self.session_factory = session_factory
        self.parsers = parsers or ParserRegistry()
        self.publisher = publisher or NullEventPublisher()
        self.inline_text_limit = inline_text_limit

    async def ingest(self, raw: RawDocument) -> IngestionResult:
        content_hash = raw.content_hash

        async with self.session_factory() as session:
            existing = await self._find_by_hash(session, content_hash)
            if existing is not None:
                logger.debug("duplicate document %s from %s", content_hash[:12], raw.source)
                return IngestionResult(
                    status=IngestionStatus.DUPLICATE,
                    content_hash=content_hash,
                    document_id=existing,
                )

        raw_object = self.object_store.put(
            object_key(Artifact.RAW, content_hash, extension=_extension_for(raw.content_type)),
            raw.content,
            content_type=raw.content_type,
        )

        parsed, error = self._parse(raw)
        if parsed is not None and not parsed.is_empty:
            self.object_store.put(
                object_key(Artifact.NORMALIZED, content_hash, extension=".txt"),
                parsed.text.encode(),
                content_type="text/plain",
            )
            status = ExtractionStatus.PARSED
        else:
            status = ExtractionStatus.FAILED

        document_id = await self._persist(raw, parsed, raw_object.uri, status)

        if status is ExtractionStatus.FAILED:
            logger.warning("stored but could not parse %s: %s", raw.url or raw.title, error)
            return IngestionResult(
                status=IngestionStatus.PARSE_FAILED,
                content_hash=content_hash,
                document_id=document_id,
                error=error,
            )

        assert parsed is not None
        event = DocumentIngested(
            document_id=document_id,
            source=raw.source,
            document_type=raw.document_type,
            publication_time=raw.publication_time,
            content_hash=content_hash,
            storage_uri=raw_object.uri,
            section_count=len(parsed.sections),
        )
        self.publisher.publish(event)
        return IngestionResult(
            status=IngestionStatus.INGESTED,
            content_hash=content_hash,
            document_id=document_id,
            parsed=parsed,
            event=event,
        )

    async def ingest_source(
        self, source: DocumentSource, *, limit: int | None = None
    ) -> list[IngestionResult]:
        """Drain a source. One document's failure never stops the run."""
        results: list[IngestionResult] = []
        async for raw in source.fetch():
            try:
                results.append(await self.ingest(raw))
            except IngestionError as exc:
                logger.exception("ingestion failed for %s", raw.url or raw.title)
                results.append(
                    IngestionResult(
                        status=IngestionStatus.PARSE_FAILED,
                        content_hash=raw.content_hash,
                        error=str(exc),
                    )
                )
            if limit is not None and len(results) >= limit:
                break
        return results

    def _parse(self, raw: RawDocument) -> tuple[ParsedDocument | None, str | None]:
        try:
            return self.parsers.parse(raw.content, raw.content_type, title=raw.title), None
        except IngestionError as exc:
            return None, str(exc)
        except Exception as exc:  # a malformed PDF must not take the run down
            return None, f"{type(exc).__name__}: {exc}"

    async def _find_by_hash(self, session: AsyncSession, content_hash: str) -> uuid.UUID | None:
        result = await session.execute(
            select(DocumentRow.document_id).where(DocumentRow.content_hash == content_hash)
        )
        return result.scalar_one_or_none()

    async def _persist(
        self,
        raw: RawDocument,
        parsed: ParsedDocument | None,
        storage_uri: str,
        status: ExtractionStatus,
    ) -> uuid.UUID:
        document_id = uuid.uuid4()
        text = parsed.text if parsed is not None else None
        async with self.session_factory() as session:
            # The node registry row must land first: `documents.document_id` is
            # a foreign key into it, and SQLAlchemy does not order inserts
            # across mappers that have no ORM relationship between them.
            session.add(Node(node_id=document_id, node_type=EntityType.DOCUMENT))
            await session.flush()
            session.add(
                DocumentRow(
                    document_id=document_id,
                    source=raw.source,
                    publisher=raw.publisher,
                    author=raw.author,
                    title=(parsed.title if parsed and parsed.title else raw.title)[:2000],
                    url=raw.url,
                    document_type=raw.document_type,
                    publication_time=raw.publication_time,
                    retrieved_at=raw.retrieved_at,
                    language=raw.language,
                    storage_uri=storage_uri,
                    content_hash=raw.content_hash,
                    raw_content=(
                        text if text is not None and len(text) <= self.inline_text_limit else None
                    ),
                    extraction_status=status,
                )
            )
            await session.commit()
        return document_id

    def load_normalized_text(self, content_hash: str) -> str:
        """Read normalized text back from object storage."""
        key = object_key(Artifact.NORMALIZED, content_hash, extension=".txt")
        return self.object_store.get(key).decode("utf-8", errors="replace")


def summarize(results: Iterable[IngestionResult]) -> dict[str, Any]:
    """Counts per status. What a batch run should log and a dashboard should show."""
    counts: dict[str, int] = {status.value: 0 for status in IngestionStatus}
    for result in results:
        counts[result.status.value] += 1
    counts["total"] = sum(counts[status.value] for status in IngestionStatus)
    return counts


_CONTENT_TYPE_EXTENSIONS = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/json": ".json",
    "application/xml": ".xml",
}


def _extension_for(content_type: str) -> str:
    return _CONTENT_TYPE_EXTENSIONS.get(content_type.split(";")[0].strip().lower(), "")
