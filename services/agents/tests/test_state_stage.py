"""Archetype classification and State estimation, against a real database."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_agents import ProcessStateStage
from econiq_data_models import (
    Event,
    EvidenceLink,
    JournalEntry,
    JournalEntryKind,
    Node,
    Process,
    ProcessState,
    ProcessStateFeature,
    ValueBasis,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import (
    EntityType,
    EpistemicStatus,
    EventType,
    ProcessArchetype,
    ProcessStatus,
)
from econiq_ontology import (
    ProcessStateLabel as S,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

PUB = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
S_CURVE = ProcessArchetype.INFRASTRUCTURE_S_CURVE


async def _seed_process(
    session_factory,
    *,
    archetype: ProcessArchetype | None = None,
    status: ProcessStatus = ProcessStatus.ACTIVE,
    event_at: datetime = PUB,
) -> uuid.UUID:
    """A Process with one supporting Event, the shape issue #8 leaves behind."""
    process_id, event_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=process_id, node_type=EntityType.PROCESS, slug="ai-infra"))
        session.add(Node(node_id=event_id, node_type=EntityType.EVENT))
        await session.flush()
        session.add(
            Process(
                process_id=process_id,
                revision=1,
                name="AI infrastructure expansion",
                slug="ai-infra",
                description="Compute demand is driving a datacentre and power buildout.",
                archetype=archetype,
                archetype_confidence=0.8 if archetype else None,
                status=status,
            )
        )
        session.add(
            Event(
                event_id=event_id,
                revision=1,
                event_type=EventType.CAPEX_ANNOUNCEMENT,
                title="Hyperscaler raises capex guidance",
                description="Planned datacentre spending was revised upward.",
                occurred_at=event_at,
                entities=[],
                independent_source_count=3,
                novelty=7.0,
                materiality=8.0,
                confidence=0.9,
                epistemic_status=EpistemicStatus.OBSERVED,
                contradictions=[],
                propagated_at=event_at,
            )
        )
        await session.flush()
        session.add(
            EvidenceLink(subject_id=process_id, evidence_id=event_id, supports=True, weight=0.9)
        )
        session.add(
            JournalEntry(
                subject_id=process_id,
                subject_type=EntityType.PROCESS,
                kind=JournalEntryKind.CREATED,
                observed_at=event_at,
                summary="Process created.",
                changes=[],
            )
        )
        await session.commit()
    return process_id


def _archetype(primary: str = "infrastructure_s_curve") -> str:
    rejected = [
        a
        for a in (
            "commodity_supply_cycle",
            "industrial_bottleneck",
            "regulatory_implementation",
            "business_model_disruption",
            "infrastructure_s_curve",
        )
        if a != primary
    ]
    return json.dumps(
        {
            "primary_archetype": primary,
            "secondary_archetypes": [],
            "rejected": [
                {"archetype": a, "reason": "…", "schema_version": "1.0.0"} for a in rejected
            ],
            "reasons": "Buildout precedes demand, which is the S-curve pattern.",
            "confidence": 0.85,
            "supporting_claim_ids": [],
            "contradicting_claim_ids": [],
            "evidence": [],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _state(
    state: S = S.ACCELERATION,
    *,
    archetype: ProcessArchetype = S_CURVE,
    features=(("capex_acceleration", 8.7),),
    transitions=None,
) -> str:
    return json.dumps(
        {
            "archetype": archetype.value,
            "categorical_state": state.value,
            "state_confidence": 0.82,
            "features": [
                {"name": name, "value": value, "rationale": "…", "schema_version": "1.0.0"}
                for name, value in features
            ],
            "transition_beliefs": transitions or {},
            "transition_indicators": ["Interconnection queues shortening"],
            "reversal_indicators": ["Capex guidance cut"],
            "supporting_claim_ids": [],
            "contradicting_claim_ids": [],
            "evidence": [],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


async def _seed_agent_run(session_factory) -> uuid.UUID:
    """A real agent run, because every derived row must cite one."""
    from econiq_data_models import AgentRun, AgentRunStatus

    run_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            AgentRun(
                agent_run_id=run_id,
                agent_name="process_archetype",
                agent_version="1.0.0",
                ontology_layer="Process",
                input_schema_version="1.0.0",
                as_of=PUB,
                status=AgentRunStatus.SUCCEEDED,
                input_payload={},
            )
        )
        await session.commit()
    return run_id


def _stage(session_factory, *responses: str) -> ProcessStateStage:
    return ProcessStateStage(LLMService(ScriptedProvider(responses), observers=[]), session_factory)


async def test_an_unclassified_process_is_classified_then_estimated(session_factory):
    process_id = await _seed_process(session_factory)
    stage = _stage(session_factory, _archetype(), _state())

    outcome = await stage.run(process_id)

    assert outcome.archetype is not None
    assert outcome.archetype.archetype is S_CURVE
    assert outcome.state is not None
    assert outcome.state.categorical_state is S.ACCELERATION

    async with session_factory() as session:
        process = (
            await session.execute(select(Process).where(Process.valid_to.is_(None)))
        ).scalar_one()
        state = (await session.execute(select(ProcessState))).scalar_one()

    assert process.archetype is S_CURVE
    assert process.archetype_confidence == pytest.approx(0.85)
    assert process.revision == 2
    # The estimate is dated by its evidence, not by wall-clock time.
    assert state.observed_at == PUB
    assert state.transition_indicators == ["Interconnection queues shortening"]


async def test_a_classified_process_is_not_reclassified(session_factory):
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    stage = _stage(session_factory, _state())

    outcome = await stage.run(process_id)

    assert outcome.archetype is None
    assert outcome.state is not None


async def test_features_are_marked_measured_only_when_they_were_measured(session_factory):
    """The agent may interpret a measurement; it may not relabel its own guess."""
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    await _stage(session_factory, _state(features=(("capex_acceleration", 8.7),))).run(process_id)

    # The second run is given the first run's features as measurements.
    await _stage(
        session_factory,
        _state(
            S.ACCELERATION,
            features=(("capex_acceleration", 8.7), ("speculation", 4.1)),
        ),
    ).run(process_id)

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ProcessStateFeature)
                    .join(
                        ProcessState,
                        ProcessState.process_state_id == ProcessStateFeature.process_state_id,
                    )
                    .order_by(ProcessState.recorded_at.desc(), ProcessStateFeature.name)
                )
            )
            .scalars()
            .all()
        )
    latest = {row.name: row.basis for row in rows[:2]}
    assert latest["capex_acceleration"] is ValueBasis.MEASURED
    assert latest["speculation"] is ValueBasis.ESTIMATED


async def test_state_history_is_appended_never_overwritten(session_factory):
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    await _stage(session_factory, _state(S.EARLY_ADOPTION)).run(process_id)
    await _stage(session_factory, _state(S.ACCELERATION)).run(process_id)

    async with session_factory() as session:
        states = (
            (await session.execute(select(ProcessState).order_by(ProcessState.recorded_at)))
            .scalars()
            .all()
        )

    assert [s.categorical_state for s in states] == [S.EARLY_ADOPTION, S.ACCELERATION]
    assert states[1].previous_state_id == states[0].process_state_id


async def test_a_transition_is_journalled_with_confidence_either_side(session_factory):
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    await _stage(session_factory, _state(S.EARLY_ADOPTION)).run(process_id)
    await _stage(session_factory, _state(S.ACCELERATION)).run(process_id)

    async with session_factory() as session:
        entry = (
            await session.execute(
                select(JournalEntry).where(JournalEntry.kind == JournalEntryKind.STATE_CHANGE)
            )
        ).scalar_one()

    assert entry.summary == "State early_adoption → acceleration"
    assert entry.confidence_before == pytest.approx(0.82)
    assert entry.confidence_after == pytest.approx(0.82)


async def test_holding_the_same_state_writes_no_transition_entry(session_factory):
    """A Process that stays put through an Event is a normal, informative result."""
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    await _stage(session_factory, _state(S.ACCELERATION)).run(process_id)
    await _stage(session_factory, _state(S.ACCELERATION)).run(process_id)

    async with session_factory() as session:
        transitions = (
            await session.execute(
                select(func.count())
                .select_from(JournalEntry)
                .where(JournalEntry.kind == JournalEntryKind.STATE_CHANGE)
            )
        ).scalar_one()
        states = (
            await session.execute(select(func.count()).select_from(ProcessState))
        ).scalar_one()

    assert transitions == 0
    # The observation is still recorded — holding a State is evidence too.
    assert states == 2


async def test_an_illegal_transition_is_refused_and_nothing_is_written(session_factory):
    """A model cannot teleport a Process from Discovery to Maturity."""
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    await _stage(session_factory, _state(S.DISCOVERY)).run(process_id)

    outcome = await _stage(session_factory, _state(S.MATURITY)).run(process_id)

    assert outcome.state is None
    assert "not a permitted transition" in (outcome.skipped_reason or "")

    async with session_factory() as session:
        states = (
            (await session.execute(select(ProcessState).order_by(ProcessState.recorded_at)))
            .scalars()
            .all()
        )
    assert [s.categorical_state for s in states] == [S.DISCOVERY]


async def test_a_major_transition_asks_for_human_review(session_factory):
    """State determines analog selection, so a big move goes back to a human."""
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    await _stage(session_factory, _state(S.EARLY_ADOPTION)).run(process_id)

    # One step along the sequence is ordinary progress.
    outcome = await _stage(session_factory, _state(S.ACCELERATION)).run(process_id)
    assert outcome.state is not None and outcome.state.requires_review is False

    # acceleration → saturation is permitted but skips infrastructure_expansion,
    # so it is a major move.
    major = await _stage(session_factory, _state(S.SATURATION)).run(process_id)

    assert major.state is not None
    assert major.state.transition.steps == 2
    assert major.requires_review

    async with session_factory() as session:
        process = (
            await session.execute(select(Process).where(Process.valid_to.is_(None)))
        ).scalar_one()
    assert process.requires_review is True


async def test_reclassification_drops_a_prior_state_from_the_old_vocabulary(session_factory):
    """Past State labels come from the old machine and no longer mean anything."""
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    await _stage(session_factory, _state(S.ACCELERATION)).run(process_id)

    from econiq_agents import StateWriter
    from econiq_schemas import ProcessArchetypeOutput

    writer = StateWriter(session_factory)
    applied = await writer.apply_archetype(
        process_id,
        ProcessArchetypeOutput.model_validate(json.loads(_archetype("industrial_bottleneck"))),
        agent_run_id=await _seed_agent_run(session_factory),
        observed_at=PUB,
    )
    assert applied.reclassified
    assert applied.invalidated_states == 1

    outcome = await _stage(
        session_factory,
        _state(S.CONSTRAINT_BINDING, archetype=ProcessArchetype.INDUSTRIAL_BOTTLENECK),
    ).run(process_id)

    assert outcome.state is not None
    assert outcome.state.categorical_state is S.CONSTRAINT_BINDING
    assert any("superseded archetype" in note for note in outcome.notes)


async def test_only_stale_processes_are_re_estimated(session_factory):
    process_id = await _seed_process(session_factory, archetype=S_CURVE)
    await _stage(session_factory, _state()).run(process_id)

    # Nothing has happened since, so nothing should be re-estimated.
    assert await _stage(session_factory).run_pending() == []

    async with session_factory() as session:
        session.add(
            JournalEntry(
                subject_id=process_id,
                subject_type=EntityType.PROCESS,
                kind=JournalEntryKind.BELIEF_CHANGE,
                observed_at=PUB + timedelta(days=1),
                summary="Beliefs moved.",
                changes=[],
            )
        )
        await session.commit()

    outcomes = await _stage(session_factory, _state()).run_pending()
    assert [o.process_id for o in outcomes] == [process_id]
