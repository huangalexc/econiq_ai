"""Parsing turns bytes into text whose offsets can be trusted."""

import pytest
from econiq_ingestion import (
    ParserRegistry,
    PlainTextParser,
    UnsupportedContentTypeError,
    detect_sections,
    normalize_whitespace,
)

FILING = """\
ITEM 1. BUSINESS

We manufacture rare-earth magnets.

ITEM 1A. RISK FACTORS

Our supply of dysprosium is concentrated.
"""


def test_whitespace_is_collapsed_without_losing_paragraphs():
    text = normalize_whitespace("A  line\r\n\r\n\r\n\r\nAnother line   here  ")
    assert text == "A line\n\nAnother line here"


def test_section_offsets_index_into_the_normalized_text():
    """A Claim's source span is only checkable if the offsets are exact."""
    text = normalize_whitespace(FILING)
    sections = detect_sections(text)

    assert [s.heading for s in sections] == ["ITEM 1. BUSINESS", "ITEM 1A. RISK FACTORS"]
    for section in sections:
        assert text[section.char_start : section.char_end].strip() == section.text


def test_markdown_headings_carry_their_level():
    sections = detect_sections("# Top\n\nBody\n\n### Deep\n\nMore")
    assert [(s.heading, s.level) for s in sections] == [("Top", 1), ("Deep", 3)]


def test_leading_text_before_the_first_heading_becomes_a_section():
    sections = detect_sections("Preamble text.\n\n# Heading\n\nBody")
    assert sections[0].heading is None
    assert sections[0].text == "Preamble text."


def test_empty_input_produces_no_sections():
    assert detect_sections("   \n\n ") == ()


def test_html_boilerplate_is_dropped():
    registry = ParserRegistry()
    parsed = registry.parse(
        b"<html><head><title>Doc</title><style>a{}</style></head>"
        b"<body><script>evil()</script><p>Real content.</p></body></html>",
        "text/html",
    )
    assert "evil" not in parsed.text
    assert "a{}" not in parsed.text
    assert "Real content." in parsed.text
    assert parsed.title == "Doc"


def test_content_type_parameters_are_ignored():
    registry = ParserRegistry()
    parsed = registry.parse(b"<p>Hello</p>", "text/html; charset=utf-8")
    assert "Hello" in parsed.text


def test_an_unknown_content_type_fails_loudly():
    with pytest.raises(UnsupportedContentTypeError, match="no parser"):
        ParserRegistry().parse(b"\x00", "application/vnd.unknown")


def test_undecodable_bytes_do_not_crash_the_parser():
    parsed = PlainTextParser().parse(b"caf\xff\xfe text")
    assert "text" in parsed.text


def test_pdf_parsing_reports_the_missing_extra_rather_than_an_import_error():
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        from econiq_ingestion import ParserNotAvailableError, PdfParser

        with pytest.raises(ParserNotAvailableError, match="parsers"):
            PdfParser().parse(b"%PDF-1.4")
