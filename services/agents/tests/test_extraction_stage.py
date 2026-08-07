"""Document → Claims, against a real database.

The chain this exercises is the one issue #17 gates on: a document arrives,
Claims come out, and every Claim points back at a span of the document that
actually exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from econiq_agents import DocumentExtractionStage
from econiq_data_models import AgentRun, AgentRunStatus, Claim, PromptVersion
from econiq_ingestion import (
    IngestionPipeline,
    InMemoryObjectStore,
    RawDocument,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import ClaimType, DocumentType
from econiq_schemas import InformationMode
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

ARTICLE = b"""\
STRATEGIC MINERALS

The Pentagon acquired a 15 percent stake in MP Materials on Monday.
MP Materials said it expects to double separation capacity by 2028.
"""


def _classification(mode: str = "textual") -> str:
    return (
        '{"document_type": "news_article", "source_type": "wire_service",'
        f' "primary_information_mode": "{mode}",'
        ' "named_entities": [{"text": "MP Materials", "kind": "company",'
        ' "resolved_id": null, "schema_version": "1.0.0"}],'
        ' "likely_event_types": ["government_funding"],'
        ' "extraction_strategy": "textual claim extraction", "confidence": 0.9,'
        ' "abstained": false, "abstention_reason": null, "uncertainty_notes": [],'
        ' "schema_version": "1.0.0"}'
    )


def _extraction(*claims: str) -> str:
    return (
        '{"claims": [' + ", ".join(claims) + '], "abstained": false,'
        ' "abstention_reason": null, "uncertainty_notes": [], "schema_version": "1.0.0"}'
    )


def _claim(text: str, quote: str, assertion: str = "observed_fact") -> str:
    return (
        f'{{"text": "{text}", "assertion_source": "{assertion}",'
        f' "source_location": {{"quote": "{quote}", "section": "STRATEGIC MINERALS",'
        ' "page": null, "paragraph": null, "char_start": null, "char_end": null,'
        ' "schema_version": "1.0.0"},'
        ' "extraction_confidence": 0.95, "entities": [], "stated_at": null,'
        ' "attributed_to": null, "schema_version": "1.0.0"}'
    )


@pytest.fixture
async def ingested(session_factory):
    pipeline = IngestionPipeline(InMemoryObjectStore(), session_factory)
    result = await pipeline.ingest(
        RawDocument(
            source="reuters-rss",
            title="Pentagon takes stake in MP Materials",
            content=ARTICLE,
            content_type="text/plain",
            publication_time=PUB,
            retrieved_at=PUB + timedelta(minutes=2),
            publisher="Reuters",
            document_type=DocumentType.NEWS_ARTICLE,
        )
    )
    assert result.parsed is not None
    return result


def _stage(session_factory, *responses: str) -> DocumentExtractionStage:
    return DocumentExtractionStage(
        LLMService(ScriptedProvider(responses), observers=[]), session_factory
    )


async def test_claims_are_persisted_with_verified_spans(ingested, session_factory):
    stage = _stage(
        session_factory,
        _classification(),
        _extraction(
            _claim(
                "The Pentagon acquired a 15 percent stake in MP Materials.",
                "acquired a 15 percent stake in MP Materials",
            ),
            _claim(
                "MP Materials expects to double separation capacity by 2028.",
                "expects to double separation capacity by 2028",
                assertion="company_forecast",
            ),
        ),
    )

    outcome = await stage.run(ingested.document_id, ingested.parsed)

    assert outcome.claims is not None
    assert outcome.claims.accepted == 2
    assert outcome.claims.hallucination_rate == 0.0

    async with session_factory() as session:
        rows = (await session.execute(select(Claim).order_by(Claim.text))).scalars().all()

    assert len(rows) == 2
    forecast = next(r for r in rows if "double separation" in r.text)
    # A company forecast is a hypothesis, not a reported fact.
    assert forecast.claim_type is ClaimType.HYPOTHESIS
    assert forecast.assertion_source == "company_forecast"

    for row in rows:
        location = row.source_location
        assert location["section"] == "STRATEGIC MINERALS"
        # The stored offsets index into the real document, not the model's guess.
        assert (
            ingested.parsed.text[location["char_start"] : location["char_end"]]
            == (location["quote"])
        )
        assert row.agent_run_id == outcome.extraction_run_id


async def test_an_ungrounded_claim_is_dropped_and_counted(ingested, session_factory):
    stage = _stage(
        session_factory,
        _classification(),
        _extraction(
            _claim(
                "The Pentagon acquired a 15 percent stake in MP Materials.",
                "acquired a 15 percent stake in MP Materials",
            ),
            _claim(
                "Lynas agreed to supply the Pentagon.",
                "Lynas agreed to supply the Pentagon",
            ),
        ),
    )

    outcome = await stage.run(ingested.document_id, ingested.parsed)

    assert outcome.claims is not None
    assert outcome.claims.accepted == 1
    assert outcome.claims.rejected == ["Lynas agreed to supply the Pentagon."]
    assert outcome.claims.hallucination_rate == pytest.approx(0.5)

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(Claim))).scalar_one()
    assert count == 1


async def test_a_rejected_run_is_recorded_as_such(ingested, session_factory):
    """A run whose output failed a deterministic check is not a success."""
    stage = _stage(
        session_factory,
        _classification(),
        _extraction(_claim("Lynas agreed to supply.", "Lynas agreed to supply")),
    )

    outcome = await stage.run(ingested.document_id, ingested.parsed)

    async with session_factory() as session:
        run = await session.get(AgentRun, outcome.extraction_run_id)
    assert run is not None
    assert run.status is AgentRunStatus.REJECTED
    assert run.evaluation["passed"] is False


async def test_quantitative_documents_are_left_to_the_etl_service(ingested, session_factory):
    """Reconstructing figures from prose with an LLM is what tech rec §20 forbids."""
    stage = _stage(session_factory, _classification(mode="quantitative"))

    outcome = await stage.run(ingested.document_id, ingested.parsed)

    assert outcome.information_mode is InformationMode.QUANTITATIVE
    assert not outcome.ran_extraction
    assert "ETL service" in (outcome.skipped_reason or "")

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(Claim))).scalar_one()
    assert count == 0


async def test_the_provenance_chain_is_complete(ingested, session_factory):
    stage = _stage(
        session_factory,
        _classification(),
        _extraction(
            _claim(
                "The Pentagon acquired a stake.",
                "acquired a 15 percent stake in MP Materials",
            )
        ),
    )

    outcome = await stage.run(ingested.document_id, ingested.parsed)

    async with session_factory() as session:
        claim = (await session.execute(select(Claim))).scalar_one()
        run = await session.get(AgentRun, claim.agent_run_id)
        assert run is not None
        prompt = await session.get(PromptVersion, run.prompt_version_id)

    # claim -> agent run -> prompt version (with its content hash) -> document
    assert run.agent_name == "claim_extraction"
    assert run.as_of == PUB
    assert prompt is not None
    assert prompt.name == "claim_extraction"
    assert len(prompt.content_hash) == 16
    assert claim.document_id == outcome.document_id
