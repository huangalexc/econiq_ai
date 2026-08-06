"""Document acquisition, storage and parsing (issue #5).

Postgres holds metadata and provenance; S3 holds the bytes (tech rec §8). The
pipeline ends by announcing ``DocumentIngested`` and stops there — documents do
not propagate synchronously through the graph (ontology §46).
"""

from econiq_ingestion.errors import (
    IngestionError,
    ParserNotAvailableError,
    StorageError,
    UnsupportedContentTypeError,
)
from econiq_ingestion.events import (
    DocumentIngested,
    EventPublisher,
    InMemoryEventPublisher,
    NullEventPublisher,
)
from econiq_ingestion.parsing import (
    HtmlParser,
    ParsedDocument,
    Parser,
    ParserRegistry,
    PdfParser,
    PlainTextParser,
    Section,
    detect_sections,
    normalize_whitespace,
)
from econiq_ingestion.pipeline import (
    INLINE_TEXT_LIMIT,
    IngestionPipeline,
    IngestionResult,
    IngestionStatus,
    summarize,
)
from econiq_ingestion.sources import (
    DocumentSource,
    FeedEntry,
    FilesystemSource,
    RawDocument,
    RssSource,
    collect,
    dedupe,
    parse_feed,
)
from econiq_ingestion.storage import (
    Artifact,
    InMemoryObjectStore,
    ObjectStore,
    S3ObjectStore,
    S3Settings,
    StoredObject,
    object_key,
)

__all__ = [
    "INLINE_TEXT_LIMIT",
    "Artifact",
    "DocumentIngested",
    "DocumentSource",
    "EventPublisher",
    "FeedEntry",
    "FilesystemSource",
    "HtmlParser",
    "InMemoryEventPublisher",
    "InMemoryObjectStore",
    "IngestionError",
    "IngestionPipeline",
    "IngestionResult",
    "IngestionStatus",
    "NullEventPublisher",
    "ObjectStore",
    "ParsedDocument",
    "Parser",
    "ParserNotAvailableError",
    "ParserRegistry",
    "PdfParser",
    "PlainTextParser",
    "RawDocument",
    "RssSource",
    "S3ObjectStore",
    "S3Settings",
    "Section",
    "StorageError",
    "StoredObject",
    "UnsupportedContentTypeError",
    "collect",
    "dedupe",
    "detect_sections",
    "normalize_whitespace",
    "object_key",
    "parse_feed",
    "summarize",
]
