"""Audits and fault injection against a real database.

The central test is :func:`test_every_injected_fault_is_caught_by_its_own_check`.
Everything else in the harness measures the system; that one measures the
harness, which is the only reason to trust the rest of it.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from econiq_data_models import (
    AgentRun,
    AgentRunStatus,
    Claim,
    Document,
    ModelVersion,
    Node,
    PromptVersion,
)
from econiq_eval import (
    FAULTS,
    DuplicationAudit,
    PointInTimeAudit,
    ProvenanceAudit,
    RunLedger,
    full_audit,
    render_markdown,
    run_fault_injection,
    run_harness,
)
from econiq_eval.faults import inject_temporal_leakage
from econiq_ontology import ClaimType, DocumentType, EntityType, ExtractionStatus, utcnow

pytestmark = pytest.mark.integration


async def test_every_injected_fault_is_caught_by_its_own_check(session_factory):
    """Agent doc §19. A check that has never fired is a comment, not a check."""
    report = await run_fault_injection(session_factory)

    assert report.results, "no faults were injected"
    assert report.clean, f"undetected: {[r.fault for r in report.missed]}"
    assert report.detection_rate == 1.0
    assert {r.fault for r in report.results} == {f.name for f in FAULTS}


async def test_a_constraint_is_reported_as_prevention_not_detection(session_factory):
    """A fault the database refuses never needed an audit, and the report says so.

    Collapsing this into "detected" would hide which faults are guarded by a
    constraint and which by a check somebody has to keep working.
    """
    from econiq_eval import Defence

    report = await run_fault_injection(session_factory)
    duplicate = next(r for r in report.results if r.fault == "duplicate_document")

    assert duplicate.defence is Defence.PREVENTED
    assert duplicate.detected is True
    assert "refused by" in duplicate.detail

    leakage = next(r for r in report.results if r.fault == "temporal_leakage")
    assert leakage.defence is Defence.DETECTED


async def test_fault_injection_leaves_the_database_as_it_found_it(session_factory):
    """Each fault is written inside a nested transaction and rolled back."""
    await run_fault_injection(session_factory)

    audit = await full_audit(session_factory)
    assert audit.clean, [str(f) for f in audit.findings]


async def test_a_detector_firing_for_the_wrong_reason_is_not_a_pass(session_factory):
    """Detection is matched on the expected check, not on 'any finding'.

    Without this, a single noisy detector would make the whole benchmark green.
    """
    from econiq_eval.faults import Fault, _duplication

    mismatched = Fault(
        name="leakage_watched_by_the_wrong_check",
        description="Temporal leakage, but graded against the duplication audit",
        inject=inject_temporal_leakage,
        detect=_duplication,
        expected_check="duplicate_evidence_links",
    )

    report = await run_fault_injection(session_factory, faults=[mismatched])

    assert report.results[0].detected is False


async def test_a_clean_database_produces_no_findings(session_factory):
    report = await full_audit(session_factory)

    assert report.clean
    assert "claims_from_future_documents" in report.checks_run
    assert "graph.causal_cycle" in report.checks_run
    # The two checks Phase 0 cannot perform are named rather than omitted.
    assert any("survivorship_bias" in item for item in report.deferred)


async def test_leakage_is_found_even_though_it_improves_the_answer(session_factory):
    """The §20 violation whose symptom is a better result, not a worse one."""
    async with session_factory() as session:
        await inject_temporal_leakage(session)
        await session.commit()

    findings = (await PointInTimeAudit(session_factory).run()).findings

    assert [f.check for f in findings] == ["claims_from_future_documents"]
    assert "published" in findings[0].detail


async def test_a_claim_without_a_run_cannot_be_attributed(session_factory):
    async with session_factory() as session:
        document_id = uuid.uuid4()
        claim_id = uuid.uuid4()
        session.add(Node(node_id=document_id, node_type=EntityType.DOCUMENT))
        session.add(Node(node_id=claim_id, node_type=EntityType.CLAIM))
        await session.flush()
        session.add(
            Document(
                document_id=document_id,
                source="test",
                title="A document",
                document_type=DocumentType.NEWS_ARTICLE,
                publication_time=utcnow() - timedelta(days=1),
                retrieved_at=utcnow(),
                content_hash=uuid.uuid4().hex,
                extraction_status=ExtractionStatus.PARSED,
            )
        )
        await session.flush()
        session.add(
            Claim(
                claim_id=claim_id,
                document_id=document_id,
                text="Unattributable.",
                claim_type=ClaimType.REPORTED_CLAIM,
                source_location={"quote": "x", "char_start": 0, "char_end": 1},
                extraction_confidence=0.9,
                entities=[],
                agent_run_id=None,
            )
        )
        await session.commit()

    findings = (await ProvenanceAudit(session_factory).run()).findings

    assert [f.check for f in findings] == ["derived_rows_without_a_run"]


async def test_output_a_run_produced_without_versions_is_a_finding(session_factory):
    """Agent doc §21: a row that cannot name its prompt cannot be re-evaluated."""
    async with session_factory() as session:
        session.add(
            AgentRun(
                agent_run_id=uuid.uuid4(),
                agent_name="unversioned",
                agent_version="1.0.0",
                ontology_layer="Process",
                input_schema_version="1.0.0",
                as_of=utcnow(),
                status=AgentRunStatus.SUCCEEDED,
                input_payload={},
                output_payload={"result": "something"},
            )
        )
        await session.commit()

    findings = (await ProvenanceAudit(session_factory).run()).findings

    assert [f.check for f in findings] == ["runs_without_versions"]


async def test_a_failed_run_is_not_held_to_the_output_schema_version(session_factory):
    """It never produced an output, so there is no output schema to record."""
    async with session_factory() as session:
        session.add(
            AgentRun(
                agent_run_id=uuid.uuid4(),
                agent_name="failed",
                agent_version="1.0.0",
                ontology_layer="Process",
                input_schema_version="1.0.0",
                as_of=utcnow(),
                status=AgentRunStatus.FAILED,
                input_payload={},
                output_payload=None,
                error="provider unavailable",
            )
        )
        await session.commit()

    assert (await ProvenanceAudit(session_factory).run()).clean


async def test_duplicate_evidence_inflates_confidence_and_is_caught(session_factory):
    subject_id, evidence_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        from econiq_data_models import EvidenceLink

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
                )
            )
        await session.commit()

    findings = (await DuplicationAudit(session_factory).run()).findings

    assert [f.check for f in findings] == ["duplicate_evidence_links"]
    assert "linked 2 times" in findings[0].detail


async def test_the_run_ledger_compares_two_prompt_versions(session_factory):
    """§21's versioning is only worth the trouble if the versions get compared."""
    async with session_factory() as session:
        model_version_id = uuid.uuid4()
        session.add(
            ModelVersion(model_version_id=model_version_id, provider="scripted", model="test-model")
        )
        versions = {}
        for version, rejected in (("1.0.0", 2), ("1.1.0", 0)):
            prompt_version_id = uuid.uuid4()
            versions[version] = prompt_version_id
            session.add(
                PromptVersion(
                    prompt_version_id=prompt_version_id,
                    name="process_discovery",
                    version=version,
                    content_hash=uuid.uuid4().hex,
                    template="…",
                )
            )
            await session.flush()
            for index in range(4):
                session.add(
                    AgentRun(
                        agent_run_id=uuid.uuid4(),
                        agent_name="process_discovery",
                        agent_version="1.0.0",
                        ontology_layer="Process",
                        prompt_version_id=prompt_version_id,
                        model_version_id=model_version_id,
                        input_schema_version="1.0.0",
                        output_schema_version="1.0.0",
                        as_of=utcnow(),
                        status=(
                            AgentRunStatus.REJECTED
                            if index < rejected
                            else AgentRunStatus.SUCCEEDED
                        ),
                        input_payload={},
                        output_payload={},
                        attempts=1,
                        cost_usd=0.10,
                        latency_ms=1000.0,
                    )
                )
        await session.commit()

    comparison = await RunLedger(session_factory).compare(
        "process_discovery", baseline="1.0.0", candidate="1.1.0"
    )

    assert comparison is not None
    assert comparison.baseline.rejection_rate == 0.5
    assert comparison.candidate.rejection_rate == 0.0
    assert comparison.regressed is False
    assert "no worse" in comparison.summary()


async def test_comparing_against_a_version_with_no_runs_returns_nothing(session_factory):
    """A zeroed row would let a prompt ship on a statistic nobody computed."""
    result = await RunLedger(session_factory).compare(
        "process_discovery", baseline="1.0.0", candidate="9.9.9"
    )

    assert result is None


async def test_the_report_names_the_levels_it_did_not_evaluate(session_factory):
    """A gate that silently omits half its levels is how Level 4 gets optimised first."""
    report = await run_harness(session_factory)
    markdown = render_markdown(report)

    assert "**PASS**" in markdown
    assert "Level 3 — Predictive utility" in markdown
    assert "Level 4 — Investment outcome" in markdown
    assert "Faults stopped: **100%**" in markdown
