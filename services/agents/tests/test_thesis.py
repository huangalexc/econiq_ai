"""Counterfactuals and Thesis Quality scoring (issues #65, #66)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_agents import thesis_measures
from econiq_agents.counterfactual_agent import (
    CounterfactualAgent,
    DiversityEvaluator,
    FalsifiabilityEvaluator,
    PlausibilityEvaluator,
)
from econiq_agents.thesis_scorer import (
    COMPUTED_AXES,
    JUDGED_AXES,
    UNAVAILABLE_AXES,
    AxisCoverageEvaluator,
    ReasoningEvaluator,
    ThesisScoringAgent,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import ProcessArchetype
from econiq_ontology import ThesisQualityDimension as Axis
from econiq_schemas import (
    CounterfactualInput,
    CounterfactualOutput,
    ProcessSummary,
    ThesisScoringInput,
    ThesisScoringOutput,
)

NOW = datetime(2026, 8, 1, tzinfo=UTC)

SUMMARY = ProcessSummary(
    process_id=str(uuid.uuid4()),
    name="Domestic strategic-mineral security",
    description="The state is underwriting domestic rare-earth separation capacity.",
    archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
)


def _world(
    assumption: str,
    *,
    plausibility: float = 6.0,
    severity: float = 7.0,
    indicators: list[str] | None = None,
    world: str = "Separation capacity arrives from allied refiners instead.",
) -> dict:
    return {
        "challenged_assumption": assumption,
        "alternative_world": world,
        "affected_links": ["Domestic capacity is the binding constraint"],
        "assets_harmed": ["MP"],
        "observable_indicators": indicators
        if indicators is not None
        else ["Allied separation tonnage reported above 5kt"],
        "plausibility": plausibility,
        "severity_if_true": severity,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _counterfactuals(*worlds: dict, most_dangerous: int | None = 0) -> str:
    return json.dumps(
        {
            "counterfactuals": list(worlds),
            "most_dangerous_index": most_dangerous if worlds else None,
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _cf_input() -> CounterfactualInput:
    return CounterfactualInput(
        as_of=NOW, process=SUMMARY, thesis_statement="Capacity is state-underwritten."
    )


# --------------------------------------------------------------------------- #
# #66 — straw men are caught, not requested away
# --------------------------------------------------------------------------- #


def test_counterfactuals_removing_the_same_assumption_are_rejected():
    """Three restatements of one assumption are one counterfactual.

    Blocking, because robustness is computed from the *set*: restatements would
    make a thesis look attacked from three directions when it was attacked from
    one, and the score would be wrong rather than merely generous.
    """
    output = CounterfactualOutput.model_validate_json(
        _counterfactuals(
            _world("Permitting timelines hold"),
            _world("Timelines for permitting will hold"),
        )
    )

    checks = DiversityEvaluator().evaluate(_cf_input(), output)

    assert checks[0].passed is False
    assert checks[0].blocking is True


def test_distinct_assumptions_pass():
    output = CounterfactualOutput.model_validate_json(
        _counterfactuals(
            _world("Permitting timelines hold"),
            _world("Chinese export policy stays restrictive"),
        )
    )

    assert DiversityEvaluator().evaluate(_cf_input(), output)[0].passed is True


def test_a_world_the_agent_calls_implausible_is_a_straw_man():
    """Agent doc §10.1 says no straw men; a prompt cannot make it so."""
    output = CounterfactualOutput.model_validate_json(
        _counterfactuals(_world("Demand collapses entirely", plausibility=1.0))
    )

    checks = PlausibilityEvaluator().evaluate(_cf_input(), output)

    assert checks[0].name == "no_straw_men"
    assert checks[0].passed is False
    assert checks[0].blocking is True


def test_an_indicator_that_restates_the_world_is_flagged_but_not_blocking():
    """A vague indicator is a weak finding, not an invalid one."""
    world_text = "Allied refiners commission separation capacity in 2027"
    output = CounterfactualOutput.model_validate_json(
        _counterfactuals(
            _world(
                "Domestic capacity is required",
                world=world_text,
                indicators=[world_text],
            )
        )
    )

    checks = FalsifiabilityEvaluator().evaluate(_cf_input(), output)

    assert checks[0].passed is False
    assert checks[0].blocking is False


def test_a_counterfactual_without_an_indicator_cannot_be_expressed():
    """The schema refuses it: an undetectable world is not a research finding."""
    with pytest.raises(ValueError, match="observable_indicators"):
        CounterfactualOutput.model_validate_json(
            _counterfactuals(_world("Permitting holds", indicators=[]))
        )


def test_the_output_has_no_field_in_which_to_conclude_the_thesis_is_safe():
    """Like the Critic, the agent has exactly one permitted move."""
    fields = set(CounterfactualOutput.model_fields)

    assert "robustness" not in fields
    assert "survives" not in fields
    assert "assessment" not in fields


async def test_the_agent_names_its_most_dangerous_world():
    service = LLMService(
        ScriptedProvider(
            [
                _counterfactuals(
                    _world("Permitting timelines hold", plausibility=7.0, severity=8.0),
                    _world("Chinese export policy relaxes", plausibility=4.0),
                    most_dangerous=0,
                )
            ]
        ),
        observers=[],
    )

    result = await CounterfactualAgent(service).run(_cf_input())

    assert result.evaluation.passed
    assert result.output.most_dangerous_index == 0


# --------------------------------------------------------------------------- #
# #65 — only what needs judgement is judged
# --------------------------------------------------------------------------- #


def test_the_axes_the_system_measures_are_not_offered_to_the_model():
    """Asking a model to re-judge a computed number invites disagreement with
    nothing to settle it."""
    assert Axis.STATE_CONFIDENCE in COMPUTED_AXES
    assert Axis.COUNTERFACTUAL_ROBUSTNESS in COMPUTED_AXES
    assert Axis.HISTORICAL_PRECEDENT in UNAVAILABLE_AXES

    for axis in JUDGED_AXES:
        assert axis not in COMPUTED_AXES
        assert axis not in UNAVAILABLE_AXES
    # Every axis is accounted for exactly once.
    assert set(JUDGED_AXES) | COMPUTED_AXES | UNAVAILABLE_AXES == set(Axis)


def _axis(
    dimension: Axis, *, why: str = "Evidence is thin on permitting.", facts=("A filing",)
) -> dict:
    return {
        "dimension": dimension.value,
        "value": 7.0,
        "why_not_higher": why,
        "facts": list(facts),
        "inferences": [],
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _scoring(*axes: dict) -> str:
    return json.dumps(
        {
            "axes": list(axes),
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _scoring_input() -> ThesisScoringInput:
    return ThesisScoringInput(
        as_of=NOW, process=SUMMARY, thesis_statement="Capacity is state-underwritten."
    )


def test_rescoring_a_computed_axis_is_rejected():
    """Two producers on one dimension is how a scorecard starts disagreeing
    with itself."""
    output = ThesisScoringOutput.model_validate_json(
        _scoring(*[_axis(a) for a in JUDGED_AXES], _axis(Axis.STATE_CONFIDENCE))
    )

    checks = {c.name: c for c in AxisCoverageEvaluator().evaluate(_scoring_input(), output)}

    assert checks["no_computed_axis_rescored"].passed is False


def test_a_missing_axis_is_rejected():
    output = ThesisScoringOutput.model_validate_json(
        _scoring(*[_axis(a) for a in JUDGED_AXES[:-1]])
    )

    checks = {c.name: c for c in AxisCoverageEvaluator().evaluate(_scoring_input(), output)}

    assert checks["all_judged_axes_scored"].passed is False


def test_a_token_ceiling_reason_is_rejected():
    """§11.1 requires 'why it is not higher' on every axis; a score with no
    stated ceiling reason is an assertion."""
    output = ThesisScoringOutput.model_validate_json(
        _scoring(*[_axis(a, why="Unclear.") for a in JUDGED_AXES])
    )

    checks = {c.name: c for c in ReasoningEvaluator().evaluate(_scoring_input(), output)}

    assert checks["ceiling_reasons_are_substantive"].passed is False


def test_an_axis_resting_only_on_inference_is_advisory_not_blocking():
    """A weak score, not an invalid one — and the reader can see it once the
    two lists are separate."""
    axes = [_axis(a) for a in JUDGED_AXES]
    axes[0]["facts"] = []
    axes[0]["inferences"] = ["The pattern resembles the 2010 cycle."]
    output = ThesisScoringOutput.model_validate_json(_scoring(*axes))

    checks = {c.name: c for c in ReasoningEvaluator().evaluate(_scoring_input(), output)}

    assert checks["axes_rest_on_facts"].passed is False
    assert checks["axes_rest_on_facts"].blocking is False


def test_the_output_cannot_carry_a_composite():
    """Ontology §42 and PRD §10: the dimensions are preserved, never blended."""
    assert "composite" not in ThesisScoringOutput.model_fields
    assert "overall" not in ThesisScoringOutput.model_fields


def test_an_axis_scored_twice_is_refused_by_the_schema():
    with pytest.raises(ValueError, match="scored more than once"):
        ThesisScoringOutput.model_validate_json(
            _scoring(_axis(JUDGED_AXES[0]), _axis(JUDGED_AXES[0]))
        )


async def test_the_scoring_agent_is_told_what_was_already_measured():
    service = LLMService(
        ScriptedProvider([_scoring(*[_axis(a) for a in JUDGED_AXES])]), observers=[]
    )
    agent = ThesisScoringAgent(service)
    payload = ThesisScoringInput(
        as_of=NOW,
        process=SUMMARY,
        thesis_statement="…",
        computed_axes={"state_confidence": 8.2, "counterfactual_robustness": 6.4},
    )

    content = agent.build_user_content(payload)

    assert "do not score these" in content.lower()
    assert "state_confidence: 8.2" in content
    # The judged axes are named explicitly rather than left to the prompt.
    assert "logical_coherence" in content


# --------------------------------------------------------------------------- #
# Deterministic measures
# --------------------------------------------------------------------------- #


def test_state_confidence_decays_with_age():
    """A confident estimate about July is not a confident statement about today."""
    fresh = thesis_measures.state_confidence(0.9, observed_at=NOW, now=NOW)
    stale = thesis_measures.state_confidence(0.9, observed_at=NOW - timedelta(days=540), now=NOW)

    assert fresh is not None and stale is not None
    assert fresh.value > stale.value
    assert stale.inputs["age_days"] == 540.0


def test_evidence_independence_penalises_collapsed_syndication():
    """Six documents from one source is a thesis resting on one report."""
    broad = thesis_measures.evidence_independence(independent_sources=5, documents=6)
    narrow = thesis_measures.evidence_independence(independent_sources=1, documents=6)

    assert broad is not None and narrow is not None
    assert broad.value > narrow.value
    assert narrow.inputs["collapse_ratio"] < 0.2


def test_accumulated_evidence_saturates():
    """The tenth supporting Event says much less than the second."""
    few = thesis_measures.accumulated_evidence(supporting=2, recent=2)
    many = thesis_measures.accumulated_evidence(supporting=8, recent=4)
    absurd = thesis_measures.accumulated_evidence(supporting=40, recent=4)

    assert few.value < many.value
    assert absurd.value == pytest.approx(many.value)


def test_an_untested_thesis_scores_nothing_for_robustness_rather_than_ten():
    """Untested is not robust. Returning a perfect score for an unexamined
    thesis would invert the axis exactly where it matters most."""
    assert thesis_measures.counterfactual_robustness([]) is None


def test_robustness_is_dominated_by_the_worst_alternative_world():
    """A thesis is as robust as its most dangerous unanswered alternative."""
    mild = thesis_measures.counterfactual_robustness([(3.0, 3.0, 1), (3.0, 3.0, 1)])
    one_severe = thesis_measures.counterfactual_robustness([(3.0, 3.0, 1), (9.0, 9.0, 1)])

    assert mild is not None and one_severe is not None
    assert one_severe.value < mild.value


def test_unobservable_counterfactuals_weaken_the_conclusion_either_way():
    """Worlds that can be watched for are worlds that can be ruled out."""
    observable = thesis_measures.counterfactual_robustness([(5.0, 5.0, 2)])
    blind = thesis_measures.counterfactual_robustness([(5.0, 5.0, 0)])

    assert observable is not None and blind is not None
    assert blind.value < observable.value


def test_contradiction_is_stored_as_burden_not_inverted():
    """Two numbers describing one thing in opposite directions is how a
    scorecard starts lying."""
    low = thesis_measures.contradiction(falsification_risk=2.0, contradicting_events=0)
    high = thesis_measures.contradiction(falsification_risk=8.0, contradicting_events=4)

    assert low is not None and high is not None
    assert high.value > low.value


def test_every_measure_carries_the_inputs_it_came_from():
    """A measured axis arriving as a bare float is no more inspectable than a
    judged one (issue #25)."""
    measures = [
        thesis_measures.state_confidence(0.8, observed_at=NOW, now=NOW),
        thesis_measures.accumulated_evidence(supporting=4, recent=2),
        thesis_measures.evidence_independence(independent_sources=3, documents=4),
        thesis_measures.contradiction(falsification_risk=5.0, contradicting_events=1),
        thesis_measures.counterfactual_robustness([(5.0, 5.0, 1)]),
    ]

    for measure in measures:
        assert measure is not None
        assert measure.inputs, f"{measure.axis} has no decomposition"
        assert measure.rationale
        assert 0.0 <= measure.value <= 10.0


# --------------------------------------------------------------------------- #
# The stage, against a real database
# --------------------------------------------------------------------------- #


@pytest.mark.integration
class TestThesisStage:
    @staticmethod
    async def _seed(session_factory) -> uuid.UUID:
        """A Process with evidence, a State and a critique already recorded."""
        from econiq_data_models import (
            Claim,
            Document,
            Event,
            EventClaim,
            EvidenceLink,
            Node,
            Process,
            ProcessState,
        )
        from econiq_ontology import (
            ClaimType,
            DocumentType,
            EntityType,
            EpistemicStatus,
            EventType,
            ExtractionStatus,
            ProcessStateLabel,
            ProcessStatus,
        )

        process_id = uuid.uuid4()
        async with session_factory() as session:
            session.add(Node(node_id=process_id, node_type=EntityType.PROCESS, slug="min"))
            await session.flush()
            session.add(
                Process(
                    process_id=process_id,
                    revision=1,
                    name=SUMMARY.name,
                    slug="min",
                    description=SUMMARY.description,
                    archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                    status=ProcessStatus.ACTIVE,
                )
            )
            await session.flush()
            session.add(
                ProcessState(
                    process_state_id=uuid.uuid4(),
                    process_id=process_id,
                    observed_at=datetime.now(UTC) - timedelta(days=10),
                    archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                    categorical_state=ProcessStateLabel.SUPPLY_TIGHTNESS,
                    state_confidence=0.82,
                    transition_beliefs={},
                    transition_indicators=[],
                    reversal_indicators=[],
                )
            )
            for index in range(3):
                doc_id, claim_id, event_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                for nid, kind in (
                    (doc_id, EntityType.DOCUMENT),
                    (claim_id, EntityType.CLAIM),
                    (event_id, EntityType.EVENT),
                ):
                    session.add(Node(node_id=nid, node_type=kind))
                await session.flush()
                session.add(
                    Document(
                        document_id=doc_id,
                        source=f"wire-{index}",
                        publisher=f"Publisher {index}",
                        title="…",
                        document_type=DocumentType.NEWS_ARTICLE,
                        publication_time=datetime.now(UTC) - timedelta(days=index + 1),
                        retrieved_at=datetime.now(UTC),
                        content_hash=uuid.uuid4().hex,
                        extraction_status=ExtractionStatus.PARSED,
                    )
                )
                session.add(
                    Event(
                        event_id=event_id,
                        revision=1,
                        event_type=EventType.GOVERNMENT_FUNDING,
                        title=f"Event {index}",
                        description="…",
                        occurred_at=datetime.now(UTC) - timedelta(days=index + 1),
                        entities=[],
                        independent_source_count=1,
                        novelty=7.0,
                        materiality=8.0,
                        confidence=0.9,
                        epistemic_status=EpistemicStatus.OBSERVED,
                        contradictions=[],
                    )
                )
                await session.flush()
                session.add(
                    Claim(
                        claim_id=claim_id,
                        document_id=doc_id,
                        text=f"Claim {index}",
                        claim_type=ClaimType.REPORTED_CLAIM,
                        source_location={"quote": "x", "char_start": 0, "char_end": 1},
                        extraction_confidence=0.9,
                        entities=[],
                    )
                )
                await session.flush()
                session.add(EventClaim(event_id=event_id, claim_id=claim_id))
                session.add(
                    EvidenceLink(
                        evidence_link_id=uuid.uuid4(),
                        subject_id=process_id,
                        evidence_id=event_id,
                        supports=True,
                    )
                )
            await session.commit()
        return process_id

    @staticmethod
    def _stage(session_factory, *responses: str):
        from econiq_agents import ThesisStage

        return ThesisStage(LLMService(ScriptedProvider(responses), observers=[]), session_factory)

    async def test_the_scorecard_carries_measured_and_judged_axes_together(self, session_factory):
        process_id = await self._seed(session_factory)
        stage = self._stage(
            session_factory,
            _counterfactuals(
                _world("Permitting timelines hold"),
                _world("Chinese export policy relaxes"),
            ),
            _scoring(*[_axis(a) for a in JUDGED_AXES]),
        )

        outcome = await stage.run(process_id)

        assert outcome.scorecard_id is not None
        assert len(outcome.counterfactual_ids) == 2
        # Four measured (no critic scorecard exists yet, so contradiction is
        # driven only by the zero contradicting Events) plus the judged axes.
        assert outcome.judged_axes == len(JUDGED_AXES)
        assert {m.axis for m in outcome.computed} >= {
            Axis.STATE_CONFIDENCE,
            Axis.ACCUMULATED_EVIDENCE,
            Axis.EVIDENCE_INDEPENDENCE,
            Axis.COUNTERFACTUAL_ROBUSTNESS,
        }

    async def test_no_composite_is_ever_written(self, session_factory):
        """Ontology §42, PRD §10: the dimensions are preserved, never blended."""
        from econiq_data_models import Scorecard
        from sqlalchemy import select

        process_id = await self._seed(session_factory)
        await self._stage(
            session_factory,
            _counterfactuals(_world("Permitting timelines hold")),
            _scoring(*[_axis(a) for a in JUDGED_AXES]),
        ).run(process_id)

        async with session_factory() as session:
            card = (await session.execute(select(Scorecard))).scalar_one()

        assert card.composite is None

    async def test_every_axis_records_why_it_is_not_higher(self, session_factory):
        """§11.1's requirement, stored rather than discarded after validation."""
        from econiq_data_models import ScoreDimension
        from sqlalchemy import select

        process_id = await self._seed(session_factory)
        await self._stage(
            session_factory,
            _counterfactuals(_world("Permitting timelines hold")),
            _scoring(*[_axis(a) for a in JUDGED_AXES]),
        ).run(process_id)

        async with session_factory() as session:
            rows = (await session.execute(select(ScoreDimension))).scalars().all()

        assert rows
        for row in rows:
            assert row.rationale, f"{row.dimension} has no reasoning"

    async def test_rejected_counterfactuals_never_reach_the_ontology(self, session_factory):
        """Straw men would inflate robustness precisely because they are easy
        to survive, so a failed evaluation writes nothing."""
        from econiq_data_models import Counterfactual
        from sqlalchemy import select

        process_id = await self._seed(session_factory)
        outcome = await self._stage(
            session_factory,
            # Both remove the same assumption: blocked by DiversityEvaluator.
            _counterfactuals(
                _world("Permitting timelines hold"),
                _world("Timelines for permitting hold"),
            ),
            _scoring(*[_axis(a) for a in JUDGED_AXES]),
        ).run(process_id)

        async with session_factory() as session:
            stored = (await session.execute(select(Counterfactual))).scalars().all()

        assert stored == []
        assert outcome.counterfactual_ids == []
        # The run is still recorded — a rejected run is provenance too.
        assert outcome.counterfactual_run_id is not None
        # And robustness is absent rather than perfect.
        assert all(m.axis is not Axis.COUNTERFACTUAL_ROBUSTNESS for m in outcome.computed)

    async def test_a_rerun_supersedes_rather_than_deletes(self, session_factory):
        """An alternative world the thesis outlived is part of its record (§32)."""
        from econiq_data_models import Counterfactual
        from sqlalchemy import select

        process_id = await self._seed(session_factory)
        for _ in range(2):
            await self._stage(
                session_factory,
                _counterfactuals(_world("Permitting timelines hold")),
                _scoring(*[_axis(a) for a in JUDGED_AXES]),
            ).run(process_id)

        async with session_factory() as session:
            rows = (await session.execute(select(Counterfactual))).scalars().all()

        assert len(rows) == 2
        assert sum(1 for row in rows if row.superseded_at is None) == 1
