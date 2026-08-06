"""Acquisition preserves provenance and never invents a publication time."""

from datetime import UTC, datetime, timedelta

import pytest
from econiq_ingestion import FilesystemSource, RawDocument, collect, dedupe, parse_feed

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Reuters Commodities</title>
  <item>
    <title>US government acquires stake in MP Materials</title>
    <link>https://example.com/a</link>
    <description>The Pentagon took an equity position.</description>
    <pubDate>Mon, 14 Jul 2026 12:00:00 +0000</pubDate>
    <guid>urn:a</guid>
  </item>
</channel></rss>
"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Federal Register</title>
  <entry>
    <title>Final rule on domestic sourcing</title>
    <link href="https://example.gov/rule"/>
    <summary>Compliance begins in 2027.</summary>
    <published>2026-07-14T12:00:00Z</published>
    <id>urn:b</id>
  </entry>
</feed>
"""


def _raw(**kw):
    defaults = dict(
        source="test",
        title="t",
        content=b"body",
        content_type="text/plain",
        publication_time=PUB,
        retrieved_at=PUB + timedelta(minutes=1),
    )
    return RawDocument(**{**defaults, **kw})


def test_content_hash_is_the_identity():
    assert _raw().content_hash == _raw(title="different title").content_hash
    assert _raw().content_hash != _raw(content=b"other").content_hash


def test_a_document_cannot_be_retrieved_before_it_was_published():
    with pytest.raises(ValueError, match="retrieved_at"):
        _raw(retrieved_at=PUB - timedelta(days=1))


def test_dedupe_keeps_the_first_occurrence():
    first, second = _raw(source="feed-a"), _raw(source="feed-b")
    assert [d.source for d in dedupe([first, second])] == ["feed-a"]


def test_rss_entries_carry_publisher_and_date():
    entries = parse_feed(RSS)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.title.startswith("US government acquires")
    assert entry.link == "https://example.com/a"
    assert entry.publisher == "Reuters Commodities"
    assert entry.published == PUB


def test_atom_entries_are_parsed_too():
    entry = parse_feed(ATOM)[0]
    assert entry.link == "https://example.gov/rule"
    assert entry.published == PUB
    assert entry.guid == "urn:b"


def test_a_missing_feed_date_falls_back_to_now_rather_than_guessing():
    feed = RSS.replace(b"<pubDate>Mon, 14 Jul 2026 12:00:00 +0000</pubDate>", b"")
    published = parse_feed(feed)[0].published
    assert (datetime.now(UTC) - published).total_seconds() < 5


async def test_filesystem_source_records_how_it_derived_the_date(tmp_path):
    (tmp_path / "one.txt").write_text("First document.")
    (tmp_path / "two.html").write_text("<p>Second</p>")

    documents = await collect(FilesystemSource(tmp_path, publisher="corpus"))

    assert [d.content_type for d in documents] == ["text/plain", "text/html"]
    assert all(d.source_metadata["publication_time_basis"] == "file_mtime" for d in documents)
    assert all(d.publisher == "corpus" for d in documents)


async def test_collect_respects_a_limit(tmp_path):
    for i in range(5):
        (tmp_path / f"{i}.txt").write_text(f"doc {i}")
    assert len(await collect(FilesystemSource(tmp_path), limit=2)) == 2
