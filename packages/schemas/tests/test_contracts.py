"""Agent contracts — the boundaries that make each agent testable in isolation."""

from datetime import UTC, datetime

import pytest
from econiq_ontology import LogicOperator, ProcessArchetype
from econiq_ontology import ProcessStateLabel as S
from econiq_schemas import (
    AGENT_CONTRACTS,
    AgentInput,
    AgentOutput,
    BeliefChange,
    CapabilityMappingOutput,
    CapabilityRole,
    FeatureDelta,
    ProcessArchetypeOutput,
    ProcessStateOutput,
    ProcessUpdateOutput,
    ProposedCapability,
    ProposedGroup,
    ProposedLeaf,
    contract_for,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 6, tzinfo=UTC)


def test_every_contract_is_a_typed_pair():
    for name, contract in AGENT_CONTRACTS.items():
        assert issubclass(contract.input_schema, AgentInput), name
        assert issubclass(contract.output_schema, AgentOutput), name
        assert contract.ontology_layer


def test_unknown_agent_names_fail_loudly():
    with pytest.raises(KeyError, match="unknown agent"):
        contract_for("buy_the_dip")


def test_every_input_carries_a_point_in_time_cutoff():
    """Passing as-of explicitly is what makes historical replay honest."""
    for contract in AGENT_CONTRACTS.values():
        assert "as_of" in contract.input_schema.model_fields


def test_abstention_must_be_explained():
    with pytest.raises(ValidationError, match="must give a reason"):
        ProcessArchetypeOutput(
            abstained=True,
            primary_archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
            rejected=[{"archetype": "commodity_supply_cycle", "reason": "no commodity"}],
            reasons="…",
            confidence=0.2,
        )


def _update(**kw):
    defaults = dict(confidence_after=0.82)
    return ProcessUpdateOutput(**{**defaults, **kw})


def test_a_process_update_must_cite_supporting_claims():
    """Agent doc §6.2: every update must cite supporting Claims."""
    with pytest.raises(ValidationError, match="must cite supporting Claims"):
        _update(feature_deltas=[FeatureDelta(name="capex_acceleration", delta=0.08, rationale="…")])

    _update(
        supporting_claim_ids=["claim_1842"],
        belief_changes=[BeliefChange(statement="…", direction="strengthened", rationale="…")],
    )


def test_a_state_change_must_name_the_proposed_state():
    with pytest.raises(ValidationError, match="requires proposed_state"):
        _update(supporting_claim_ids=["c1"], state_change_recommended=True)
    with pytest.raises(ValidationError, match="without recommending"):
        _update(supporting_claim_ids=["c1"], proposed_state=S.INFRASTRUCTURE_EXPANSION)


def test_state_output_is_validated_against_the_archetype_machine():
    ProcessStateOutput(
        archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
        categorical_state=S.ACCELERATION,
        state_confidence=0.82,
        transition_beliefs={S.INFRASTRUCTURE_EXPANSION: 0.5},
    )
    with pytest.raises(ValidationError, match="cannot transition"):
        ProcessStateOutput(
            archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
            categorical_state=S.ACCELERATION,
            state_confidence=0.82,
            transition_beliefs={S.DISCOVERY: 0.5},
        )


def test_archetype_output_requires_rejected_alternatives():
    """Forcing the model to reject the others guards against picking whichever
    archetype yields the nicest narrative."""
    with pytest.raises(ValidationError):
        ProcessArchetypeOutput(
            primary_archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
            rejected=[],
            reasons="…",
            confidence=0.8,
        )
    with pytest.raises(ValidationError, match="appears in rejected"):
        ProcessArchetypeOutput(
            primary_archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
            rejected=[{"archetype": "infrastructure_s_curve", "reason": "…"}],
            reasons="…",
            confidence=0.8,
        )


def _capability(ref):
    return ProposedCapability(
        ref=ref, name=ref, description="…", role=CapabilityRole.NECESSARY, confidence=0.8
    )


def test_capability_mapping_tree_references_must_resolve():
    tree = ProposedGroup(
        operator=LogicOperator.AND,
        children=[ProposedLeaf(ref="domestic-production"), ProposedLeaf(ref="separation")],
    )
    CapabilityMappingOutput(
        capabilities=[_capability("domestic-production"), _capability("separation")],
        requirement_tree=tree,
    )
    with pytest.raises(ValidationError, match="unknown refs"):
        CapabilityMappingOutput(
            capabilities=[_capability("domestic-production")], requirement_tree=tree
        )
    with pytest.raises(ValidationError, match="missing from the requirement tree"):
        CapabilityMappingOutput(
            capabilities=[_capability("domestic-production"), _capability("separation")],
            requirement_tree=ProposedLeaf(ref="domestic-production"),
        )


def test_confluence_independence_is_counted_by_code_not_asserted():
    from econiq_schemas import CapabilityConfluenceOutput

    output = CapabilityConfluenceOutput(
        upstream=[
            {
                "process_id": "p1",
                "independence": "independent",
                "support_strength": 8.0,
                "rationale": "…",
            },
            {
                "process_id": "p2",
                "independence": "redundant",
                "support_strength": 4.0,
                "rationale": "…",
            },
        ]
    )
    assert output.independent_support_count == 1
