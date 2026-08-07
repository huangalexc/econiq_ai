"""Raw bytes → normalized text → sections (tech rec §20).

Sections matter more than they look: a Claim's ``source_location`` points into
one, and "which section of the 10-K did this come from" is the difference
between a citation a human can check and a page number they cannot.

Numbers are deliberately *not* extracted here. Structured source data is
preferred over asking an LLM to reconstruct figures from prose (tech rec §20),
so quantitative content is routed to the deterministic ETL service instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Protocol, runtime_checkable

from econiq_ingestion.errors import ParserNotAvailableError, UnsupportedContentTypeError


@dataclass(frozen=True, slots=True)
class Section:
    """One structural unit of a document.

    ``char_start``/``char_end`` index into the normalized text, which is what
    makes a Claim's source span verifiable after the fact: the quote an agent
    returns can be compared against the document it claims to come from.
    """

    index: int
    heading: str | None
    text: str
    char_start: int
    char_end: int
    level: int = 1


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Normalized text plus its structure."""

    text: str
    sections: tuple[Section, ...] = ()
    title: str | None = None
    parser: str = "unknown"
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def section_at(self, char_offset: int) -> Section | None:
        for section in self.sections:
            if section.char_start <= char_offset < section.char_end:
                return section
        return None


@runtime_checkable
class Parser(Protocol):
    content_types: frozenset[str]

    def parse(self, content: bytes, *, title: str | None = None) -> ParsedDocument: ...


class PlainTextParser:
    content_types = frozenset({"text/plain", "text/markdown", "application/octet-stream"})

    def parse(self, content: bytes, *, title: str | None = None) -> ParsedDocument:
        text = normalize_whitespace(content.decode("utf-8", errors="replace"))
        return ParsedDocument(
            text=text, sections=detect_sections(text), title=title, parser="plain_text"
        )


class HtmlParser:
    """HTML → readable text.

    Uses trafilatura when installed — boilerplate removal materially improves
    Claim extraction, because navigation chrome and cookie banners otherwise
    become "claims". Falls back to a stdlib extractor so the pipeline (and CI)
    works without the optional dependency.
    """

    content_types = frozenset({"text/html", "application/xhtml+xml"})

    def parse(self, content: bytes, *, title: str | None = None) -> ParsedDocument:
        decoded = content.decode("utf-8", errors="replace")
        extracted, parser_name = self._extract(decoded)
        text = normalize_whitespace(extracted)
        return ParsedDocument(
            text=text,
            sections=detect_sections(text),
            title=title or _StripTags.title_of(decoded),
            parser=parser_name,
        )

    @staticmethod
    def _extract(decoded: str) -> tuple[str, str]:
        try:
            import trafilatura
        except ImportError:
            return _StripTags.text_of(decoded), "html_stdlib"
        extracted = trafilatura.extract(decoded, include_comments=False, include_tables=True)
        if extracted:
            return extracted, "trafilatura"
        # Trafilatura returns None when it finds no article body — a short press
        # release, for instance. Falling back beats discarding the document.
        return _StripTags.text_of(decoded), "html_stdlib"


class PdfParser:
    """PDF → text, page by page.

    Each page becomes a section, so a Claim can cite a page number the reader
    can actually turn to.
    """

    content_types = frozenset({"application/pdf"})

    def parse(self, content: bytes, *, title: str | None = None) -> ParsedDocument:
        try:
            import pymupdf
        except ImportError as exc:
            raise ParserNotAvailableError(
                "PDF parsing needs the 'parsers' extra: uv sync --all-extras"
            ) from exc

        sections: list[Section] = []
        chunks: list[str] = []
        offset = 0
        with pymupdf.open(stream=content, filetype="pdf") as document:
            for number, page in enumerate(document, start=1):
                page_text = normalize_whitespace(page.get_text())
                if not page_text:
                    continue
                chunks.append(page_text)
                sections.append(
                    Section(
                        index=len(sections),
                        heading=f"Page {number}",
                        text=page_text,
                        char_start=offset,
                        char_end=offset + len(page_text),
                    )
                )
                offset += len(page_text) + 2
            metadata = {k: str(v) for k, v in (document.metadata or {}).items() if v}

        return ParsedDocument(
            text="\n\n".join(chunks),
            sections=tuple(sections),
            title=title or metadata.get("title"),
            parser="pymupdf",
            metadata=metadata,
        )


class ParserRegistry:
    """Content type → parser."""

    def __init__(self, parsers: list[Parser] | None = None) -> None:
        self._parsers: dict[str, Parser] = {}
        for parser in parsers or [PlainTextParser(), HtmlParser(), PdfParser()]:
            self.register(parser)

    def register(self, parser: Parser) -> None:
        for content_type in parser.content_types:
            self._parsers[content_type] = parser

    def parse(
        self, content: bytes, content_type: str, *, title: str | None = None
    ) -> ParsedDocument:
        parser = self._parsers.get(content_type.split(";")[0].strip().lower())
        if parser is None:
            raise UnsupportedContentTypeError(
                f"no parser for {content_type!r}; registered: {sorted(self._parsers)}"
            )
        return parser.parse(content, title=title)


_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")

#: Headings: markdown, numbered legal/filing headings, or a short ALL-CAPS line.
_HEADING = re.compile(
    r"^(?:(?P<hashes>#{1,6})\s+(?P<md>.+)"
    r"|(?P<numbered>\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{0,90})"
    r"|(?P<caps>[A-Z][A-Z0-9 ,.'&/():-]{3,80}))$"
)


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces and blank lines without losing paragraphing."""
    text = text.replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def detect_sections(text: str) -> tuple[Section, ...]:
    """Split normalized text into sections on heading lines.

    Offsets index into ``text`` exactly, so a section boundary is a verifiable
    span rather than an approximation.
    """
    if not text.strip():
        return ()

    lines = text.split("\n")
    starts: list[tuple[int, str | None, int]] = []
    offset = 0
    for line in lines:
        stripped = line.strip()
        match = _HEADING.match(stripped) if stripped else None
        if match:
            heading = match.group("md") or match.group("numbered") or match.group("caps")
            level = len(match.group("hashes")) if match.group("hashes") else 1
            starts.append((offset, heading.strip(), level))
        offset += len(line) + 1

    if not starts or starts[0][0] > 0:
        starts.insert(0, (0, None, 1))

    sections: list[Section] = []
    for position, (start, heading, level) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        sections.append(
            Section(
                index=len(sections),
                heading=heading,
                text=body,
                char_start=start,
                char_end=end,
                level=level,
            )
        )
    return tuple(sections)


class _StripTags(HTMLParser):
    """Minimal readable-text extraction, used when trafilatura is unavailable."""

    _SKIP = frozenset({"script", "style", "noscript", "template", "svg"})
    _BLOCK = frozenset(
        {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skipping = 0
        self._in_title = False
        self.title: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skipping:
            return
        if self._in_title and self.title is None:
            self.title = data.strip() or None
            return
        self._parts.append(data)

    @classmethod
    def text_of(cls, html: str) -> str:
        parser = cls()
        parser.feed(html)
        return "".join(parser._parts)

    @classmethod
    def title_of(cls, html: str) -> str | None:
        parser = cls()
        parser.feed(html)
        return parser.title
