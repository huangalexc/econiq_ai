"""Graders and metrics — pure functions, no database."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from econiq_eval import (
    CapabilityOutcome,
    ExtractedClaim,
    ForecastBenchmarkUnavailableError,
    ProcessOutcome,
    calibration,
    compare_sets,
    grade_assets,
    grade_capabilities,
    grade_extraction,
    grade_processes,
    load_forecast_benchmark,
)
from econiq_eval.datasets import (
    AssetCase,
    CapabilityCase,
    ExtractionCase,
    LabelledClaim,
    LabelledExposure,
    LabelledRequirement,
    ProcessCase,
)
from econiq_ontology import (
    BottleneckKind,
    ExposureKind,
    LogicOperator,
    ProcessArchetype,
)
from econiq_ontology import (
    ProcessStateLabel as S,
)

AS_OF = datetime(2026, 3, 1, tzinfo=UTC)

DOCUMENT = (
    "Separation capacity outside China remains under 10 percent of global supply. "
    "The company said it expects the new plant to commission in 2027."
)


def _extraction_case(**overrides: object) -> ExtractionCase:
    defaults: dict[str, object] = {
        "case_id": "ext-1",
        "document_title": "Separation capacity",
        "document_text": DOCUMENT,
        "document_type": "news_article",
        "published_at": AS_OF,
        "expected_classification": "news_article",
        "claims": (
            LabelledClaim(
                text="Non-Chinese separation capacity is under 10 percent of supply.",
                claim_type="reported_claim",
                quote="under 10 percent of global supply",
            ),
            LabelledClaim(
                text="The new plant is expected to commission in 2027.",
                claim_type="forward_looking",
                quote="commission in 2027",
                attributed_to="the company",
            ),
        ),
    }
    return ExtractionCase.model_validate(defaults | overrides)


def test_a_labelled_quote_that_is_not_in_the_document_is_rejected_at_load():
    """A labelling error would otherwise be charged to the agent."""
    with pytest.raises(ValueError, match="absent from the document"):
        _extraction_case(
            claims=(
                LabelledClaim(
                    text="Fabricated.",
                    claim_type="reported_claim",
                    quote="a sentence nobody wrote",
                ),
            )
        )


def test_perfect_extraction_scores_perfectly():
    case = _extraction_case()
    produced = [
        ExtractedClaim(text=c.text, quote=c.quote, attributed_to=c.attributed_to)
        for c in case.claims
    ]

    result = grade_extraction([(case, produced)])

    scores = {g.name: g.score for g in result.grades}
    assert scores["extraction.precision"] == 1.0
    assert scores["extraction.recall"] == 1.0
    assert result.passed


def test_a_quote_no_document_contains_fails_however_small_the_dataset():
    """The hallucination check is an invariant, not a quality target.

    Every other grade here is advisory below the sample threshold. This one is
    not, because a fabricated citation is a defect at n=1.
    """
    case = _extraction_case()
    produced = [ExtractedClaim(text="Invented.", quote="a sentence nobody wrote")]

    result = grade_extraction([(case, produced)])

    hallucination = next(g for g in result.grades if g.name == "extraction.hallucination_rate")
    assert hallucination.blocking is True
    assert hallucination.passed is False
    assert result.passed is False


def test_quality_targets_are_advisory_until_the_dataset_is_large_enough():
    """A recall bar applied to one case would be a red build that means nothing."""
    case = _extraction_case()
    result = grade_extraction([(case, [])])  # recall 0.0

    recall = next(g for g in result.grades if g.name == "extraction.recall")
    assert recall.passed is False
    assert recall.blocking is False
    assert "advisory" in recall.detail
    # …and so the set still passes: the measurement is reported, not enforced.
    assert result.passed is True


def _process_case(**overrides: object) -> ProcessCase:
    defaults: dict[str, object] = {
        "case_id": "proc-1",
        "process_name": "Domestic strategic-mineral security",
        "as_of": AS_OF,
        "archetype": ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
        "event_titles": ("Pentagon takes a stake in a rare-earth producer",),
        "expected_state": S.SUPPLY_TIGHTNESS,
        "adjacent_states": (S.PRICE_ACCELERATION,),
    }
    return ProcessCase.model_validate(defaults | overrides)


def test_an_adjacent_state_is_a_near_miss_not_a_failure():
    case = _process_case()
    outcome = ProcessOutcome(
        archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE, state=S.PRICE_ACCELERATION
    )

    result = grade_processes([(case, outcome)])

    strict = next(g for g in result.grades if g.name == "process.state_accuracy")
    tolerant = next(g for g in result.grades if g.name == "process.state_tolerant_accuracy")
    assert strict.score == 0.0
    assert tolerant.score == 1.0


def test_a_state_from_the_wrong_machine_is_structural_and_blocking():
    """Issue #9 makes this unrepresentable; the grader proves it stayed that way."""
    case = _process_case()
    outcome = ProcessOutcome(
        archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
        state=S.DISCOVERY,  # an S-curve state, not a commodity-cycle one
    )

    result = grade_processes([(case, outcome)])

    check = next(g for g in result.grades if g.name == "process.state_on_archetype_machine")
    assert check.passed is False
    assert check.blocking is True
    assert result.passed is False


def test_state_calibration_is_reported_but_never_enforced():
    """Ontology §35: these are model beliefs until a calibration framework says otherwise."""
    result = grade_processes(
        [
            (
                _process_case(),
                ProcessOutcome(
                    archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                    state=S.PRICE_ACCELERATION,
                    state_confidence=0.95,
                ),
            )
        ]
    )

    check = next(g for g in result.grades if g.name == "process.state_calibration")
    assert check.blocking is False
    assert check.passed is True  # wrong answer at 0.95 confidence, still not a failure
    assert "§35" in check.detail


def test_capability_distractors_are_what_make_precision_meaningful():
    case = CapabilityCase(
        case_id="cap-1",
        process_name="Domestic strategic-mineral security",
        as_of=AS_OF,
        bottleneck_name="Heavy rare-earth separation capacity",
        bottleneck_kind=BottleneckKind.PROCESSING_CAPACITY,
        currently_binding=True,
        requirement=LabelledRequirement(
            operator=LogicOperator.AND,
            capabilities=("Solvent extraction separation", "Feedstock supply"),
        ),
        distractor_capabilities=("Electric vehicle assembly",),
    )
    outcome = CapabilityOutcome(
        bottleneck_kind="processing_capacity",
        operator=LogicOperator.AND,
        capabilities=("Solvent extraction separation", "Electric vehicle assembly"),
    )

    result = grade_capabilities([(case, outcome)])

    rejected = next(g for g in result.grades if g.name == "capability.distractors_rejected")
    assert rejected.passed is False
    assert "Electric vehicle assembly" in str(rejected.metrics["admitted"])


def test_thematic_distractors_are_the_comparison_the_prd_asks_the_system_to_win():
    case = AssetCase(
        case_id="asset-1",
        process_name="Domestic strategic-mineral security",
        as_of=AS_OF,
        capability_name="Heavy rare-earth separation",
        expected=(
            LabelledExposure(
                identifier="MP",
                exposure_kind=ExposureKind.PRODUCTION_CAPABILITY,
                directness="direct",
            ),
        ),
        distractors=("TSLA",),
    )

    result = grade_assets([(case, ["MP", "TSLA"])])

    check = next(g for g in result.grades if g.name == "asset.thematic_distractors")
    assert check.passed is False
    assert "naive thematic screen" in check.detail or "thematic distractor" in check.detail


def test_compare_sets_counts_both_directions():
    metrics = compare_sets(["a", "b", "c"], ["b", "c", "d"])
    assert (metrics.true_positives, metrics.false_positives, metrics.false_negatives) == (2, 1, 1)
    assert metrics.f1 == pytest.approx(2 / 3)


def test_calibration_puts_a_confident_wrong_answer_where_it_can_be_seen():
    measured = calibration([(0.9, False), (0.9, False), (0.1, False), (0.1, False)])

    assert measured.brier == pytest.approx((0.81 + 0.81 + 0.01 + 0.01) / 4)
    # The 0.9 bin claimed 90% and delivered 0%.
    top = next(b for b in measured.bins if b[0] >= 0.8)
    assert top[2] == 0.0
    assert measured.max_deviation == pytest.approx(0.9)


def test_the_forecast_benchmark_refuses_rather_than_scoring_nothing():
    """Agent doc §18.5 needs realised outcomes; Phase 0 has none."""
    with pytest.raises(ForecastBenchmarkUnavailableError, match="Phase 2"):
        load_forecast_benchmark()
