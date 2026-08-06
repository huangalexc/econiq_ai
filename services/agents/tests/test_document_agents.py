"""Grounding: a Claim that does not quote the document is not evidence."""

from datetime import UTC, datetime

from econiq_agents import (
    ClaimExtractionAgent,
    QuoteGroundingEvaluator,
    normalize_for_matching,
    resolve_span,
)
from econiq_ingestion import ParserRegistry
from econiq_llm import LLMService, ScriptedProvider
from econiq_schemas import ClaimExtractionInput, ClaimExtractionOutput

PUB = datetime(2026, 7, 14, tzinfo=UTC)

ARTICLE = """\
STRATEGIC MINERALS

The Pentagon acquired a 15 percent stake in MP Materials on Monday.
The company said it would expand its Mountain Pass separation facility.
"""


def _document():
    return ParserRegistry().parse(ARTICLE.encode(), "text/plain")


def _input(text: str = ARTICLE) -> ClaimExtractionInput:
    return ClaimExtractionInput(
        as_of=PUB,
        document_id="doc-1",
        document_type="news_article",
        publisher="Reuters",
        publication_time=PUB,
        text=text,
    )


def _claim(quote: str, text: str = "The Pentagon acquired a stake in MP Materials.") -> dict:
    return {
        "text": text,
        "assertion_source": "observed_fact",
        "source_location": {"quote": quote, "section": "STRATEGIC MINERALS"},
        "extraction_confidence": 0.95,
        "entities": [],
        "stated_at": None,
        "attributed_to": None,
        "schema_version": "1.0.0",
    }


def _output(*claims: dict) -> ClaimExtractionOutput:
    return ClaimExtractionOutput.model_validate(
        {
            "claims": list(claims),
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def test_a_real_quote_passes():
    checks = QuoteGroundingEvaluator().evaluate(
        _input(), _output(_claim("acquired a 15 percent stake in MP Materials"))
    )
    assert all(check.passed for check in checks)


def test_a_fabricated_quote_fails():
    checks = QuoteGroundingEvaluator().evaluate(
        _input(), _output(_claim("acquired a 40 percent stake in Lynas"))
    )
    failed = [c for c in checks if not c.passed]
    assert [c.name for c in failed] == ["quotes_appear_in_document"]
    assert "Lynas" in (failed[0].detail or "")


def test_a_claim_with_no_quote_is_flagged_separately():
    claim = _claim("")
    claim["source_location"] = {"paragraph": 2}
    checks = {c.name: c for c in QuoteGroundingEvaluator().evaluate(_input(), _output(claim))}
    assert checks["claims_carry_a_quote"].passed is False
    assert checks["quotes_appear_in_document"].passed is True


def test_typographic_differences_do_not_fail_a_real_quote():
    """A curly apostrophe is not a hallucination."""
    text = "The company said it wouldn't expand."
    checks = QuoteGroundingEvaluator().evaluate(_input(text), _output(_claim("wouldn’t expand")))
    assert all(check.passed for check in checks)


def test_whitespace_is_folded_for_matching():
    assert normalize_for_matching("A   line\n\nhere") == "a line here"


def test_resolve_span_returns_real_offsets_and_the_section():
    document = _document()
    span = resolve_span("expand its Mountain Pass separation facility", document)

    assert span is not None
    assert document.text[span.char_start : span.char_end] == (
        "expand its Mountain Pass separation facility"
    )
    assert span.section_heading == "STRATEGIC MINERALS"


def test_resolve_span_handles_reflowed_whitespace():
    document = _document()
    span = resolve_span("The Pentagon acquired a 15  percent stake", document)
    assert span is not None
    assert document.text[span.char_start :].startswith("The Pentagon acquired")


def test_resolve_span_refuses_to_guess():
    assert resolve_span("a quote that is not there", _document()) is None
    assert resolve_span("", _document()) is None


async def test_the_extraction_agent_attaches_grounding_by_default():
    payload = _input()
    response = _output(_claim("acquired a 15 percent stake in MP Materials")).model_dump_json()
    agent = ClaimExtractionAgent(LLMService(ScriptedProvider([response]), observers=[]))

    result = await agent.run(payload)

    assert result.evaluation.passed
    assert result.output.claims[0].claim_type.value == "derived_fact"


async def test_an_ungrounded_extraction_is_reported_as_failing():
    payload = _input()
    response = _output(_claim("acquired a 40 percent stake in Lynas")).model_dump_json()
    agent = ClaimExtractionAgent(LLMService(ScriptedProvider([response]), observers=[]))

    result = await agent.run(payload)

    assert not result.evaluation.passed
    assert result.evaluation.failures[0].name == "quotes_appear_in_document"
