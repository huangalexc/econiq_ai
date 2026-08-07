"""The critic must attack and must not rescue."""

from datetime import UTC, datetime

from econiq_agents import (
    MostDamagingEvaluator,
    NoRescueEvaluator,
    TestabilityEvaluator,
    coverage_of,
)
from econiq_ontology import CritiqueKind
from econiq_schemas import ProcessCriticInput, ProcessCriticOutput, ProcessSummary

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _payload() -> ProcessCriticInput:
    return ProcessCriticInput(
        as_of=NOW,
        process=ProcessSummary(
            process_id="p1", name="AI infrastructure expansion", description="…"
        ),
        thesis_statement="Compute demand is driving a durable power buildout.",
    )


def _critique(
    kind: CritiqueKind = CritiqueKind.UNSUPPORTED_ASSUMPTION,
    *,
    statement: str = "The thesis assumes interconnection queues clear by 2028.",
    rationale: str = "No supplied evidence speaks to queue times.",
    severity: float = 7.0,
    testable_with: str | None = "Published interconnection queue statistics.",
) -> dict:
    return {
        "kind": kind.value,
        "statement": statement,
        "severity": severity,
        "rationale": rationale,
        "testable_with": testable_with,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _output(*critiques: dict, risk: float = 6.0, index: int | None = 0) -> ProcessCriticOutput:
    return ProcessCriticOutput.model_validate(
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


def _checks(evaluator, output) -> dict[str, bool]:
    return {check.name: check.passed for check in evaluator.evaluate(_payload(), output)}


def test_a_plain_attack_passes():
    assert _checks(NoRescueEvaluator(), _output(_critique()))["no_rescue_language"]


def test_a_critique_that_argues_itself_down_is_caught():
    """'A real gap, however the thesis remains sound' is a critique plus a
    rebuttal, and the rebuttal is not this agent's to make."""
    rescued = _critique(
        rationale="No evidence speaks to queue times, however the thesis remains sound."
    )
    assert _checks(NoRescueEvaluator(), _output(rescued))["no_rescue_language"] is False


def test_balancing_language_is_caught():
    for phrase in (
        "On balance this is unlikely to matter.",
        "This is likely offset by continued capex growth.",
        "This concern is overstated.",
    ):
        output = _output(_critique(rationale=phrase))
        assert _checks(NoRescueEvaluator(), output)["no_rescue_language"] is False, phrase


def test_ordinary_adversarial_prose_is_not_mistaken_for_a_rescue():
    output = _output(
        _critique(
            rationale=(
                "The supplied evidence shows announced spending, however announced "
                "spending has historically overstated delivered capacity."
            )
        )
    )
    assert _checks(NoRescueEvaluator(), output)["no_rescue_language"]


def test_the_nominated_finding_must_be_the_most_severe():
    output = _output(
        _critique(severity=4.0),
        _critique(severity=9.0),
        index=0,
    )
    assert _checks(MostDamagingEvaluator(), output)["most_damaging_is_most_severe"] is False

    corrected = _output(_critique(severity=4.0), _critique(severity=9.0), index=1)
    assert _checks(MostDamagingEvaluator(), corrected)["most_damaging_is_most_severe"]


def test_a_falsifying_indicator_must_name_what_would_falsify_it():
    untestable = _critique(CritiqueKind.FALSIFYING_INDICATOR, testable_with=None)
    checks = _checks(TestabilityEvaluator(), _output(untestable))
    assert checks["falsifying_indicators_are_testable"] is False

    testable = _critique(CritiqueKind.FALSIFYING_INDICATOR)
    assert _checks(TestabilityEvaluator(), _output(testable))["falsifying_indicators_are_testable"]


def test_other_critique_kinds_may_be_untestable():
    """Testability is required of falsifying indicators, encouraged elsewhere."""
    output = _output(_critique(CritiqueKind.ALTERNATIVE_EXPLANATION, testable_with=None))
    assert _checks(TestabilityEvaluator(), output)["falsifying_indicators_are_testable"]


def test_coverage_reports_which_lines_of_attack_were_taken():
    output = _output(
        _critique(CritiqueKind.UNSUPPORTED_ASSUMPTION),
        _critique(CritiqueKind.SPURIOUS_CORRELATION),
    )
    coverage = coverage_of(output)

    assert coverage.attempted == {
        CritiqueKind.UNSUPPORTED_ASSUMPTION,
        CritiqueKind.SPURIOUS_CORRELATION,
    }
    assert CritiqueKind.HISTORICAL_COUNTEREXAMPLE in coverage.missing
    assert coverage.ratio == 2 / 7


def test_the_output_schema_offers_nowhere_to_defend_the_thesis():
    """Structure enforces what the prompt asks for."""
    fields = set(ProcessCriticOutput.model_fields)
    assert not fields & {"mitigations", "verdict", "counterpoints", "thesis_holds"}
