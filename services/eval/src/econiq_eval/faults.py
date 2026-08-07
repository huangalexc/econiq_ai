"""Synthetic fault injection (agent doc §19).

The audits in :mod:`econiq_eval.audit` answer "is this database clean?". On a
clean database they return nothing — which is also what a broken audit returns.
This module closes that gap: it writes a known defect and asserts the audit
finds it.

That inversion is the entire value. An integrity check nobody has ever seen fire
is not a check, it is a comment; and the checks here guard the properties whose
violation makes the system look *better* rather than worse. A leaked future
document produces a more accurate Process. Duplicated evidence produces higher
confidence. Nothing downstream complains, so the only thing standing between the
system and a confident wrong answer is a check that provably fires.

Each fault runs inside a transaction that is rolled back, so the benchmark
leaves the database as it found it.

The §19 list is implemented as far as Phase 0 reaches. ``survivorship_bias`` and
``return_calculation`` need realised market data and are reported as deferred
rather than passed — a fault that cannot be injected has not been defended
against, and recording it as a pass would be the exact self-deception this
module exists to prevent.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from econiq_data_models import (
    AgentRun,
    AgentRunStatus,
    Claim,
    Document,
    EvidenceLink,
    Node,
    Relationship,
)
from econiq_ontology import (
    ClaimType,
    DocumentType,
    EntityType,
    ExtractionStatus,
    RelationshipType,
    utcnow,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_eval.audit import (
    AuditFinding,
    DuplicationAudit,
    PointInTimeAudit,
    ProvenanceAudit,
)

Injector = Callable[[AsyncSession], Awaitable[None]]
Detector = Callable[[async_sessionmaker[AsyncSession]], Awaitable[Sequence[AuditFinding]]]


class Defence(StrEnum):
    """How the system is supposed to stop a fault.

    The distinction is worth keeping. ``PREVENTED`` means the write cannot
    happen — a database constraint refuses it, and no audit is needed or even
    possible. ``DETECTED`` means the write succeeds and a check has to find it
    afterwards. Prevention is strictly stronger, and collapsing the two would
    hide which faults are guarded by a constraint and which by vigilance.
    """

    PREVENTED = "prevented"
    DETECTED = "detected"


@dataclass(frozen=True, slots=True)
class Fault:
    """A known defect and the defence that is supposed to stop it."""

    name: str
    description: str
    inject: Injector
    expected_check: str
    detect: Detector | None = None
    defence: Defence = Defence.DETECTED


@dataclass(frozen=True, slots=True)
class FaultResult:
    fault: str
    detected: bool
    expected_check: str
    defence: Defence = Defence.DETECTED
    findings: tuple[str, ...] = ()

    @property
    def detail(self) -> str:
        if self.detected and self.defence is Defence.PREVENTED:
            return f"refused by {self.expected_check} before it could be written"
        if self.detected:
            return f"caught by {self.expected_check}"
        if self.defence is Defence.PREVENTED:
            return f"NOT PREVENTED — {self.expected_check} allowed the write"
        return f"NOT CAUGHT — {self.expected_check} reported nothing"


@dataclass(frozen=True, slots=True)
class FaultInjectionReport:
    results: tuple[FaultResult, ...]
    deferred: tuple[str, ...]

    @property
    def detection_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.detected) / len(self.results)

    @property
    def missed(self) -> tuple[FaultResult, ...]:
        return tuple(r for r in self.results if not r.detected)

    @property
    def clean(self) -> bool:
        return not self.missed


#: §19 faults that need Phase 2 data. Named so the report shows a gap, not a
#: silence.
DEFERRED_FAULTS = (
    "survivorship_bias: needs point-in-time index membership (Phase 2, #35-#46)",
    "incorrect_return_calculation: needs the Asset return series (Phase 2, #35-#46)",
    "false_event_merge: needs a labelled clustering corpus; graded by "
    "grade_clustering's false_merge_rate rather than by injection",
)


async def _point_in_time(
    factory: async_sessionmaker[AsyncSession],
) -> Sequence[AuditFinding]:
    return (await PointInTimeAudit(factory).run()).findings


async def _provenance(factory: async_sessionmaker[AsyncSession]) -> Sequence[AuditFinding]:
    return (await ProvenanceAudit(factory).run()).findings


async def _duplication(factory: async_sessionmaker[AsyncSession]) -> Sequence[AuditFinding]:
    return (await DuplicationAudit(factory).run()).findings


# --------------------------------------------------------------------------- #
# Injectors
# --------------------------------------------------------------------------- #


async def _seed_document(session: AsyncSession, *, published_offset_days: int = -1) -> uuid.UUID:
    document_id = uuid.uuid4()
    session.add(Node(node_id=document_id, node_type=EntityType.DOCUMENT))
    await session.flush()
    session.add(
        Document(
            document_id=document_id,
            source="fault-injection",
            publisher="Synthetic",
            title="Injected document",
            document_type=DocumentType.NEWS_ARTICLE,
            publication_time=utcnow() + timedelta(days=published_offset_days),
            retrieved_at=utcnow(),
            content_hash=uuid.uuid4().hex,
            extraction_status=ExtractionStatus.PARSED,
        )
    )
    await session.flush()
    return document_id


async def _seed_run(session: AsyncSession, *, as_of_offset_days: int = -30) -> uuid.UUID:
    run_id = uuid.uuid4()
    session.add(
        AgentRun(
            agent_run_id=run_id,
            agent_name="fault_injection",
            agent_version="0.0.0",
            ontology_layer="Claim",
            input_schema_version="1.0.0",
            output_schema_version="1.0.0",
            as_of=utcnow() + timedelta(days=as_of_offset_days),
            status=AgentRunStatus.SUCCEEDED,
            input_payload={},
            output_payload={},
        )
    )
    await session.flush()
    return run_id


def _claim(
    *, document_id: uuid.UUID, run_id: uuid.UUID | None, **overrides: object
) -> tuple[Node, Claim]:
    claim_id = uuid.uuid4()
    node = Node(node_id=claim_id, node_type=EntityType.CLAIM)
    claim = Claim(
        claim_id=claim_id,
        document_id=document_id,
        text="An injected proposition.",
        claim_type=ClaimType.REPORTED_CLAIM,
        source_location={"quote": "injected", "char_start": 0, "char_end": 8},
        extraction_confidence=0.9,
        entities=[],
        agent_run_id=run_id,
        **overrides,
    )
    return node, claim


async def inject_temporal_leakage(session: AsyncSession) -> None:
    """A run reads a document published after its own point-in-time cut-off.

    Agent doc §19's headline example, and the one whose absence would be
    hardest to notice: the answer gets better, not worse.
    """
    document_id = await _seed_document(session, published_offset_days=-1)
    run_id = await _seed_run(session, as_of_offset_days=-30)
    node, claim = _claim(document_id=document_id, run_id=run_id)
    session.add(node)
    await session.flush()
    session.add(claim)
    await session.flush()


async def inject_unsupported_claim(session: AsyncSession) -> None:
    """A Claim with no agent run — nothing to attribute the quotation to."""
    document_id = await _seed_document(session)
    node, claim = _claim(document_id=document_id, run_id=None)
    session.add(node)
    await session.flush()
    session.add(claim)
    await session.flush()


async def inject_incorrect_date(session: AsyncSession) -> None:
    """A Claim dated after the document that contains it."""
    document_id = await _seed_document(session, published_offset_days=-10)
    run_id = await _seed_run(session)
    node, claim = _claim(
        document_id=document_id,
        run_id=run_id,
        stated_at=utcnow(),
    )
    session.add(node)
    await session.flush()
    session.add(claim)
    await session.flush()


async def inject_duplicate_evidence(session: AsyncSession) -> None:
    """The same Event supporting the same Process twice, inflating confidence."""
    subject_id, evidence_id = uuid.uuid4(), uuid.uuid4()
    session.add(Node(node_id=subject_id, node_type=EntityType.PROCESS))
    session.add(Node(node_id=evidence_id, node_type=EntityType.EVENT))
    await session.flush()
    for _ in range(2):
        session.add(
            EvidenceLink(
                evidence_link_id=uuid.uuid4(),
                subject_id=subject_id,
                evidence_id=evidence_id,
                supports=True,
                weight=1.0,
            )
        )
    await session.flush()


async def inject_duplicate_document(session: AsyncSession) -> None:
    """The same content ingested twice — syndication that was not collapsed."""
    content_hash = uuid.uuid4().hex
    for index in range(2):
        document_id = uuid.uuid4()
        session.add(Node(node_id=document_id, node_type=EntityType.DOCUMENT))
        await session.flush()
        session.add(
            Document(
                document_id=document_id,
                source=f"wire-{index}",
                publisher=f"Publisher {index}",
                title="Identical wire copy",
                document_type=DocumentType.NEWS_ARTICLE,
                publication_time=utcnow() - timedelta(days=1),
                retrieved_at=utcnow(),
                content_hash=content_hash,
                extraction_status=ExtractionStatus.PARSED,
            )
        )
        await session.flush()


async def inject_circular_process(session: AsyncSession) -> None:
    """Process A causes B causes A — traversal and explanation both break."""
    a, b = uuid.uuid4(), uuid.uuid4()
    session.add(Node(node_id=a, node_type=EntityType.PROCESS))
    session.add(Node(node_id=b, node_type=EntityType.PROCESS))
    await session.flush()
    for source, target in ((a, b), (b, a)):
        session.add(
            Relationship(
                relationship_id=uuid.uuid4(),
                revision=1,
                source_id=source,
                target_id=target,
                relationship_type=RelationshipType.INFLUENCES,
                weight=0.8,
                confidence=0.8,
                rationale="injected cycle",
            )
        )
    await session.flush()


async def inject_illegal_edge(session: AsyncSession) -> None:
    """A Bottleneck wired straight to an Asset, skipping the Capability layer.

    The skip is what makes a discovery chain inspectable, so an edge that jumps
    it produces an Asset nobody can explain.
    """
    bottleneck_id, asset_id = uuid.uuid4(), uuid.uuid4()
    session.add(Node(node_id=bottleneck_id, node_type=EntityType.BOTTLENECK))
    session.add(Node(node_id=asset_id, node_type=EntityType.ASSET))
    await session.flush()
    session.add(
        Relationship(
            relationship_id=uuid.uuid4(),
            revision=1,
            source_id=bottleneck_id,
            target_id=asset_id,
            relationship_type=RelationshipType.EXPRESSED_BY,
            weight=0.9,
            confidence=0.9,
            rationale="injected illegal edge",
        )
    )
    await session.flush()


async def _graph_findings(
    factory: async_sessionmaker[AsyncSession],
) -> Sequence[AuditFinding]:
    from econiq_graph import GraphIntegrity

    report = await GraphIntegrity(factory).check()
    return [
        AuditFinding(check=f"graph.{v.kind}", subject_id=v.node_id, detail=v.detail)
        for v in report.violations
    ]


FAULTS: tuple[Fault, ...] = (
    Fault(
        name="temporal_leakage",
        description="A run cites a document published after its point-in-time cut-off",
        inject=inject_temporal_leakage,
        detect=_point_in_time,
        expected_check="claims_from_future_documents",
    ),
    Fault(
        name="incorrect_date",
        description="A Claim dated after the document containing it",
        inject=inject_incorrect_date,
        detect=_point_in_time,
        expected_check="claims_stated_after_publication",
    ),
    Fault(
        name="unsupported_claim",
        description="A Claim with no agent run behind it",
        inject=inject_unsupported_claim,
        detect=_provenance,
        expected_check="derived_rows_without_a_run",
    ),
    Fault(
        name="duplicate_evidence",
        description="One Event linked twice to the same subject",
        inject=inject_duplicate_evidence,
        detect=_duplication,
        expected_check="duplicate_evidence_links",
    ),
    Fault(
        # Not an audit: the unique index on documents.content_hash refuses the
        # second write. Kept in the benchmark because a schema change that
        # dropped that index would otherwise be invisible.
        name="duplicate_document",
        description="Identical content ingested under two sources",
        inject=inject_duplicate_document,
        expected_check="uq_documents_content_hash",
        defence=Defence.PREVENTED,
    ),
    Fault(
        name="circular_process",
        description="Two Processes each causing the other",
        inject=inject_circular_process,
        detect=_graph_findings,
        expected_check="graph.causal_cycle",
    ),
    Fault(
        name="false_capability_edge",
        description="A Bottleneck wired directly to an Asset",
        inject=inject_illegal_edge,
        detect=_graph_findings,
        expected_check="graph.illegal_edge",
    ),
)


async def run_fault_injection(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    faults: Sequence[Fault] = FAULTS,
) -> FaultInjectionReport:
    """Inject each fault, run its detector, roll back.

    Detection is matched on the *expected* check rather than on "any finding".
    A leakage fault caught by the duplicate-document check would mean the
    detector is firing for the wrong reason, and counting that as a pass would
    make the benchmark agree with a broken system.
    """
    results = [await _run_one(session_factory, fault) for fault in faults]
    return FaultInjectionReport(results=tuple(results), deferred=DEFERRED_FAULTS)


async def _run_one(session_factory: async_sessionmaker[AsyncSession], fault: Fault) -> FaultResult:
    matched: tuple[str, ...] = ()
    prevented = False

    async with session_factory() as session:
        transaction = await session.begin_nested()
        try:
            try:
                await fault.inject(session)
            except IntegrityError as exc:
                # The database refused the write. For a PREVENTED fault that is
                # the pass condition; for a DETECTED one it means the injector
                # is broken, and reporting it as caught would hide that.
                prevented = True
                matched = (str(exc.orig).strip().splitlines()[0],)
            else:
                if fault.detect is not None:
                    findings = await _detect_in_session(session, fault)
                    matched = tuple(f.detail for f in findings if f.check == fault.expected_check)
        finally:
            await transaction.rollback()

    detected = (
        prevented and fault.expected_check in matched[0]
        if fault.defence is Defence.PREVENTED and matched
        else (bool(matched) and not prevented)
    )
    return FaultResult(
        fault=fault.name,
        detected=detected,
        expected_check=fault.expected_check,
        defence=fault.defence,
        findings=matched[:3],
    )


async def _detect_in_session(session: AsyncSession, fault: Fault) -> Sequence[AuditFinding]:
    """Run the detector against the session holding the uncommitted fault.

    The detectors take a session factory because that is how every other
    component in this system takes a database. Here the fault only exists inside
    one open transaction, so it is handed a factory that yields that session and
    ignores close — the alternative is committing the fault, and a benchmark
    that leaves wreckage behind cannot be run against anything real.
    """

    class _Bound:
        def __call__(self) -> _Bound:
            return self

        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *_: object) -> None:
            return None

    assert fault.detect is not None  # guarded by the caller
    return await fault.detect(_Bound())  # type: ignore[arg-type]
