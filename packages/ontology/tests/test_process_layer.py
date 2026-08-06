"""The rules that stop a malformed Process object reaching the database."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_ontology import (
    CapabilityLeaf,
    CapabilityRequirement,
    LogicOperator,
    Necessity,
    Process,
    ProcessArchetype,
    ProcessState,
    ProcessStatus,
    RequirementGroup,
)
from econiq_ontology import (
    ProcessStateLabel as S,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 6, tzinfo=UTC)


def _state(**kw):
    defaults = dict(
        process_id=uuid.uuid4(),
        observed_at=NOW,
        recorded_at=NOW,
        archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
        categorical_state=S.ACCELERATION,
        state_confidence=0.8,
    )
    return ProcessState(**{**defaults, **kw})


def test_state_must_be_legal_for_its_archetype():
    with pytest.raises(ValidationError, match="not a valid State"):
        _state(categorical_state=S.SUPPLY_TIGHTNESS)


def test_transition_beliefs_must_be_reachable_transitions():
    _state(transition_beliefs={S.INFRASTRUCTURE_EXPANSION: 0.6, S.SATURATION: 0.4})
    with pytest.raises(ValidationError, match="cannot transition"):
        _state(transition_beliefs={S.DISCOVERY: 0.9})


def test_observation_cannot_be_recorded_before_it_was_observed():
    with pytest.raises(ValidationError, match="recorded_at"):
        _state(recorded_at=NOW - timedelta(days=1))


def test_merged_process_must_name_its_target():
    with pytest.raises(ValidationError, match="merged_into"):
        Process(
            name="AI infrastructure",
            slug="ai-infrastructure",
            description="…",
            status=ProcessStatus.MERGED,
        )


def _leaf(cap_id, necessity=Necessity.REQUIRED, weight=1.0):
    return CapabilityLeaf(capability_id=cap_id, necessity=necessity, weight=weight)


def test_and_requirements_are_not_satisfied_by_one_capability():
    """Ontology §12: domestic production AND processing is a different
    investment case from either alone."""
    production, processing = uuid.uuid4(), uuid.uuid4()
    req = CapabilityRequirement(
        bottleneck_id=uuid.uuid4(),
        root=RequirementGroup(
            operator=LogicOperator.AND,
            children=[_leaf(production), _leaf(processing)],
        ),
    )
    assert not req.is_satisfied_by(frozenset({production}))
    assert req.is_satisfied_by(frozenset({production, processing}))
    assert req.coverage(frozenset({production})) == pytest.approx(0.5)


def test_or_requirements_are_satisfied_by_either():
    a, b = uuid.uuid4(), uuid.uuid4()
    req = CapabilityRequirement(
        process_id=uuid.uuid4(),
        root=RequirementGroup(operator=LogicOperator.OR, children=[_leaf(a), _leaf(b)]),
    )
    assert req.is_satisfied_by(frozenset({b}))
    assert req.coverage(frozenset({b})) == pytest.approx(1.0)


def test_optional_capabilities_never_block_satisfaction():
    required, nice_to_have = uuid.uuid4(), uuid.uuid4()
    req = CapabilityRequirement(
        bottleneck_id=uuid.uuid4(),
        root=RequirementGroup(
            operator=LogicOperator.AND,
            children=[_leaf(required), _leaf(nice_to_have, Necessity.OPTIONAL)],
        ),
    )
    assert req.is_satisfied_by(frozenset({required}))
    assert set(req.capability_ids()) == {required, nice_to_have}


def test_weighted_coverage_reflects_importance():
    heavy, light = uuid.uuid4(), uuid.uuid4()
    req = CapabilityRequirement(
        bottleneck_id=uuid.uuid4(),
        root=RequirementGroup(
            operator=LogicOperator.AND,
            children=[_leaf(heavy, weight=0.75), _leaf(light, weight=0.25)],
        ),
    )
    assert req.coverage(frozenset({heavy})) == pytest.approx(0.75)
    assert req.coverage(frozenset({light})) == pytest.approx(0.25)


def test_requirement_must_anchor_to_a_bottleneck_or_process():
    with pytest.raises(ValidationError, match="anchor"):
        CapabilityRequirement(root=_leaf(uuid.uuid4()))
