"""State machines are the contract every Process agent writes against."""

import pytest
from econiq_ontology import (
    STATE_MACHINES,
    UNSPECIFIED_IN_SOURCE,
    ProcessArchetype,
    state_machine,
    validate_state,
)
from econiq_ontology import (
    ProcessStateLabel as S,
)


def test_every_archetype_has_a_state_machine():
    assert set(STATE_MACHINES) == set(ProcessArchetype)


@pytest.mark.parametrize("archetype", list(ProcessArchetype))
def test_sequences_are_reachable_and_unique(archetype):
    machine = STATE_MACHINES[archetype]
    assert len(set(machine.sequence)) == len(machine.sequence)
    reachable = {machine.initial_state}
    for state in machine.sequence:
        reachable |= machine.transitions.get(state, frozenset())
    assert reachable == set(machine.sequence)


def test_state_labels_do_not_leak_across_archetypes():
    # "supply_tightness" is a Commodity Supply Cycle state and a category error
    # for a Regulatory Implementation.
    validate_state(ProcessArchetype.COMMODITY_SUPPLY_CYCLE, S.SUPPLY_TIGHTNESS)
    with pytest.raises(ValueError, match="not a valid State"):
        validate_state(ProcessArchetype.REGULATORY_IMPLEMENTATION, S.SUPPLY_TIGHTNESS)


def test_s_curve_may_saturate_before_the_buildout_completes():
    machine = state_machine(ProcessArchetype.INFRASTRUCTURE_S_CURVE)
    assert machine.can_transition(S.ACCELERATION, S.INFRASTRUCTURE_EXPANSION)
    assert machine.can_transition(S.ACCELERATION, S.SATURATION)
    assert not machine.can_transition(S.DISCOVERY, S.MATURITY)


def test_commodity_cycle_closes():
    machine = state_machine(ProcessArchetype.COMMODITY_SUPPLY_CYCLE)
    assert machine.cyclical
    assert machine.can_transition(S.DOWNCYCLE, S.WEAK_DEMAND)
    assert machine.terminal_states == frozenset()


def test_adjacent_states_drive_level_two_analog_retrieval():
    machine = state_machine(ProcessArchetype.INFRASTRUCTURE_S_CURVE)
    assert machine.adjacent_states(S.ACCELERATION) == (
        S.EARLY_ADOPTION,
        S.INFRASTRUCTURE_EXPANSION,
    )
    # The endpoints have only one neighbour, and a linear machine does not wrap.
    assert machine.adjacent_states(S.DISCOVERY) == (S.EARLY_ADOPTION,)

    cyclical = state_machine(ProcessArchetype.COMMODITY_SUPPLY_CYCLE)
    assert S.WEAK_DEMAND in cyclical.adjacent_states(S.DOWNCYCLE)


def test_unspecified_archetypes_are_flagged_for_review():
    # These sequences are proposals, not spec — keep that visible.
    assert {
        ProcessArchetype.INDUSTRIAL_BOTTLENECK,
        ProcessArchetype.BUSINESS_MODEL_DISRUPTION,
    } == UNSPECIFIED_IN_SOURCE
