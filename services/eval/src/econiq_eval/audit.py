"""Point-in-time and provenance audits (agent doc §20, §21).

These are not benchmarks. A benchmark says the system is 74% accurate; an audit
says the system cheated. Nothing here depends on labelled data, so every check
runs against any database — a test fixture, the end-to-end corpus, or
production — and any finding is a defect rather than a score.

Two families:

**Point-in-time integrity (§20).** At historical date `t` the system may read
documents published on or before `t` and nothing else. The doc is explicit that
this must be enforced programmatically rather than by convention, because the
convention is invisible when it breaks: a leaked future document produces a
*better* answer, so the failure mode is a system that looks like it is working.

**Provenance and versioning (§21).** Every derived row must reach a run, and
every run must name its prompt version, its model version and the schema
versions on both sides. A row that cannot answer "which prompt produced this?"
cannot be re-evaluated when the prompt changes, which makes every later
comparison between prompt versions quietly wrong.

``GraphIntegrity`` in ``econiq_graph`` covers the structural checks — illegal
edges, causal cycles, orphans, competing current revisions. This module does not
repeat them; :func:`full_audit` runs both and merges the findings.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from econiq_data_models import (
    AgentRun,
    AgentRunStatus,
    AssetExposure,
    Claim,
    Critique,
    Document,
    EvidenceLink,
    ProcessState,
    Scorecard,
)
from econiq_graph import GraphIntegrity
from econiq_ontology import utcnow
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """One concrete violation, identified well enough to go and look at it."""

    check: str
    subject_id: uuid.UUID | None
    detail: str

    def __str__(self) -> str:
        return f"{self.check}: {self.detail}"


@dataclass(frozen=True, slots=True)
class AuditReport:
    findings: tuple[AuditFinding, ...] = ()
    checks_run: tuple[str, ...] = ()
    deferred: tuple[str, ...] = field(default=())

    @property
    def clean(self) -> bool:
        return not self.findings

    def by_check(self) -> dict[str, list[AuditFinding]]:
        grouped: dict[str, list[AuditFinding]] = {}
        for finding in self.findings:
            grouped.setdefault(finding.check, []).append(finding)
        return grouped

    def __add__(self, other: AuditReport) -> AuditReport:
        return AuditReport(
            findings=self.findings + other.findings,
            checks_run=self.checks_run + other.checks_run,
            deferred=self.deferred + other.deferred,
        )


#: Evidence links are written in the same transaction as the run that made them,
#: so an exact comparison would flag ordinary clock skew. A day is wide enough to
#: stay quiet and narrow enough that a real backdating still shows up.
_SKEW_TOLERANCE = timedelta(days=1)

#: Checks the agent doc asks for that Phase 0 cannot yet perform, named rather
#: than silently absent. Both need realised market data, which arrives with the
#: historical outcome engine (#35-#46).
DEFERRED_CHECKS = (
    "survivorship_bias: needs a point-in-time index membership history (Phase 2)",
    "return_calculation: needs the Asset return series (Phase 2)",
)


class PointInTimeAudit:
    """Did any agent see something it could not have seen?"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def run(self) -> AuditReport:
        async with self.session_factory() as session:
            findings = (
                await self.claims_from_future_documents(session)
                + await self.claims_stated_after_publication(session)
                + await self.evidence_recorded_after_its_run(session)
                + await self.observations_recorded_in_the_future(session)
            )
        return AuditReport(
            findings=tuple(findings),
            checks_run=(
                "claims_from_future_documents",
                "claims_stated_after_publication",
                "evidence_recorded_after_its_run",
                "observations_recorded_in_the_future",
            ),
            deferred=DEFERRED_CHECKS,
        )

    async def claims_from_future_documents(self, session: AsyncSession) -> list[AuditFinding]:
        """The core §20 violation: a run read a document published after its cut-off.

        This is the one that matters most, because leakage improves the answer.
        An agent that saw next month's filing writes a better Process, scores
        better on every benchmark above, and is worthless.
        """
        rows = (
            await session.execute(
                select(
                    Claim.claim_id,
                    Document.publication_time,
                    AgentRun.as_of,
                    AgentRun.agent_name,
                )
                .join(Document, Document.document_id == Claim.document_id)
                .join(AgentRun, AgentRun.agent_run_id == Claim.agent_run_id)
                .where(Document.publication_time > AgentRun.as_of)
            )
        ).all()
        return [
            AuditFinding(
                check="claims_from_future_documents",
                subject_id=claim_id,
                detail=(
                    f"{agent} ran as of {as_of.isoformat()} but this Claim comes "
                    f"from a document published {published.isoformat()}"
                ),
            )
            for claim_id, published, as_of, agent in rows
        ]

    async def claims_stated_after_publication(self, session: AsyncSession) -> list[AuditFinding]:
        """A Claim dated after the document that contains it (§19 'incorrect date')."""
        rows = (
            await session.execute(
                select(Claim.claim_id, Claim.stated_at, Document.publication_time)
                .join(Document, Document.document_id == Claim.document_id)
                .where(Claim.stated_at.is_not(None), Claim.stated_at > Document.publication_time)
            )
        ).all()
        return [
            AuditFinding(
                check="claims_stated_after_publication",
                subject_id=claim_id,
                detail=(
                    f"stated_at {stated.isoformat()} is after its document's "
                    f"publication at {published.isoformat()}"
                ),
            )
            for claim_id, stated, published in rows
        ]

    async def evidence_recorded_after_its_run(self, session: AsyncSession) -> list[AuditFinding]:
        """An evidence link created by a run that predates the evidence itself."""
        rows = (
            await session.execute(
                select(
                    EvidenceLink.evidence_link_id,
                    EvidenceLink.created_at,
                    AgentRun.as_of,
                )
                .join(AgentRun, AgentRun.agent_run_id == EvidenceLink.agent_run_id)
                .where(EvidenceLink.created_at < AgentRun.started_at - _SKEW_TOLERANCE)
            )
        ).all()
        return [
            AuditFinding(
                check="evidence_recorded_after_its_run",
                subject_id=link_id,
                detail=(
                    f"evidence link created {created.isoformat()} against a run "
                    f"whose cut-off was {as_of.isoformat()}"
                ),
            )
            for link_id, created, as_of in rows
        ]

    async def observations_recorded_in_the_future(
        self, session: AsyncSession
    ) -> list[AuditFinding]:
        """`recorded_at` beyond now — a clock problem that would corrupt every replay."""
        now = utcnow()
        findings: list[AuditFinding] = []
        for model, id_column, label in (
            (ProcessState, ProcessState.process_state_id, "process_state"),
            (AssetExposure, AssetExposure.asset_exposure_id, "asset_exposure"),
            (Critique, Critique.critique_id, "critique"),
            (Scorecard, Scorecard.scorecard_id, "scorecard"),
        ):
            query: Select[tuple[uuid.UUID, datetime]] = select(id_column, model.recorded_at).where(
                model.recorded_at > now
            )
            for row_id, recorded in (await session.execute(query)).all():
                findings.append(
                    AuditFinding(
                        check="observations_recorded_in_the_future",
                        subject_id=row_id,
                        detail=f"{label} claims to have been recorded at {recorded.isoformat()}",
                    )
                )
        return findings


class ProvenanceAudit:
    """Can every derived row name the prompt and model that produced it (§21)?"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def run(self) -> AuditReport:
        async with self.session_factory() as session:
            findings = (
                await self.runs_without_versions(session)
                + await self.derived_rows_without_a_run(session)
                + await self.accepted_rows_from_rejected_runs(session)
            )
        return AuditReport(
            findings=tuple(findings),
            checks_run=(
                "runs_without_versions",
                "derived_rows_without_a_run",
                "accepted_rows_from_rejected_runs",
            ),
        )

    async def runs_without_versions(self, session: AsyncSession) -> list[AuditFinding]:
        """§21's required fields, checked rather than assumed."""
        rows = (
            await session.execute(
                select(AgentRun.agent_run_id, AgentRun.agent_name)
                .where(
                    AgentRun.prompt_version_id.is_(None)
                    | AgentRun.model_version_id.is_(None)
                    | AgentRun.output_schema_version.is_(None)
                )
                # A failed run legitimately has no output schema version: it
                # never produced an output. Only runs that returned something
                # are held to the full chain. Keyed off status rather than a
                # null output_payload, because SQLAlchemy stores Python None in
                # a JSONB column as JSON `null` — `IS NOT NULL` is true for it.
                .where(AgentRun.status.in_([AgentRunStatus.SUCCEEDED, AgentRunStatus.REJECTED]))
            )
        ).all()
        return [
            AuditFinding(
                check="runs_without_versions",
                subject_id=run_id,
                detail=f"{agent} produced output without a complete prompt/model/schema chain",
            )
            for run_id, agent in rows
        ]

    async def derived_rows_without_a_run(self, session: AsyncSession) -> list[AuditFinding]:
        """An ontology row nobody can attribute.

        Claims are the strictest case and the one worth failing on: a Claim is a
        quotation, and an unattributable quotation is exactly what the evidence
        chain exists to prevent.
        """
        rows = (
            (await session.execute(select(Claim.claim_id).where(Claim.agent_run_id.is_(None))))
            .scalars()
            .all()
        )
        return [
            AuditFinding(
                check="derived_rows_without_a_run",
                subject_id=claim_id,
                detail="Claim has no agent run, so no prompt or model can be attributed to it",
            )
            for claim_id in rows
        ]

    async def accepted_rows_from_rejected_runs(self, session: AsyncSession) -> list[AuditFinding]:
        """Output the evaluator rejected must not have reached the ontology.

        ``AgentRunRecorder`` marks a run `rejected` when a deterministic check
        failed. If rows still cite that run, the check ran and was ignored,
        which is worse than not having run it.
        """
        rejected = select(AgentRun.agent_run_id).where(AgentRun.status == AgentRunStatus.REJECTED)
        rows = (
            await session.execute(
                select(Claim.claim_id, Claim.agent_run_id).where(Claim.agent_run_id.in_(rejected))
            )
        ).all()
        return [
            AuditFinding(
                check="accepted_rows_from_rejected_runs",
                subject_id=claim_id,
                detail=f"persisted from run {run_id} whose evaluation rejected the output",
            )
            for claim_id, run_id in rows
        ]


class DuplicationAudit:
    """Duplicate evidence (§19), which silently inflates confidence.

    Two links from the same subject to the same evidence make one fact look like
    two. Independent source counting is the defence (ontology §47) and this is
    the check that it held.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def run(self) -> AuditReport:
        async with self.session_factory() as session:
            duplicates = (
                await session.execute(
                    select(
                        EvidenceLink.subject_id,
                        EvidenceLink.evidence_id,
                        func.count().label("n"),
                    )
                    .where(EvidenceLink.retracted_at.is_(None))
                    .group_by(EvidenceLink.subject_id, EvidenceLink.evidence_id)
                    .having(func.count() > 1)
                )
            ).all()

        findings = [
            AuditFinding(
                check="duplicate_evidence_links",
                subject_id=subject_id,
                detail=f"evidence {evidence_id} is linked {count} times to this subject",
            )
            for subject_id, evidence_id, count in duplicates
        ]
        # Duplicate *documents* are not audited here: `documents.content_hash`
        # is uniquely indexed, so the database refuses them outright. A check
        # that cannot fire is a comment; the fault benchmark proves the
        # constraint instead (see `Defence.PREVENTED` in `faults`).
        return AuditReport(
            findings=tuple(findings),
            checks_run=("duplicate_evidence_links",),
        )


async def full_audit(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    as_of: datetime | None = None,
) -> AuditReport:
    """Every integrity check the system can perform, in one report."""
    report = (
        await PointInTimeAudit(session_factory).run()
        + await ProvenanceAudit(session_factory).run()
        + await DuplicationAudit(session_factory).run()
    )

    structural = await GraphIntegrity(session_factory).check(as_of=as_of)
    return report + AuditReport(
        findings=tuple(
            AuditFinding(
                check=f"graph.{violation.kind}",
                subject_id=violation.node_id,
                detail=violation.detail,
            )
            for violation in structural.violations
        ),
        checks_run=(
            "graph.illegal_edge",
            "graph.causal_cycle",
            "graph.orphaned_node",
            "graph.multiple_current_revisions",
        ),
    )


def summarise(report: AuditReport) -> Sequence[str]:
    """Human-readable lines, worst first."""
    if report.clean:
        return [f"{len(report.checks_run)} integrity checks, no findings."]
    grouped = report.by_check()
    return [
        f"{check}: {len(items)} finding(s) — {items[0].detail}"
        for check, items in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    ]
