"""Process Archetypes and their State machines (ontology §8).

Different economic dynamics need different State models. A State label is only
meaningful relative to an Archetype: "supply_tightness" is a real State of a
Commodity Supply Cycle and a category error for a Regulatory Implementation.
This module is the single place that knows which is which.

Provenance of each sequence:

* ``INFRASTRUCTURE_S_CURVE`` — §8.1's States, ordered so that adoption
  accelerates before the infrastructure buildout it drives. §7's ``Euphoria``
  State is deliberately absent: speculative excess is an Asset-state property,
  not a State of the underlying Process.
* ``COMMODITY_SUPPLY_CYCLE`` — §8.2, verbatim, closed into a cycle because
  ``DOWNCYCLE`` returns to ``WEAK_DEMAND``.
* ``REGULATORY_IMPLEMENTATION`` — §8.4, plus an ``ANNOUNCED`` State preceding
  ``ENACTED``: §8.4 explicitly requires distinguishing announced from enacted
  policy, which the bare sequence does not express.
* ``INDUSTRIAL_BOTTLENECK`` and ``BUSINESS_MODEL_DISRUPTION`` — **not specified**
  in §8.3/§8.5, which give examples but no State sequence. The sequences below
  are proposals derived from the archetype descriptions and are flagged in
  ``UNSPECIFIED_IN_SOURCE``. They need senior review before Phase 0 agents
  depend on them (issue #9).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from econiq_ontology.enums import ProcessArchetype


class ProcessStateLabel(StrEnum):
    """Every categorical State across all Archetypes.

    A flat vocabulary keeps the database column typed; ``StateMachine`` enforces
    which labels are legal for which Archetype.
    """

    # Infrastructure / S-curve adoption (§8.1, §7)
    DISCOVERY = "discovery"
    EARLY_ADOPTION = "early_adoption"
    ACCELERATION = "acceleration"
    INFRASTRUCTURE_EXPANSION = "infrastructure_expansion"
    SATURATION = "saturation"
    MATURITY = "maturity"

    # Commodity supply cycle (§8.2)
    WEAK_DEMAND = "weak_demand"
    DEMAND_RECOVERY = "demand_recovery"
    INVENTORY_DRAW = "inventory_draw"
    SUPPLY_TIGHTNESS = "supply_tightness"
    PRICE_ACCELERATION = "price_acceleration"
    SUPPLY_RESPONSE = "supply_response"
    OVERSUPPLY = "oversupply"
    DOWNCYCLE = "downcycle"

    # Industrial bottleneck (§8.3 — proposed, see module docstring)
    CONSTRAINT_EMERGING = "constraint_emerging"
    CONSTRAINT_BINDING = "constraint_binding"
    RESPONSE_MOBILIZATION = "response_mobilization"
    BUILDOUT = "buildout"
    CAPACITY_DELIVERY = "capacity_delivery"
    CONSTRAINT_RELIEVED = "constraint_relieved"

    # Regulatory implementation (§8.4)
    ANNOUNCED = "announced"
    ENACTED = "enacted"
    RULEMAKING = "rulemaking"
    IMPLEMENTATION = "implementation"
    COMPLIANCE_BUILDOUT = "compliance_buildout"
    ENFORCEMENT = "enforcement"
    NORMALIZATION = "normalization"

    # Business model disruption (§8.5 — proposed, see module docstring)
    TRIGGER = "trigger"
    EXPERIMENTATION = "experimentation"
    BEHAVIOR_SHIFT = "behavior_shift"
    SUBSTITUTION = "substitution"
    INCUMBENT_RESPONSE = "incumbent_response"
    REALLOCATION = "reallocation"
    NEW_EQUILIBRIUM = "new_equilibrium"


S = ProcessStateLabel


@dataclass(frozen=True)
class StateMachine:
    """The State model of one Archetype.

    ``sequence`` is the canonical developmental ordering. It drives "adjacent
    State" analog retrieval (ontology §30 Level 2), so it must stay ordered by
    developmental stage even where ``transitions`` allows shortcuts.
    """

    archetype: ProcessArchetype
    sequence: tuple[ProcessStateLabel, ...]
    transitions: Mapping[ProcessStateLabel, frozenset[ProcessStateLabel]]
    cyclical: bool = False

    def __post_init__(self) -> None:
        unknown = set(self.transitions) - set(self.sequence)
        if unknown:
            raise ValueError(f"transitions reference states outside sequence: {unknown}")
        for origin, targets in self.transitions.items():
            stray = targets - set(self.sequence)
            if stray:
                raise ValueError(f"transitions from {origin} leave the sequence: {stray}")

    @property
    def states(self) -> frozenset[ProcessStateLabel]:
        return frozenset(self.sequence)

    @property
    def initial_state(self) -> ProcessStateLabel:
        return self.sequence[0]

    @property
    def terminal_states(self) -> frozenset[ProcessStateLabel]:
        """States with no outgoing transition. Empty for cyclical archetypes."""
        return frozenset(s for s in self.sequence if not self.transitions.get(s))

    def allows(self, state: ProcessStateLabel) -> bool:
        return state in self.states

    def ordinal(self, state: ProcessStateLabel) -> int:
        """Position in the developmental sequence."""
        self.require(state)
        return self.sequence.index(state)

    def can_transition(self, origin: ProcessStateLabel, target: ProcessStateLabel) -> bool:
        self.require(origin)
        self.require(target)
        return target in self.transitions.get(origin, frozenset())

    def adjacent_states(
        self, state: ProcessStateLabel, distance: int = 1
    ) -> tuple[ProcessStateLabel, ...]:
        """Neighbours in the developmental sequence, nearest first.

        Used by Level-2 analog retrieval ("same Archetype, adjacent State").
        For cyclical archetypes the sequence wraps.
        """
        if distance < 1:
            raise ValueError("distance must be >= 1")
        idx = self.ordinal(state)
        n = len(self.sequence)
        out: list[ProcessStateLabel] = []
        for step in range(1, distance + 1):
            for offset in (-step, step):
                pos = idx + offset
                if self.cyclical:
                    pos %= n
                elif not 0 <= pos < n:
                    continue
                candidate = self.sequence[pos]
                if candidate != state and candidate not in out:
                    out.append(candidate)
        return tuple(out)

    def require(self, state: ProcessStateLabel) -> None:
        if state not in self.states:
            raise ValueError(
                f"{state.value!r} is not a valid State for archetype {self.archetype.value!r}"
            )


def _linear(
    states: tuple[ProcessStateLabel, ...],
    extra: Mapping[ProcessStateLabel, tuple[ProcessStateLabel, ...]] | None = None,
) -> Mapping[ProcessStateLabel, frozenset[ProcessStateLabel]]:
    """Forward-only transitions along ``states``, plus any ``extra`` edges."""
    table: dict[ProcessStateLabel, set[ProcessStateLabel]] = {state: set() for state in states}
    for origin, target in pairwise(states):
        table[origin].add(target)
    for origin, targets in (extra or {}).items():
        table[origin].update(targets)
    return MappingProxyType({k: frozenset(v) for k, v in table.items()})


_S_CURVE = (
    S.DISCOVERY,
    S.EARLY_ADOPTION,
    S.ACCELERATION,
    S.INFRASTRUCTURE_EXPANSION,
    S.SATURATION,
    S.MATURITY,
)

_COMMODITY = (
    S.WEAK_DEMAND,
    S.DEMAND_RECOVERY,
    S.INVENTORY_DRAW,
    S.SUPPLY_TIGHTNESS,
    S.PRICE_ACCELERATION,
    S.SUPPLY_RESPONSE,
    S.OVERSUPPLY,
    S.DOWNCYCLE,
)

_BOTTLENECK = (
    S.CONSTRAINT_EMERGING,
    S.CONSTRAINT_BINDING,
    S.RESPONSE_MOBILIZATION,
    S.BUILDOUT,
    S.CAPACITY_DELIVERY,
    S.CONSTRAINT_RELIEVED,
)

_REGULATORY = (
    S.ANNOUNCED,
    S.ENACTED,
    S.RULEMAKING,
    S.IMPLEMENTATION,
    S.COMPLIANCE_BUILDOUT,
    S.ENFORCEMENT,
    S.NORMALIZATION,
)

_DISRUPTION = (
    S.TRIGGER,
    S.EXPERIMENTATION,
    S.BEHAVIOR_SHIFT,
    S.SUBSTITUTION,
    S.INCUMBENT_RESPONSE,
    S.REALLOCATION,
    S.NEW_EQUILIBRIUM,
)


STATE_MACHINES: Mapping[ProcessArchetype, StateMachine] = MappingProxyType(
    {
        ProcessArchetype.INFRASTRUCTURE_S_CURVE: StateMachine(
            archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
            sequence=_S_CURVE,
            # Demand can saturate before the buildout completes, so
            # acceleration may lead straight to saturation.
            transitions=_linear(_S_CURVE, extra={S.ACCELERATION: (S.SATURATION,)}),
        ),
        ProcessArchetype.COMMODITY_SUPPLY_CYCLE: StateMachine(
            archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
            sequence=_COMMODITY,
            # Cycles close: a downcycle returns to weak demand (§8.2).
            transitions=_linear(_COMMODITY, extra={S.DOWNCYCLE: (S.WEAK_DEMAND,)}),
            cyclical=True,
        ),
        ProcessArchetype.INDUSTRIAL_BOTTLENECK: StateMachine(
            archetype=ProcessArchetype.INDUSTRIAL_BOTTLENECK,
            sequence=_BOTTLENECK,
            # Buildout can fail to deliver and fall back to mobilization.
            transitions=_linear(
                _BOTTLENECK, extra={S.BUILDOUT: (S.CAPACITY_DELIVERY, S.RESPONSE_MOBILIZATION)}
            ),
        ),
        ProcessArchetype.REGULATORY_IMPLEMENTATION: StateMachine(
            archetype=ProcessArchetype.REGULATORY_IMPLEMENTATION,
            sequence=_REGULATORY,
            # Announced policy may never be enacted; rules may be remade.
            transitions=_linear(
                _REGULATORY, extra={S.IMPLEMENTATION: (S.COMPLIANCE_BUILDOUT, S.RULEMAKING)}
            ),
        ),
        ProcessArchetype.BUSINESS_MODEL_DISRUPTION: StateMachine(
            archetype=ProcessArchetype.BUSINESS_MODEL_DISRUPTION,
            sequence=_DISRUPTION,
            transitions=_linear(_DISRUPTION),
        ),
    }
)

#: Archetypes whose State sequence is a proposal rather than a specified one.
#: Kept explicit so downstream code and reviewers can see what is not yet
#: grounded in the source documents (see module docstring).
UNSPECIFIED_IN_SOURCE: frozenset[ProcessArchetype] = frozenset(
    {
        ProcessArchetype.INDUSTRIAL_BOTTLENECK,
        ProcessArchetype.BUSINESS_MODEL_DISRUPTION,
    }
)


def state_machine(archetype: ProcessArchetype) -> StateMachine:
    return STATE_MACHINES[archetype]


def states_for(archetype: ProcessArchetype) -> tuple[ProcessStateLabel, ...]:
    return STATE_MACHINES[archetype].sequence


def validate_state(archetype: ProcessArchetype, state: ProcessStateLabel) -> None:
    """Raise ``ValueError`` if ``state`` is not legal for ``archetype``."""
    STATE_MACHINES[archetype].require(state)
