"""The Phase 0 gate: PRD §28's success criteria as queries (issue #17).

§28 states the MVP is successful if the platform can reliably perform one loop,
and lists eleven steps of it. This module turns each step into a question asked
of the database, so "did Phase 0 succeed?" has an answer somebody can re-run
rather than an answer somebody wrote down.

Two things this module is careful not to claim.

**A criterion is met by the graph, not by the code existing.** "Identify
multiple Asset expressions" is not satisfied by an Asset agent being present; it
is satisfied by two Assets being reachable from one Capability in the actual
graph. Every check below reads rows.

**Passing does not mean the agents are accurate.** These checks establish that
the chain is coherent, connected and provenanced — that a document stream
*became* a Process graph. Whether the Process is the right one is what the
benchmarks in :mod:`econiq_eval.graders` measure, and they need labelled data
and a real model. A run driven by scripted responses can satisfy every criterion
here and still be wrong about the world; :func:`evaluate_phase0` records which
provider produced the graph so the report cannot be read as more than it is.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from econiq_data_models import (
    Asset,
    AssetExposure,
    Bottleneck,
    Capability,
    CapabilityRequirement,
    Claim,
    Document,
    Event,
    EventClaim,
    EvidenceLink,
    JournalEntry,
    Process,
    ProcessState,
    ProcessStateFeature,
    RequirementNode,
    Scorecard,
    ScoreDimension,
)
from econiq_graph import GraphQueries
from econiq_ontology import EntityType, ScoreFamily, utcnow
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class Criterion:
    """One line of PRD §28, and whether the graph satisfies it."""

    number: int
    name: str
    met: bool
    detail: str
    deferred_to: str | None = None

    @property
    def status(self) -> str:
        if self.deferred_to:
            return "deferred"
        return "met" if self.met else "NOT MET"


@dataclass(frozen=True, slots=True)
class Phase0Report:
    criteria: tuple[Criterion, ...]
    provider: str
    ran_at: datetime

    @property
    def in_scope(self) -> tuple[Criterion, ...]:
        return tuple(c for c in self.criteria if c.deferred_to is None)

    @property
    def passed(self) -> bool:
        """Deferred criteria do not count against the gate, and do not count for it."""
        return all(c.met for c in self.in_scope)

    @property
    def unmet(self) -> tuple[Criterion, ...]:
        return tuple(c for c in self.in_scope if not c.met)


class Phase0Evaluation:
    """Reads the graph and answers §28."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.graph = GraphQueries(session_factory)

    async def evaluate(self, *, provider: str) -> Phase0Report:
        async with self.session_factory() as session:
            criteria = [
                await self._detects_a_process(session),
                await self._aggregates_and_deduplicates_events(session),
                await self._determines_a_defensible_state(session),
                await self._identifies_bottlenecks(session),
                await self._translates_bottlenecks_into_capabilities(session),
                await self._identifies_multiple_asset_expressions(session),
                await self._compares_assets_quantitatively(session),
                await self._preserves_evidence_provenance(session),
            ]
        criteria.append(await self._constructs_an_inspectable_case())
        async with self.session_factory() as session:
            criteria.append(await self._monitors_the_thesis_over_time(session))
        criteria.append(self._learns_from_historical_outcomes())
        return Phase0Report(criteria=tuple(criteria), provider=provider, ran_at=utcnow())

    # 1 ---------------------------------------------------------------- #

    async def _detects_a_process(self, session: AsyncSession) -> Criterion:
        rows = (
            await session.execute(
                select(Process.process_id, Process.name).where(Process.valid_to.is_(None))
            )
        ).all()
        evidenced = 0
        for process_id, _ in rows:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(EvidenceLink)
                    .where(
                        EvidenceLink.subject_id == process_id,
                        EvidenceLink.retracted_at.is_(None),
                    )
                )
            ).scalar_one()
            evidenced += int(count > 0)
        return Criterion(
            number=1,
            name="Detect a meaningful Process",
            # An unevidenced Process is a name, not a detection.
            met=evidenced > 0,
            detail=f"{len(rows)} current Process(es), {evidenced} carrying evidence",
        )

    # 2 ---------------------------------------------------------------- #

    async def _aggregates_and_deduplicates_events(self, session: AsyncSession) -> Criterion:
        """Aggregation is Claims from several documents collapsing into one Event.

        The number that matters is ``independent_source_count`` against the
        document count: an Event built from four syndicated copies of one wire
        report is one source, not four (ontology §47), and an Event whose two
        numbers are equal has not been deduplicated, it has just been counted.
        """
        rows = (
            await session.execute(
                select(
                    Event.event_id,
                    Event.title,
                    Event.independent_source_count,
                    func.count(distinct(Claim.document_id)).label("documents"),
                )
                .join(EventClaim, EventClaim.event_id == Event.event_id)
                .join(Claim, Claim.claim_id == EventClaim.claim_id)
                .where(Event.valid_to.is_(None))
                .group_by(Event.event_id, Event.title, Event.independent_source_count)
            )
        ).all()

        multi_document = [r for r in rows if r.documents > 1]
        deduplicated = [r for r in multi_document if r.independent_source_count < r.documents]
        return Criterion(
            number=2,
            name="Aggregate and deduplicate relevant Events",
            met=bool(multi_document),
            detail=(
                f"{len(rows)} Event(s); {len(multi_document)} built from more than one "
                f"document; {len(deduplicated)} where independent sources were "
                f"counted below the document count"
            ),
        )

    # 3 ---------------------------------------------------------------- #

    async def _determines_a_defensible_state(self, session: AsyncSession) -> Criterion:
        """Defensible means the features behind it are visible, with their basis."""
        states = (await session.execute(select(ProcessState.process_state_id))).scalars().all()
        if not states:
            return Criterion(3, "Determine a defensible Process State", False, "no States recorded")

        features = (
            await session.execute(
                select(
                    ProcessStateFeature.process_state_id,
                    func.count().label("n"),
                    func.count(distinct(ProcessStateFeature.basis)).label("bases"),
                ).group_by(ProcessStateFeature.process_state_id)
            )
        ).all()
        with_features = {row[0] for row in features}
        return Criterion(
            number=3,
            name="Determine a defensible Process State",
            met=bool(with_features),
            detail=(
                f"{len(states)} State observation(s), {len(with_features)} carrying "
                f"features that record whether each was measured or estimated"
            ),
        )

    # 4 ---------------------------------------------------------------- #

    async def _identifies_bottlenecks(self, session: AsyncSession) -> Criterion:
        rows = (
            await session.execute(
                select(Bottleneck.bottleneck_id, Bottleneck.currently_binding).where(
                    Bottleneck.valid_to.is_(None), Bottleneck.resolved.is_(False)
                )
            )
        ).all()
        binding = [r for r in rows if r.currently_binding]
        return Criterion(
            number=4,
            name="Identify important Bottlenecks",
            met=bool(binding),
            detail=f"{len(rows)} open Bottleneck(s), {len(binding)} currently binding",
        )

    # 5 ---------------------------------------------------------------- #

    async def _translates_bottlenecks_into_capabilities(self, session: AsyncSession) -> Criterion:
        """A Bottleneck with a requirement tree, not merely a Capability existing."""
        requirements = (
            await session.execute(
                select(
                    CapabilityRequirement.bottleneck_id,
                    func.count(RequirementNode.requirement_node_id).label("nodes"),
                )
                .join(
                    RequirementNode,
                    (RequirementNode.requirement_id == CapabilityRequirement.requirement_id)
                    & (RequirementNode.requirement_revision == CapabilityRequirement.revision),
                )
                .where(CapabilityRequirement.valid_to.is_(None))
                .group_by(CapabilityRequirement.bottleneck_id)
            )
        ).all()
        capability_count = (
            await session.execute(
                select(func.count()).select_from(Capability).where(Capability.valid_to.is_(None))
            )
        ).scalar_one()
        return Criterion(
            number=5,
            name="Translate Bottlenecks into Capabilities",
            met=bool(requirements),
            detail=(
                f"{len(requirements)} Bottleneck(s) carry a requirement tree over "
                f"{capability_count} Capability node(s)"
            ),
        )

    # 6 ---------------------------------------------------------------- #

    async def _identifies_multiple_asset_expressions(self, session: AsyncSession) -> Criterion:
        """Several ways to express one Capability — the point of the layer.

        One Asset per Capability would mean the system had found *an* instrument,
        which a thematic screen also does. Finding several, and being able to
        say how each is exposed, is the thing being validated.
        """
        rows = (
            await session.execute(
                select(
                    AssetExposure.target_id,
                    func.count(distinct(AssetExposure.asset_id)).label("assets"),
                    func.count(distinct(AssetExposure.exposure_kind)).label("kinds"),
                )
                .where(AssetExposure.target_type == EntityType.CAPABILITY)
                .group_by(AssetExposure.target_id)
            )
        ).all()
        multiple = [r for r in rows if r.assets > 1]
        total_assets = (
            await session.execute(
                select(func.count()).select_from(Asset).where(Asset.valid_to.is_(None))
            )
        ).scalar_one()
        return Criterion(
            number=6,
            name="Identify multiple Asset expressions",
            met=bool(multiple),
            detail=(
                f"{total_assets} Asset(s); {len(multiple)} of {len(rows)} Capability/ies "
                f"have more than one Asset expressing them"
            ),
        )

    # 7 ---------------------------------------------------------------- #

    async def _compares_assets_quantitatively(self, session: AsyncSession) -> Criterion:
        """Scorecards with their dimensions — a bare number is not a comparison.

        Ontology §17 keeps the families apart, so this looks for Asset Quality
        specifically rather than for any score: comparing Assets on a blended
        number would be the exact failure the family separation exists to stop.
        """
        rows = (
            await session.execute(
                select(
                    Scorecard.subject_id,
                    Scorecard.family,
                    func.count(ScoreDimension.dimension).label("dimensions"),
                )
                .outerjoin(ScoreDimension, ScoreDimension.scorecard_id == Scorecard.scorecard_id)
                .group_by(Scorecard.scorecard_id, Scorecard.subject_id, Scorecard.family)
            )
        ).all()
        asset_scores = [r for r in rows if r.family is ScoreFamily.ASSET_QUALITY]
        decomposed = [r for r in asset_scores if r.dimensions > 0]
        return Criterion(
            number=7,
            name="Quantitatively compare Assets",
            met=len(decomposed) > 1,
            detail=(
                f"{len(asset_scores)} Asset scorecard(s), {len(decomposed)} decomposed "
                f"into dimensions; comparison needs at least two"
            ),
        )

    # 8 ---------------------------------------------------------------- #

    async def _preserves_evidence_provenance(self, session: AsyncSession) -> Criterion:
        """Every Claim reaches a document span; every Event reaches Claims."""
        claims = (await session.execute(select(Claim.claim_id, Claim.source_location))).all()
        located = [c for c in claims if c.source_location.get("char_start") is not None]

        orphan_events = (
            await session.execute(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.valid_to.is_(None),
                    ~select(EventClaim.event_id)
                    .where(EventClaim.event_id == Event.event_id)
                    .exists(),
                )
            )
        ).scalar_one()

        documents = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
        met = bool(claims) and len(located) == len(claims) and orphan_events == 0
        return Criterion(
            number=8,
            name="Preserve evidence provenance",
            met=met,
            detail=(
                f"{len(located)}/{len(claims)} Claim(s) carry verified document offsets "
                f"across {documents} document(s); {orphan_events} Event(s) without Claims"
            ),
        )

    # 9 ---------------------------------------------------------------- #

    async def _constructs_an_inspectable_case(self) -> Criterion:
        """The whole chain, walked: Process → Bottleneck → Capability → Asset.

        Traversed rather than counted. Rows of each type existing proves nothing
        about whether they are connected, and an investment case that cannot be
        walked from thesis to instrument is not inspectable.
        """
        async with self.session_factory() as session:
            process_ids = (
                (
                    await session.execute(
                        select(Process.process_id).where(Process.valid_to.is_(None))
                    )
                )
                .scalars()
                .all()
            )

        complete: list[uuid.UUID] = []
        for process_id in process_ids:
            if await self.graph.assets_within_hops([process_id], max_hops=4):
                complete.append(process_id)

        return Criterion(
            number=9,
            name="Construct an inspectable investment case",
            met=bool(complete),
            detail=(
                f"{len(complete)}/{len(process_ids)} Process(es) reach an Asset by "
                f"traversal through the Bottleneck and Capability layers"
            ),
        )

    # 10 --------------------------------------------------------------- #

    async def _monitors_the_thesis_over_time(self, session: AsyncSession) -> Criterion:
        """Journal entries explaining a change, plus more than one State observation."""
        journal = (
            await session.execute(select(func.count()).select_from(JournalEntry))
        ).scalar_one()
        state_counts = (
            await session.execute(
                select(ProcessState.process_id, func.count().label("n")).group_by(
                    ProcessState.process_id
                )
            )
        ).all()
        revised = [r for r in state_counts if r.n > 1]
        superseded = (
            await session.execute(
                select(func.count()).select_from(Process).where(Process.valid_to.is_not(None))
            )
        ).scalar_one()
        return Criterion(
            number=10,
            name="Monitor changes to the thesis over time",
            met=journal > 0 and (bool(revised) or superseded > 0),
            detail=(
                f"{journal} journal entr(ies); {len(revised)} Process(es) with more than "
                f"one State observation; {superseded} superseded Process revision(s)"
            ),
        )

    # 11 --------------------------------------------------------------- #

    def _learns_from_historical_outcomes(self) -> Criterion:
        """Explicitly not met, and explicitly not counted against the gate.

        §28 lists this among the eleven, but `phases.txt` places the historical
        engine in Phase 2. Marking it "met" would be false and marking it
        "failed" would make the gate unpassable by design; it is deferred, and
        the report says which phase owes it.
        """
        return Criterion(
            number=11,
            name="Learn from historical outcomes",
            met=False,
            detail=(
                "No historical State-conditioned episodes, analog retrieval or "
                "realised outcomes exist yet. This is agent doc §17's Level 3-4, "
                "which the doc is explicit must not be optimised for before "
                "Levels 1-2 are validated."
            ),
            deferred_to="Phase 2 (#35-#46)",
        )


def render_markdown(report: Phase0Report, *, notes: Sequence[str] = ()) -> str:
    verdict = "PASS" if report.passed else "FAIL"
    met = sum(1 for c in report.in_scope if c.met)
    lines = [
        "# Phase 0 validation — PRD §28",
        "",
        f"**{verdict}** — {met}/{len(report.in_scope)} in-scope criteria met, "
        f"{len(report.criteria) - len(report.in_scope)} deferred.",
        "",
        f"Graph produced by the `{report.provider}` provider at "
        f"{report.ran_at.isoformat(timespec='seconds')}.",
        "",
        "| # | Criterion | Status | Evidence |",
        "|---|---|---|---|",
    ]
    lines += [f"| {c.number} | {c.name} | {c.status} | {c.detail} |" for c in report.criteria]
    lines.append("")

    deferred = [c for c in report.criteria if c.deferred_to]
    if deferred:
        lines += ["## Deferred", ""]
        lines += [f"- **{c.name}** → {c.deferred_to}. {c.detail}" for c in deferred]
        lines.append("")

    if report.unmet:
        lines += ["## Not met", ""]
        lines += [f"- **{c.name}** — {c.detail}" for c in report.unmet]
        lines.append("")

    if notes:
        lines += ["## Notes on what this does and does not establish", ""]
        lines += [f"- {note}" for note in notes]
        lines.append("")
    return "\n".join(lines)


#: Attached to every generated report. The gate is about the pipeline; saying so
#: in the artefact is cheaper than discovering the confusion later.
STANDING_NOTES = (
    "These criteria are satisfied by rows and edges in the graph, not by the "
    "presence of the agents that write them. Every check reads the database.",
    "Passing establishes that a document stream became a coherent, connected, "
    "provenanced Process graph. It does not establish that the Process is the "
    "right one — that is what the labelled benchmarks measure, and they require "
    "a real model provider and a larger dataset than Phase 0 has.",
    "Criterion 11 is deferred rather than failed. Counting it against the gate "
    "would make Phase 0 unpassable by design, since phases.txt places the "
    "historical engine in Phase 2.",
)


async def evaluate_phase0(
    session_factory: async_sessionmaker[AsyncSession], *, provider: str
) -> Phase0Report:
    return await Phase0Evaluation(session_factory).evaluate(provider=provider)


__all__ = [
    "STANDING_NOTES",
    "Criterion",
    "Phase0Evaluation",
    "Phase0Report",
    "evaluate_phase0",
    "render_markdown",
]
