"""Where documents come from.

A source yields ``RawDocument`` — bytes plus the provenance that came with them.
Nothing here interprets content; interpretation starts at the parser, and
inference starts at the agents. Keeping acquisition dumb is what lets the same
pipeline replay a historical corpus and a live feed identically (issue #35).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from xml.etree import ElementTree

from econiq_ontology import DocumentType


@dataclass(frozen=True, slots=True)
class RawDocument:
    """A document as acquired, before any interpretation.

    ``publication_time`` comes from the source, never from ingestion time: a
    document ingested today may have been published years ago, and treating the
    two as interchangeable is how point-in-time integrity dies (ontology §33).
    """

    source: str
    title: str
    content: bytes
    content_type: str
    publication_time: datetime
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    publisher: str | None = None
    author: str | None = None
    url: str | None = None
    document_type: DocumentType = DocumentType.OTHER
    language: str = "en"
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.retrieved_at < self.publication_time:
            raise ValueError("retrieved_at must not precede publication_time")

    @property
    def content_hash(self) -> str:
        """SHA-256 of the raw bytes — the idempotency key for ingestion."""
        return hashlib.sha256(self.content).hexdigest()


@runtime_checkable
class DocumentSource(Protocol):
    """A pluggable acquisition channel."""

    name: str

    def fetch(self) -> AsyncIterator[RawDocument]: ...


class FilesystemSource:
    """Reads documents from a directory.

    The workhorse for evaluation: issue #17's phase gate runs against a curated
    corpus, and a curated corpus is a directory of files.
    """

    def __init__(
        self,
        root: Path,
        *,
        name: str = "filesystem",
        document_type: DocumentType = DocumentType.OTHER,
        publisher: str | None = None,
        pattern: str = "*",
    ) -> None:
        self.root = root
        self.name = name
        self.document_type = document_type
        self.publisher = publisher
        self.pattern = pattern

    async def fetch(self) -> AsyncIterator[RawDocument]:
        for path in sorted(self.root.glob(self.pattern)):
            if not path.is_file():
                continue
            stat = path.stat()
            # Filesystem mtime is a weak publication time. It is recorded as
            # such rather than silently substituted with "now".
            published = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            yield RawDocument(
                source=self.name,
                title=path.stem,
                content=path.read_bytes(),
                content_type=_content_type_for(path),
                publication_time=published,
                publisher=self.publisher,
                url=path.as_uri(),
                document_type=self.document_type,
                source_metadata={"path": str(path), "publication_time_basis": "file_mtime"},
            )


class RssSource:
    """An RSS/Atom feed.

    Deliberately minimal: a feed entry is a pointer and a summary, not the
    article. ``fetch_full_text`` decides whether the pipeline stores the summary
    or follows the link — following it is usually right, because Claim
    extraction against a two-sentence summary produces thin, unattributable
    claims.
    """

    def __init__(
        self,
        feed_url: str,
        *,
        name: str,
        publisher: str | None = None,
        document_type: DocumentType = DocumentType.NEWS_ARTICLE,
        client: Any | None = None,
        fetch_full_text: bool = True,
    ) -> None:
        self.feed_url = feed_url
        self.name = name
        self.publisher = publisher
        self.document_type = document_type
        self.fetch_full_text = fetch_full_text
        self._client = client

    async def fetch(self) -> AsyncIterator[RawDocument]:
        client = self._client or _default_client()
        response = await client.get(self.feed_url)
        response.raise_for_status()
        for entry in parse_feed(response.content):
            content, content_type = entry.summary.encode(), "text/html"
            if self.fetch_full_text and entry.link:
                article = await client.get(entry.link)
                if article.status_code == 200:
                    content = article.content
                    content_type = article.headers.get("content-type", "text/html")
            retrieved = datetime.now(UTC)
            yield RawDocument(
                source=self.name,
                title=entry.title,
                content=content,
                content_type=content_type.split(";")[0].strip(),
                publication_time=min(entry.published, retrieved),
                retrieved_at=retrieved,
                publisher=self.publisher or entry.publisher,
                author=entry.author,
                url=entry.link,
                document_type=self.document_type,
                source_metadata={"feed_url": self.feed_url, "guid": entry.guid},
            )


@dataclass(frozen=True, slots=True)
class FeedEntry:
    title: str
    link: str | None
    summary: str
    published: datetime
    guid: str | None = None
    author: str | None = None
    publisher: str | None = None


_ATOM = "{http://www.w3.org/2005/Atom}"


def parse_feed(payload: bytes) -> list[FeedEntry]:
    """Parse RSS 2.0 or Atom into entries.

    Written against the stdlib rather than a feed library: feeds are a small,
    stable surface, and one fewer dependency in the ingest path is one fewer
    thing to audit.
    """
    root = ElementTree.fromstring(payload)
    entries: list[FeedEntry] = []

    channel = root.find("channel")
    if channel is not None:  # RSS 2.0
        publisher = _text(channel.find("title"))
        for item in channel.findall("item"):
            entries.append(
                FeedEntry(
                    title=_text(item.find("title")) or "(untitled)",
                    link=_text(item.find("link")),
                    summary=_text(item.find("description")) or "",
                    published=_parse_date(_text(item.find("pubDate"))),
                    guid=_text(item.find("guid")),
                    author=_text(item.find("author")),
                    publisher=publisher,
                )
            )
        return entries

    publisher = _text(root.find(f"{_ATOM}title"))
    for item in root.findall(f"{_ATOM}entry"):  # Atom
        link_el = item.find(f"{_ATOM}link")
        entries.append(
            FeedEntry(
                title=_text(item.find(f"{_ATOM}title")) or "(untitled)",
                link=link_el.get("href") if link_el is not None else None,
                summary=_text(item.find(f"{_ATOM}summary")) or "",
                published=_parse_date(
                    _text(item.find(f"{_ATOM}published")) or _text(item.find(f"{_ATOM}updated"))
                ),
                guid=_text(item.find(f"{_ATOM}id")),
                author=_text(item.find(f"{_ATOM}author/{_ATOM}name")),
                publisher=publisher,
            )
        )
    return entries


def _text(element: ElementTree.Element | None) -> str | None:
    return element.text.strip() if element is not None and element.text else None


def _parse_date(value: str | None) -> datetime:
    """Parse a feed date, falling back to now.

    A missing date is recorded as ingestion time rather than guessed. Callers
    that need certainty read ``source_metadata``.
    """
    if not value:
        return datetime.now(UTC)
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


_EXTENSION_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".json": "application/json",
    ".xml": "application/xml",
}


def _content_type_for(path: Path) -> str:
    return _EXTENSION_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _default_client() -> Any:
    import httpx

    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers={"user-agent": "econiq-ingestion/0.1 (research)"},
    )


async def collect(source: DocumentSource, limit: int | None = None) -> list[RawDocument]:
    """Drain a source into a list. Convenience for tests and batch runs."""
    out: list[RawDocument] = []
    async for document in source.fetch():
        out.append(document)
        if limit is not None and len(out) >= limit:
            break
    return out


def dedupe(documents: Iterable[RawDocument]) -> list[RawDocument]:
    """Drop byte-identical duplicates, keeping the first occurrence."""
    seen: set[str] = set()
    out: list[RawDocument] = []
    for document in documents:
        if document.content_hash in seen:
            continue
        seen.add(document.content_hash)
        out.append(document)
    return out
