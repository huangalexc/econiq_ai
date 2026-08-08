"""Archetype State machines (issues #22, #23).

The Process screen draws the machine a Process moves through (ui_concept §6.2),
and the Emergence Radar positions a Process by how far along that machine it is
(§5.2). Both need the ordering, and neither should own a copy of it.

Served from ``econiq_ontology.archetypes`` rather than duplicated in the client.
The sequence is not decoration — it defines which States are adjacent, which is
what makes "one step early" a near miss rather than a wrong answer, and a
frontend copy would drift the first time an archetype gained a State. It did:
the S-curve sequence changed once already during Phase 0, and every consumer
that had inlined it broke loudly rather than silently because they read it from
here.

Static reference data. It takes no ``as_of`` — the machines are part of the
ontology, not part of the graph, so there is no past version of them to
reconstruct.
"""

from __future__ import annotations

from econiq_ontology import ProcessArchetype, state_machine
from fastapi import APIRouter

from econiq_api.schemas import ArchetypeMachineOut, StateNodeOut

router = APIRouter(prefix="/api/archetypes", tags=["archetypes"])


@router.get("", response_model=list[ArchetypeMachineOut])
async def list_machines() -> list[ArchetypeMachineOut]:
    return [_machine(archetype) for archetype in ProcessArchetype]


@router.get("/{archetype}", response_model=ArchetypeMachineOut)
async def get_machine(archetype: ProcessArchetype) -> ArchetypeMachineOut:
    return _machine(archetype)


def _machine(archetype: ProcessArchetype) -> ArchetypeMachineOut:
    machine = state_machine(archetype)
    terminal = machine.terminal_states
    return ArchetypeMachineOut(
        archetype=archetype,
        cyclical=machine.cyclical,
        states=[
            StateNodeOut(
                state=state,
                ordinal=index,
                # Maturity is the position on the machine, normalised. A
                # single-state machine would divide by zero, and a Process on
                # it is fully mature by definition.
                maturity=index / (len(machine.sequence) - 1) if len(machine.sequence) > 1 else 1.0,
                transitions_to=sorted(
                    target.value for target in machine.transitions.get(state, frozenset())
                ),
                is_terminal=state in terminal,
            )
            for index, state in enumerate(machine.sequence)
        ],
    )
