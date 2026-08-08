"""Cross-Event evidence dependence (issue #67, agent doc §10.2; ontology §47).

``independence.py`` answers a narrower question — how many independent reports
stand behind *one* Event — and answers it well, because syndicated copies of one
wire story share text and text overlap is cheap to measure.

Across Events that method stops working. Two outlets can report the same company
statement in entirely different words, three days apart, and the observation
behind both is still one observation. Nothing in the text says so. What says so
is that both articles cite the same filing, or that one says "as first reported
by", or that a reader who knows the story can see the second adds nothing.

So this module splits the problem the way agent doc §2.3 asks: **code finds what
is structurally visible, and the agent judges only what is left.**

Structurally visible, no model required:

* two Events resting on the same document — one primary source, definitionally;
* two Events whose Claims come from the same publisher — one newsroom.

Not visible, and genuinely a judgement:

* two independent outlets reporting one press release;
* a follow-up that restates rather than adds;
* an analyst note repeating a company forecast as though it were a finding.

The output of both is the same shape, tagged with which found it, so a reader
can tell a measured dependence from a judged one — and so the eval harness can
score the agent on the cases code could not settle rather than on the ones it
could.

**Why this matters for the score.** ``evidence_independence`` currently counts
sources per Event and sums them, which double-counts anything two Events share.
:func:`effective_sources` collapses the dependence graph into connected
components, so four Events all tracing to one filing count once. That is the
"improvement in evidence weighting" §10.2 asks to be measured.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from econiq_ontology import EvidenceDependenceKind as Kind


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One Event as the dependence analysis sees it."""

    event_id: uuid.UUID
    title: str
    document_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    publishers: frozenset[str] = field(default_factory=frozenset)
    claim_texts: tuple[str, ...] = ()
    independent_source_count: int = 1


@dataclass(frozen=True, slots=True)
class Dependence:
    """A directed dependence between two Events."""

    source_event_id: uuid.UUID
    dependent_event_id: uuid.UUID
    kind: Kind
    rationale: str
    confidence: float
    detected_by: str

    @property
    def pair(self) -> frozenset[uuid.UUID]:
        return frozenset({self.source_event_id, self.dependent_event_id})


def structural_dependencies(items: Sequence[EvidenceItem]) -> list[Dependence]:
    """Dependence that can be read off the rows, with no judgement involved.

    Direction is by position in the supplied order, which callers pass oldest
    first: the earlier Event is the source. For a shared document that is
    arbitrary but harmless — the pair collapses to one component either way —
    and for anything the agent later reclassifies as derivative it is the
    correct default.
    """
    found: list[Dependence] = []
    for i, earlier in enumerate(items):
        for later in items[i + 1 :]:
            shared_documents = earlier.document_ids & later.document_ids
            if shared_documents:
                found.append(
                    Dependence(
                        source_event_id=earlier.event_id,
                        dependent_event_id=later.event_id,
                        kind=Kind.SHARED_SOURCE,
                        rationale=(
                            f"Both rest on {len(shared_documents)} shared document(s); "
                            "one primary source cannot be two independent observations."
                        ),
                        confidence=1.0,
                        detected_by="computed",
                    )
                )
                # A shared document is the strongest finding available. Adding a
                # publisher edge for the same pair would double-count a single
                # relationship in the component graph's explanation.
                continue

            shared_publishers = earlier.publishers & later.publishers
            if shared_publishers:
                found.append(
                    Dependence(
                        source_event_id=earlier.event_id,
                        dependent_event_id=later.event_id,
                        kind=Kind.SHARED_SOURCE,
                        rationale=(
                            f"Both carried by {sorted(shared_publishers)}. One "
                            "newsroom reporting twice is one source."
                        ),
                        # Lower than a shared document: the same outlet can and
                        # does report genuinely separate observations.
                        confidence=0.6,
                        detected_by="computed",
                    )
                )
    return found


def undecided_pairs(
    items: Sequence[EvidenceItem], known: Iterable[Dependence]
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Pairs the structural pass could not settle — the agent's actual work.

    Sending every pair to the model would spend most of the budget re-deriving
    what a set intersection already established, and would let the model
    *disagree* with a shared document, which is not a matter of opinion.
    """
    settled = {dependence.pair for dependence in known}
    return [
        (earlier.event_id, later.event_id)
        for i, earlier in enumerate(items)
        for later in items[i + 1 :]
        if frozenset({earlier.event_id, later.event_id}) not in settled
    ]


def effective_sources(
    items: Sequence[EvidenceItem], dependencies: Iterable[Dependence]
) -> tuple[int, list[frozenset[uuid.UUID]]]:
    """Independent source count after collapsing the dependence graph.

    Connected components, not pairwise deduction. If A and B share a filing and
    B and C share a publisher, all three are one source — dependence is
    transitive in the way that matters here, because the question is how many
    *distinct observations* the thesis rests on.

    Returns the count and the groups, because a number without the grouping
    cannot be explained on a scorecard (#25).

    A component's contribution is the largest ``independent_source_count`` of
    its members rather than one. An Event already resolved from three
    independent reports is three sources; collapsing it to one because it shares
    a publisher with another Event would throw away work the Event layer did.
    """
    parent: dict[uuid.UUID, uuid.UUID] = {item.event_id: item.event_id for item in items}

    def find(node: uuid.UUID) -> uuid.UUID:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for dependence in dependencies:
        a, b = dependence.source_event_id, dependence.dependent_event_id
        if a not in parent or b not in parent:
            continue
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    groups: dict[uuid.UUID, set[uuid.UUID]] = {}
    for item in items:
        groups.setdefault(find(item.event_id), set()).add(item.event_id)

    by_event = {item.event_id: item for item in items}
    total = sum(
        max(by_event[event_id].independent_source_count for event_id in members)
        for members in groups.values()
    )
    return total, [frozenset(members) for members in groups.values()]
