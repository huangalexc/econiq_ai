"""Document Classifier and Claim Extraction agents (issue #6, agent doc §4).

The first LLM stage. Two properties are defended here rather than hoped for:

* **No invented facts.** Every Claim must quote a span that appears verbatim in
  the document. The quote is checked by code, not trusted — a Claim whose quote
  is not in the document is a hallucination, and hallucinations must not become
  evidence.
* **No investment implications.** These agents stop at the Claim layer. Nothing
  in their output schema can hold an asset view (agent doc §2.1).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from econiq_ingestion import ParsedDocument
from econiq_llm import Agent, EvaluationCheck, Evaluator, ModelTier
from econiq_schemas import (
    AgentInput,
    AgentOutput,
    ClaimExtractionInput,
    ClaimExtractionOutput,
    DocumentClassifierInput,
    DocumentClassifierOutput,
)

from econiq_agents.prompts import CLAIM_EXTRACTION_V1, DOCUMENT_CLASSIFIER_V1

#: Documents run long and models cost per token. The classifier only needs
#: enough to judge type and mode, so it sees the head of the document.
CLASSIFIER_EXCERPT_CHARS = 6_000


class DocumentClassifierAgent(Agent[DocumentClassifierInput, DocumentClassifierOutput]):
    """Routes a document (agent doc §4.1).

    Runs on the fast tier: it is high-volume, and a misrouted document is cheap
    to detect downstream — the extraction pipeline it lands in either finds
    Claims or does not.
    """

    name = "document_classifier"
    version = "1.0.0"
    ontology_layer = "Document"
    tier = ModelTier.FAST
    effort = "low"

    input_schema = DocumentClassifierInput
    output_schema = DocumentClassifierOutput
    prompt = DOCUMENT_CLASSIFIER_V1

    def build_user_content(self, payload: DocumentClassifierInput) -> str:
        return "\n".join(
            [
                f"Title: {payload.title}",
                f"Publisher: {payload.publisher or 'unknown'}",
                f"Source feed: {payload.source}",
                f"Published: {payload.publication_time.isoformat()}",
                "",
                "Document (truncated):",
                payload.text[:CLASSIFIER_EXCERPT_CHARS],
            ]
        )


class ClaimExtractionAgent(Agent[ClaimExtractionInput, ClaimExtractionOutput]):
    """Document → Claims (agent doc §4.2).

    Runs on the standard tier with the grounding evaluator attached by default:
    extraction quality is dominated by whether spans are real, and that is
    exactly what code can check.
    """

    name = "claim_extraction"
    version = "1.0.0"
    ontology_layer = "Document → Claim"
    tier = ModelTier.STANDARD

    input_schema = ClaimExtractionInput
    output_schema = ClaimExtractionOutput
    prompt = CLAIM_EXTRACTION_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        # Grounding replaces the generic citation check: this agent invents the
        # citations rather than resolving supplied ones, so what matters is
        # whether its quotes exist in the document.
        return (QuoteGroundingEvaluator(),)

    def build_user_content(self, payload: ClaimExtractionInput) -> str:
        return "\n".join(
            [
                f"Document type: {payload.document_type.value}",
                f"Publisher: {payload.publisher or 'unknown'}",
                f"Published: {payload.publication_time.isoformat()}",
                "",
                "Document:",
                payload.text,
            ]
        )


@dataclass(frozen=True, slots=True)
class ResolvedSpan:
    """Where a quoted claim actually sits in the document."""

    char_start: int
    char_end: int
    section_index: int | None
    section_heading: str | None


class QuoteGroundingEvaluator:
    """Checks that every Claim quotes text the document actually contains.

    Whitespace and unicode punctuation are normalized before comparison —
    models routinely turn a straight quote into a curly one, and failing a
    correct extraction over an apostrophe would be noise. Anything beyond that
    is a fabricated span.
    """

    def __init__(self, *, min_quote_chars: int = 12) -> None:
        self.min_quote_chars = min_quote_chars

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(payload, ClaimExtractionInput) or not isinstance(
            output, ClaimExtractionOutput
        ):
            return ()

        haystack = normalize_for_matching(payload.text)
        ungrounded: list[str] = []
        missing_quote: list[str] = []

        for claim in output.claims:
            quote = claim.source_location.quote
            if not quote:
                missing_quote.append(claim.text[:60])
                continue
            if normalize_for_matching(quote) not in haystack:
                ungrounded.append(quote[:60])

        checks = [
            EvaluationCheck(
                name="quotes_appear_in_document",
                passed=not ungrounded,
                detail=None if not ungrounded else f"quotes not found: {ungrounded}",
            ),
            EvaluationCheck(
                name="claims_carry_a_quote",
                passed=not missing_quote,
                detail=None if not missing_quote else f"claims without a quote: {missing_quote}",
            ),
        ]
        return checks


_WHITESPACE = re.compile(r"\s+")
_QUOTE_CHARS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def normalize_for_matching(text: str) -> str:
    """Fold the differences that do not change what a quote says."""
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTE_CHARS)
    return _WHITESPACE.sub(" ", folded).strip().lower()


def resolve_span(quote: str, document: ParsedDocument) -> ResolvedSpan | None:
    """Locate a quote in the document and return its real offsets.

    The agent proposes the quote; code decides where it is. Storing offsets the
    model guessed would make the provenance inspector confidently wrong, which
    is worse than having no offsets at all.
    """
    if not quote:
        return None

    found = document.text.find(quote)
    index = found if found != -1 else _find_normalized(quote, document.text)
    if index is None:
        return None

    section = document.section_at(index)
    return ResolvedSpan(
        char_start=index,
        char_end=index + len(quote),
        section_index=section.index if section else None,
        section_heading=section.heading if section else None,
    )


def _find_normalized(quote: str, text: str) -> int | None:
    """Locate a quote that differs only in whitespace or punctuation style.

    Walks the original text keeping a map back to real offsets, so the returned
    index still points into the untouched document.
    """
    needle = normalize_for_matching(quote)
    if not needle:
        return None

    folded_chars: list[str] = []
    offsets: list[int] = []
    previous_was_space = True
    for position, char in enumerate(unicodedata.normalize("NFKC", text).translate(_QUOTE_CHARS)):
        if char.isspace():
            if previous_was_space:
                continue
            folded_chars.append(" ")
            offsets.append(position)
            previous_was_space = True
            continue
        folded_chars.append(char.lower())
        offsets.append(position)
        previous_was_space = False

    found = "".join(folded_chars).find(needle)
    if found == -1:
        return None
    return offsets[found]
