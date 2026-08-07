"""Adversarial critique, against a real database."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_agents import Independence, ProcessCritiqueStage
from econiq_data_models import (
    Claim,
    Critique,
    Document,
    Event,
    EventClaim,
    EvidenceLink,
    Node,
    Process,
    ProcessState,
    Scorecard,
    ScoreDimension,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import (
    ClaimType,
    CritiqueKind,
    CritiqueStatus,
    DocumentType,
    EntityType,
    EpistemicStatus,
    EventType,
    ExtractionStatus,
    ProcessArchetype,
    ProcessStatus,
    ScoreFamily,
    ThesisQualityDimension,
)
from econiq_ontology import (
    ProcessStateLabel as S,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


async def _seed_process(session_factory, *, with_state: bool = True) -> uuid.UUID:
    """A Process with evidence behind it, the shape issues #8–#9 leave."""
    process_id, event_id = uuid.uuid4(), uuid.uuid4()
    document_id, claim_id = uuid.uuid4(), uuid.uuid4()

    async with session_factory() as session:
        for node_id, node_type in (
            (process_id, EntityType.PROCESS),
            (event_id, EntityType.EVENT),
            (document_id, EntityType.DOCUMENT),
            (claim_id, EntityType.CLAIM),
        ):
            session.add(Node(node_id=node_id, node_type=node_type))
        await session.flush()
        session.add(
            Process(
                process_id=process_id,
                revision=1,
                name="AI infrastructure expansion",
                slug=f"ai-infra-{process_id.hex[:6]}",
                description="Compute demand is driving a durable power buildout.",
                archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
                archetype_confidence=0.8,
                status=ProcessStatus.ACTIVE,
            )
        )
        session.add(
            Document(
                document_id=document_id,
                source="feed",
                publisher="Reuters",
                title="Capex guidance raised",
                document_type=DocumentType.NEWS_ARTICLE,
                publication_time=PUB,
                retrieved_at=PUB + timedelta(minutes=1),
                content_hash=uuid.uuid4().hex,
                extraction_status=ExtractionStatus.PARSED,
            )
        )
        session.add(
            Event(
                event_id=event_id,
                revision=1,
                event_type=EventType.CAPEX_ANNOUNCEMENT,
                title="Hyperscaler raises capex guidance",
                description="Planned datacentre spending was revised upward.",
                occurred_at=PUB,
                entities=[],
                independent_source_count=2,
                novelty=7.0,
                materiality=8.0,
                confidence=0.9,
                epistemic_status=EpistemicStatus.OBSERVED,
                contradictions=[],
                propagated_at=PUB,
            )
        )
        await session.flush()
        session.add(
            Claim(
                claim_id=claim_id,
                document_id=document_id,
                text="Planned datacentre spending was revised upward for 2027.",
                claim_type=ClaimType.REPORTED_CLAIM,
                source_location={"quote": "revised upward"},
                extraction_confidence=0.9,
                entities=[],
            )
        )
        session.add(EventClaim(event_id=event_id, claim_id=claim_id))
        session.add(
            EvidenceLink(subject_id=process_id, evidence_id=event_id, supports=True, weight=0.9)
        )
        if with_state:
            session.add(
                ProcessState(
                    process_id=process_id,
                    observed_at=PUB,
                    archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
                    categorical_state=S.ACCELERATION,
                    state_confidence=0.82,
                    transition_beliefs={},
                    transition_indicators=[],
                    reversal_indicators=[],
                )
            )
        await session.commit()
    return process_id


def _critique(
    kind: str = "unsupported_assumption",
    *,
    severity: float = 7.0,
    statement: str = "The thesis assumes interconnection queues clear by 2028.",
    rationale: str = "No supplied evidence speaks to queue times.",
    testable_with: str | None = "Published interconnection queue statistics.",
) -> dict:
    return {
        "kind": kind,
        "statement": statement,
        "severity": severity,
        "rationale": rationale,
        "testable_with": testable_with,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _output(*critiques: dict, risk: float = 6.5, index: int | None = 0) -> str:
    return json.dumps(
        {
            "critiques": list(critiques),
            "falsification_risk": risk,
            "most_damaging_critique_index": index if critiques else None,
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _stage(session_factory, *responses: str) -> ProcessCritiqueStage:
    return ProcessCritiqueStage(
        LLMService(ScriptedProvider(responses), observers=[]), session_factory
    )


async def test_findings_are_stored_against_the_process(session_factory):
    process_id = await _seed_process(session_factory)
    stage = _stage(
        session_factory,
        _output(
            _critique(severity=5.0),
            _critique("falsifying_indicator", severity=8.0),
            index=1,
        ),
    )

    outcome = await stage.run(process_id)

    assert outcome.found == 2
    assert outcome.falsification_risk == pytest.approx(6.5)

    async with session_factory() as session:
        rows = (await session.execute(select(Critique).order_by(Critique.severity))).scalars().all()

    assert [row.kind for row in rows] == [
        CritiqueKind.UNSUPPORTED_ASSUMPTION,
        CritiqueKind.FALSIFYING_INDICATOR,
    ]
    assert all(row.status is CritiqueStatus.OPEN for row in rows)
    assert all(row.subject_id == process_id for row in rows)
    # The worst finding is flagged, because the scorer and the UI lead with it.
    assert [row.is_most_damaging for row in rows] == [False, True]
    assert rows[1].testable_with


async def test_the_falsification_risk_becomes_a_thesis_quality_dimension(session_factory):
    """'Surfaced in scoring' means the scorer can read it, decomposed."""
    process_id = await _seed_process(session_factory)
    await _stage(session_factory, _output(_critique(severity=9.0), risk=7.5)).run(process_id)

    async with session_factory() as session:
        scorecard = (await session.execute(select(Scorecard))).scalar_one()
        dimension = (await session.execute(select(ScoreDimension))).scalar_one()

    assert scorecard.family is ScoreFamily.THESIS_QUALITY
    assert scorecard.subject_id == process_id
    # A single contributed dimension is not a summary of the family.
    assert scorecard.composite is None
    assert dimension.dimension == ThesisQualityDimension.CONTRADICTION.value
    assert dimension.value == pytest.approx(7.5)
    assert dimension.inputs["max_severity"] == pytest.approx(9.0)
    assert dimension.inputs["critique_count"] == pytest.approx(1.0)


async def test_a_rescued_critique_is_refused_and_nothing_is_stored(session_factory):
    process_id = await _seed_process(session_factory)
    stage = _stage(
        session_factory,
        _output(
            _critique(rationale="No evidence speaks to this, however the thesis remains sound.")
        ),
    )

    outcome = await stage.run(process_id)

    assert outcome.found == 0
    assert "rescue" in (outcome.rejected_reason or "").lower() or "argue" in (
        outcome.rejected_reason or ""
    )
    assert outcome.critic_run_id is not None  # the run is kept as the record

    async with session_factory() as session:
        stored = (await session.execute(select(func.count()).select_from(Critique))).scalar_one()
    assert stored == 0


async def test_a_later_pass_supersedes_but_never_deletes(session_factory):
    """A thesis that survived four attacks is only visible if they stay."""
    process_id = await _seed_process(session_factory)
    await _stage(session_factory, _output(_critique(statement="First objection."))).run(process_id)
    outcome = await _stage(session_factory, _output(_critique(statement="Second objection."))).run(
        process_id
    )

    assert outcome.superseded == 1

    async with session_factory() as session:
        rows = (
            (await session.execute(select(Critique).order_by(Critique.recorded_at))).scalars().all()
        )

    assert len(rows) == 2
    assert rows[0].status is CritiqueStatus.ADDRESSED
    assert rows[0].resolved_at is not None
    assert "superseded" in (rows[0].resolution_note or "")
    assert rows[1].status is CritiqueStatus.OPEN


async def test_coverage_across_the_seven_lines_of_attack_is_measured(session_factory):
    process_id = await _seed_process(session_factory)
    outcome = await _stage(
        session_factory,
        _output(
            _critique("unsupported_assumption"),
            _critique("alternative_explanation"),
            _critique("spurious_correlation"),
            index=0,
        ),
    ).run(process_id)

    assert outcome.coverage is not None
    assert outcome.coverage.ratio == pytest.approx(3 / 7)
    assert CritiqueKind.HISTORICAL_COUNTEREXAMPLE in outcome.coverage.missing


async def test_a_process_with_no_evidence_is_not_critiqued(session_factory):
    """Critiquing a thesis with nothing in front of you produces speculation."""
    process_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=process_id, node_type=EntityType.PROCESS))
        await session.flush()
        session.add(
            Process(
                process_id=process_id,
                revision=1,
                name="Speculative process",
                slug="speculative",
                description="…",
                status=ProcessStatus.CANDIDATE,
            )
        )
        await session.commit()

    outcome = await _stage(session_factory).run(process_id)

    assert outcome.skipped_reason == "no evidence to critique against"


async def test_independence_is_recorded_not_assumed(session_factory):
    process_id = await _seed_process(session_factory)

    outcome = await _stage(session_factory, _output(_critique())).run(process_id)
    # Nothing else has run on this graph, so there is no thesis model to differ
    # from — the honest answer is prompt-level independence.
    assert outcome.independence is Independence.PROMPT_ONLY


async def test_a_distinct_critic_model_is_reported_as_such(session_factory):
    from econiq_data_models import AgentRun, AgentRunStatus, ModelVersion

    process_id = await _seed_process(session_factory)
    model_version_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            ModelVersion(
                model_version_id=model_version_id, provider="scripted", model="thesis-model"
            )
        )
        await session.flush()
        session.add(
            AgentRun(
                agent_run_id=uuid.uuid4(),
                agent_name="process_update",
                agent_version="1.0.0",
                ontology_layer="Event → Process",
                model_version_id=model_version_id,
                input_schema_version="1.0.0",
                as_of=PUB,
                status=AgentRunStatus.SUCCEEDED,
                input_payload={},
                trigger_event_id=uuid.uuid4(),
            )
        )
        await session.commit()

    stage = ProcessCritiqueStage(
        LLMService(ScriptedProvider([_output(_critique())]), observers=[]),
        session_factory,
        critic_model="a-different-model",
    )
    outcome = await stage.run(process_id)

    assert outcome.independence is Independence.DISTINCT_MODEL


async def test_only_processes_whose_thesis_moved_are_re_critiqued(session_factory):
    process_id = await _seed_process(session_factory)
    await _stage(session_factory, _output(_critique())).run_pending()

    assert await _stage(session_factory).run_pending() == []

    async with session_factory() as session:
        session.add(
            ProcessState(
                process_id=process_id,
                observed_at=PUB + timedelta(days=1),
                archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
                categorical_state=S.INFRASTRUCTURE_EXPANSION,
                state_confidence=0.8,
                transition_beliefs={},
                transition_indicators=[],
                reversal_indicators=[],
            )
        )
        await session.commit()

    again = await _stage(session_factory, _output(_critique())).run_pending()
    assert [o.process_id for o in again] == [process_id]
