"""State machines enforced at the boundary, not just documented."""

from datetime import UTC, datetime

from econiq_agents import (
    MeasuredFeatureEvaluator,
    StateTransitionEvaluator,
    classify_transition,
)
from econiq_ontology import ProcessArchetype, states_for
from econiq_ontology import ProcessStateLabel as S
from econiq_schemas import ProcessStateInput, ProcessStateOutput, ProcessSummary

NOW = datetime(2026, 7, 14, tzinfo=UTC)
S_CURVE = ProcessArchetype.INFRASTRUCTURE_S_CURVE


def _payload(prior=None, measured=None) -> ProcessStateInput:
    return ProcessStateInput(
        as_of=NOW,
        process=ProcessSummary(
            process_id="p1", name="AI infrastructure expansion", description="…"
        ),
        archetype=S_CURVE,
        permitted_states=list(states_for(S_CURVE)),
        measured_features=measured or {},
        prior_state=prior,
    )


def _output(state=S.ACCELERATION, features=()) -> ProcessStateOutput:
    return ProcessStateOutput.model_validate(
        {
            "archetype": S_CURVE.value,
            "categorical_state": state.value,
            "state_confidence": 0.8,
            "features": [
                {"name": name, "value": value, "rationale": "…", "schema_version": "1.0.0"}
                for name, value in features
            ],
            "transition_beliefs": {},
            "transition_indicators": [],
            "reversal_indicators": [],
            "supporting_claim_ids": [],
            "contradicting_claim_ids": [],
            "evidence": [],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _transition_checks(prior, proposed) -> dict[str, bool]:
    checks = StateTransitionEvaluator().evaluate(_payload(prior), _output(proposed))
    return {check.name: check.passed for check in checks}


def test_a_forward_step_is_allowed():
    assert _transition_checks(S.EARLY_ADOPTION, S.ACCELERATION)["transition_is_reachable"]


def test_staying_put_is_allowed_and_is_the_common_case():
    assert _transition_checks(S.ACCELERATION, S.ACCELERATION)["transition_is_reachable"]


def test_a_process_cannot_teleport_down_the_sequence():
    checks = _transition_checks(S.DISCOVERY, S.MATURITY)
    assert checks["transition_is_reachable"] is False


def test_the_first_estimate_has_no_prior_to_check_against():
    checks = StateTransitionEvaluator().evaluate(_payload(None), _output(S.MATURITY))
    assert [c.name for c in checks] == ["state_within_offered_vocabulary"]
    assert checks[0].passed


def test_a_measured_feature_may_be_interpreted_but_not_restated():
    """Code computes the numbers; the agent interprets them (ontology §2.4)."""
    measured = {"capex_acceleration": 8.7}
    faithful = MeasuredFeatureEvaluator().evaluate(
        _payload(measured=measured), _output(features=[("capex_acceleration", 8.7)])
    )
    assert faithful[0].passed

    contradicted = MeasuredFeatureEvaluator().evaluate(
        _payload(measured=measured), _output(features=[("capex_acceleration", 6.0)])
    )
    assert contradicted[0].passed is False
    assert "measured 8.70" in (contradicted[0].detail or "")


def test_estimated_features_are_not_checked_against_measurements():
    checks = MeasuredFeatureEvaluator().evaluate(
        _payload(measured={"capex_acceleration": 8.7}),
        _output(features=[("speculation", 4.1)]),
    )
    assert checks[0].passed


def test_transition_significance_flags_reversals_and_jumps():
    order = states_for(S_CURVE)
    assert classify_transition(order, S.EARLY_ADOPTION, S.ACCELERATION).major is False
    assert classify_transition(order, S.DISCOVERY, S.SATURATION).major is True
    reversal = classify_transition(order, S.SATURATION, S.ACCELERATION)
    assert reversal.backwards and reversal.major


def test_no_change_is_not_a_transition():
    order = states_for(S_CURVE)
    unchanged = classify_transition(order, S.ACCELERATION, S.ACCELERATION)
    assert unchanged.changed is False
    assert unchanged.major is False
