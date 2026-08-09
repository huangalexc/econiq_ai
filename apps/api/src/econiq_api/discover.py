"""Ranking for the Discover feed (issue #20, ui_concept §5.1).

The home screen answers "what is changing in the economic state space?", which
means ranking Processes by how much their evidence has moved rather than by size
or by return. §5.1 lists eight inputs. Four of them exist in Phase 0, one has an
honest proxy, and three do not exist at all — and this module is explicit about
which is which, because a ranking that silently drops half its inputs is a
different ranking wearing the same name.

===========================  ==========================================
§5.1 input                   Status here
===========================  ==========================================
State confidence             computed — latest ProcessState
Evidence acceleration        computed — recent window against the prior one
Recent State change          computed — days since the label last moved
Affected Capability count    computed — graph traversal
Asset breadth                computed — graph traversal
Novelty                      computed — mean novelty of supporting Events
Market attention             **proxied** as source breadth, see below
Historical analogue strength **absent** — Phase 2 (#35-#46)
===========================  ==========================================

**On "market attention".** There is no market data in Phase 0 — no price, no
volume, no options interest. What exists is how many distinct publishers wrote
about the Events behind a Process, which is *media* coverage. That is a
defensible proxy and it is the one used, but it is named ``source_breadth``
rather than ``attention`` throughout. Calling it market attention would make the
central discovery claim of §5.2 — evidence accelerating *before attention
catches up* — untestable, because media coverage and market attention diverge
exactly in the cases the screen exists to find.

**This is a discovery ranking, not a prediction** (§5.2 is explicit). It is
computed on read and never stored, which also keeps it out of the score families
in ontology §17: it is not Thesis quality, and a persisted "discovery score"
would eventually be compared against one.

Every component is returned with its raw value, its normalised value and its
weight, so the rank can be taken apart on screen (the [Explain] primitive, #25).
A rank nobody can decompose is a number the user has to trust.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from econiq_data_models import (
    Asset,
    AssetExposure,
    Capability,
    Claim,
    Document,
    Event,
    EventClaim,
    EvidenceLink,
    Process,
    ProcessState,
    Relationship,
)
from econiq_ontology import EntityType, RelationshipType
from sqlalchemy import Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from econiq_api.temporal import current_revision, recorded_by

#: The window evidence acceleration is measured over, and the window it is
#: compared against. Thirty days is long enough that a quiet fortnight is not
#: read as a collapse, and short enough that a Process which stopped moving six
#: weeks ago does not still look hot.
WINDOW = timedelta(days=30)

#: Weights for the composite rank. Chosen by this repository, not by the PRD,
#: and deliberately flat-ish: the components are on different footings (one is a
#: proxy, one is a raw count) and a finely-tuned weighting would imply the
#: relative importances had been validated. They have not been. The decomposition
#: is returned so the reader can disagree with them.
WEIGHTS: dict[str, float] = {
    "evidence_acceleration": 0.30,
    "state_confidence": 0.20,
    "state_recency": 0.15,
    "asset_breadth": 0.15,
    "capability_count": 0.10,
    "novelty": 0.10,
}

#: Named, not silently absent. A caller can render "not available yet" instead
#: of a ranking that looks complete.
UNAVAILABLE_INPUTS: tuple[tuple[str, str], ...] = (
    (
        "market_attention",
        "No market data in Phase 0. Proxied by source_breadth (distinct "
        "publishers), which is media coverage and is reported alongside the "
        "rank rather than inside it.",
    ),
    (
        "historical_analogue_strength",
        "Needs the historical retrieval engine (Phase 2, #35-#46).",
    ),
)


@dataclass(frozen=True, slots=True)
class Component:
    name: str
    raw: float
    normalised: float
    weight: float

    @property
    def contribution(self) -> float:
        return self.normalised * self.weight


@dataclass(frozen=True, slots=True)
class RankedProcess:
    process_id: uuid.UUID
    score: float
    components: tuple[Component, ...]
    #: Reported beside the rank, never inside it — see the module docstring.
    source_breadth: int
    contradiction_count: int
    evidence_recent: int
    evidence_prior: int
    capability_count: int
    asset_count: int
    bottleneck_names: tuple[str, ...] = field(default=())


@dataclass(slots=True)
class _Facts:
    """Raw per-Process measurements, before normalisation."""

    evidence_recent: int = 0
    evidence_prior: int = 0
    contradictions: int = 0
    state_confidence: float = 0.0
    state_observed_at: datetime | None = None
    capability_count: int = 0
    asset_count: int = 0
    source_breadth: int = 0
    novelty: float = 0.0
    bottleneck_names: tuple[str, ...] = ()


async def rank_processes(
    session: AsyncSession,
    *,
    as_of: datetime | None,
    now: datetime,
    process_ids: Sequence[uuid.UUID] | None = None,
) -> list[RankedProcess]:
    """Rank the current Processes. Empty input gives an empty ranking."""
    ids = (
        list(process_ids) if process_ids is not None else await _current_process_ids(session, as_of)
    )
    if not ids:
        return []

    facts = {pid: _Facts() for pid in ids}
    cut = as_of or now

    await _evidence_windows(session, facts, cut=cut)
    await _states(session, facts, as_of=as_of)
    await _graph_counts(session, facts, as_of=as_of)
    await _source_breadth_and_novelty(session, facts, as_of=as_of)
    await _bottlenecks(session, facts, as_of=as_of)

    ranked = [_score(pid, fact, cut=cut) for pid, fact in facts.items()]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


async def _current_process_ids(session: AsyncSession, as_of: datetime | None) -> list[uuid.UUID]:
    query: Select[tuple[uuid.UUID]] = select(Process.process_id)
    rows = await session.execute(current_revision(query, Process, as_of))
    return list(rows.scalars().all())


async def _evidence_windows(
    session: AsyncSession, facts: dict[uuid.UUID, _Facts], *, cut: datetime
) -> None:
    """Evidence in the last window against the window before it.

    Counted from ``created_at`` — when the system learned it — rather than from
    the Event's ``occurred_at``. A backfill of ten-year-old filings is not a
    Process accelerating, and dating the count by the event would say it was.
    """
    boundary = cut - WINDOW
    previous = cut - 2 * WINDOW

    rows = await session.execute(
        select(
            EvidenceLink.subject_id,
            func.count()
            .filter(EvidenceLink.created_at > boundary, EvidenceLink.created_at <= cut)
            .label("recent"),
            func.count()
            .filter(EvidenceLink.created_at > previous, EvidenceLink.created_at <= boundary)
            .label("prior"),
            func.count().filter(EvidenceLink.supports.is_(False)).label("against"),
        )
        .where(
            EvidenceLink.subject_id.in_(facts),
            EvidenceLink.retracted_at.is_(None),
            EvidenceLink.created_at <= cut,
        )
        .group_by(EvidenceLink.subject_id)
    )
    for subject_id, recent, prior, against in rows.all():
        fact = facts[subject_id]
        fact.evidence_recent = recent
        fact.evidence_prior = prior
        fact.contradictions = against


async def _states(
    session: AsyncSession, facts: dict[uuid.UUID, _Facts], *, as_of: datetime | None
) -> None:
    query: Select[tuple[ProcessState]] = select(ProcessState).where(
        ProcessState.process_id.in_(facts)
    )
    rows = (
        (
            await session.execute(
                recorded_by(query, ProcessState, as_of).order_by(
                    ProcessState.observed_at.desc(), ProcessState.recorded_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    seen: set[uuid.UUID] = set()
    for row in rows:
        if row.process_id in seen:
            continue
        seen.add(row.process_id)
        fact = facts[row.process_id]
        fact.state_confidence = row.state_confidence
        fact.state_observed_at = row.observed_at


async def _graph_counts(
    session: AsyncSession, facts: dict[uuid.UUID, _Facts], *, as_of: datetime | None
) -> None:
    """Capabilities and Assets downstream of each Process.

    Walked explicitly over the two hops rather than through the recursive
    traversal: the shape is fixed here (Process → Bottleneck → Capability →
    Asset) and a recursive CTE per Process would be one query each.
    """
    creates = _edges(RelationshipType.CREATES, as_of).subquery("creates")
    requires = _edges(RelationshipType.REQUIRES, as_of).subquery("requires")

    capability_rows = await session.execute(
        select(
            creates.c.source_id,
            func.count(distinct(requires.c.target_id)).label("capabilities"),
        )
        .join(requires, requires.c.source_id == creates.c.target_id)
        .where(creates.c.source_id.in_(facts))
        .group_by(creates.c.source_id)
    )
    for process_id, count in capability_rows.all():
        facts[process_id].capability_count = count

    # Assets are counted through exposures rather than through the
    # `expressed_by` edge, because an exposure is the row that says *how* the
    # Asset is exposed, and an edge without one is not yet an expression.
    asset_rows = await session.execute(
        select(
            creates.c.source_id,
            func.count(distinct(AssetExposure.asset_id)).label("assets"),
        )
        .join(requires, requires.c.source_id == creates.c.target_id)
        .join(
            AssetExposure,
            (AssetExposure.target_id == requires.c.target_id)
            & (AssetExposure.target_type == EntityType.CAPABILITY),
        )
        .where(creates.c.source_id.in_(facts))
        .group_by(creates.c.source_id)
    )
    for process_id, count in asset_rows.all():
        facts[process_id].asset_count = count


def _edges(kind: RelationshipType, as_of: datetime | None) -> Select[tuple[uuid.UUID, uuid.UUID]]:
    query: Select[tuple[uuid.UUID, uuid.UUID]] = select(
        Relationship.source_id, Relationship.target_id
    ).where(Relationship.relationship_type == kind)
    return current_revision(query, Relationship, as_of)


async def _source_breadth_and_novelty(
    session: AsyncSession, facts: dict[uuid.UUID, _Facts], *, as_of: datetime | None
) -> None:
    """Distinct publishers behind a Process's evidence, and mean Event novelty.

    Note that this deliberately *does not* collapse syndication, and so differs
    from the Event layer's ``independent_source_count``. The two measure
    different things and the difference is the point: one wire story carried by
    fifty outlets is a single piece of evidence (ontology §47) but a great deal
    of coverage. Evidence independence must collapse it or confidence inflates;
    a coverage proxy must not, or a story everybody ran looks obscure.

    Publishers rather than documents, though — one outlet publishing three
    updates on the same day is one voice getting louder, not three voices.
    """
    query = (
        select(
            EvidenceLink.subject_id,
            func.count(distinct(Document.publisher)).label("publishers"),
            func.avg(Event.novelty).label("novelty"),
        )
        .join(Event, Event.event_id == EvidenceLink.evidence_id)
        .join(EventClaim, EventClaim.event_id == Event.event_id)
        .join(Claim, Claim.claim_id == EventClaim.claim_id)
        .join(Document, Document.document_id == Claim.document_id)
        .where(
            EvidenceLink.subject_id.in_(facts),
            EvidenceLink.retracted_at.is_(None),
            EvidenceLink.supports.is_(True),
        )
        .group_by(EvidenceLink.subject_id)
    )
    if as_of is not None:
        query = query.where(EvidenceLink.created_at <= as_of)

    for subject_id, publishers, novelty in (await session.execute(query)).all():
        fact = facts[subject_id]
        fact.source_breadth = publishers or 0
        fact.novelty = float(novelty or 0.0)


async def _bottlenecks(
    session: AsyncSession, facts: dict[uuid.UUID, _Facts], *, as_of: datetime | None
) -> None:
    """Binding Bottleneck names, for the hot cards (§5.3)."""
    from econiq_data_models import Bottleneck

    query: Select[tuple[uuid.UUID, str]] = select(Bottleneck.process_id, Bottleneck.name).where(
        Bottleneck.process_id.in_(facts),
        Bottleneck.resolved.is_(False),
        Bottleneck.currently_binding.is_(True),
    )
    grouped: dict[uuid.UUID, list[str]] = {}
    for process_id, name in (
        await session.execute(current_revision(query, Bottleneck, as_of))
    ).all():
        grouped.setdefault(process_id, []).append(name)
    for process_id, names in grouped.items():
        facts[process_id].bottleneck_names = tuple(sorted(names))


def _score(process_id: uuid.UUID, fact: _Facts, *, cut: datetime) -> RankedProcess:
    acceleration = _acceleration(fact.evidence_recent, fact.evidence_prior)
    components = (
        Component(
            "evidence_acceleration",
            raw=fact.evidence_recent - fact.evidence_prior,
            normalised=acceleration,
            weight=WEIGHTS["evidence_acceleration"],
        ),
        Component(
            "state_confidence",
            raw=fact.state_confidence,
            normalised=fact.state_confidence,
            weight=WEIGHTS["state_confidence"],
        ),
        Component(
            "state_recency",
            raw=_days_since(fact.state_observed_at, cut),
            normalised=_recency(fact.state_observed_at, cut),
            weight=WEIGHTS["state_recency"],
        ),
        Component(
            "asset_breadth",
            raw=fact.asset_count,
            normalised=_saturating(fact.asset_count, at=10),
            weight=WEIGHTS["asset_breadth"],
        ),
        Component(
            "capability_count",
            raw=fact.capability_count,
            normalised=_saturating(fact.capability_count, at=6),
            weight=WEIGHTS["capability_count"],
        ),
        Component(
            "novelty",
            raw=fact.novelty,
            # Event novelty is a 0-10 judgement.
            normalised=min(fact.novelty / 10.0, 1.0),
            weight=WEIGHTS["novelty"],
        ),
    )
    return RankedProcess(
        process_id=process_id,
        score=round(sum(c.contribution for c in components), 4),
        components=components,
        source_breadth=fact.source_breadth,
        contradiction_count=fact.contradictions,
        evidence_recent=fact.evidence_recent,
        evidence_prior=fact.evidence_prior,
        capability_count=fact.capability_count,
        asset_count=fact.asset_count,
        bottleneck_names=fact.bottleneck_names,
    )


def _acceleration(recent: int, prior: int) -> float:
    """Recent evidence against the previous window, mapped to 0-1.

    A Process with no prior evidence and some now is new rather than
    accelerating infinitely, so the ratio is bounded. Deceleration is
    representable — it lands below 0.5 — because a thesis losing evidence is
    information the Discover screen should be able to show.
    """
    if recent == 0 and prior == 0:
        return 0.0
    if prior == 0:
        return min(0.5 + recent / 20.0, 1.0)
    ratio = recent / prior
    return min(ratio / 2.0, 1.0)


def _days_since(moment: datetime | None, cut: datetime) -> float:
    if moment is None:
        return float("inf")
    return max((cut - moment).total_seconds() / 86400.0, 0.0)


def _recency(moment: datetime | None, cut: datetime) -> float:
    """A State that moved this week outranks one that has not moved in a year."""
    days = _days_since(moment, cut)
    if days == float("inf"):
        return 0.0
    return max(0.0, 1.0 - days / 180.0)


def _saturating(count: int, *, at: int) -> float:
    """Counts saturate: the tenth Asset says much less than the second."""
    return min(count / at, 1.0) if at else 0.0


async def asset_names(
    session: AsyncSession, asset_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not asset_ids:
        return {}
    rows = await session.execute(
        select(Asset.asset_id, Asset.name).where(
            Asset.asset_id.in_(asset_ids), Asset.valid_to.is_(None)
        )
    )
    return {asset_id: name for asset_id, name in rows.all()}


async def capability_names(
    session: AsyncSession, capability_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not capability_ids:
        return {}
    rows = await session.execute(
        select(Capability.capability_id, Capability.name).where(
            Capability.capability_id.in_(capability_ids), Capability.valid_to.is_(None)
        )
    )
    return {capability_id: name for capability_id, name in rows.all()}
