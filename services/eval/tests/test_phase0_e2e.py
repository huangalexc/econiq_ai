"""Issue #17 — the Phase 0 gate, end to end.

Documents in, an Asset out, then PRD §28 asked of the resulting graph.
"""

from __future__ import annotations

import pytest
from econiq_data_models import Asset, Claim, Document, Event, JournalEntry, Process
from econiq_eval import full_audit, run_fault_injection
from econiq_eval.corpus import CORPUS, PROVIDER_NAME, run_corpus
from econiq_eval.phase0 import STANDING_NOTES, evaluate_phase0, render_markdown
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


@pytest.fixture
async def corpus_run(session_factory):
    return await run_corpus(session_factory)


async def test_the_corpus_becomes_a_connected_graph(corpus_run, session_factory):
    """The chain issue #17 exists to prove: document → Claim → Event → … → Asset."""
    async with session_factory() as session:
        counts = {
            model.__name__: (
                await session.execute(select(func.count()).select_from(model))
            ).scalar_one()
            for model in (Document, Claim, Event, Process, Asset)
        }

    assert counts["Document"] == len(CORPUS)
    assert counts["Claim"] == len(corpus_run.claim_ids) > 0
    assert counts["Event"] == 2
    assert corpus_run.process_id is not None
    assert len(corpus_run.asset_ids) >= 2, "one Asset per Capability is a thematic screen"


async def test_two_reports_of_one_story_count_as_one_independent_source(
    corpus_run, session_factory
):
    """Ontology §47. Syndication must not inflate the evidence behind an Event."""
    async with session_factory() as session:
        event = (
            await session.execute(select(Event).where(Event.event_id == corpus_run.event_ids[0]))
        ).scalar_one()
        documents = (
            await session.execute(
                select(func.count(func.distinct(Claim.document_id)))
                .select_from(Claim)
                .where(Claim.claim_id.in_(corpus_run.claim_ids[:3]))
            )
        ).scalar_one()

    assert documents == 2
    assert event.independent_source_count < documents


async def test_the_follow_up_revises_the_thesis_rather_than_replacing_it(
    corpus_run, session_factory
):
    """New information that weakens a thesis has to leave a trail (PRD §21)."""
    async with session_factory() as session:
        revisions = (
            await session.execute(
                select(func.count())
                .select_from(Process)
                .where(Process.process_id == corpus_run.process_id)
            )
        ).scalar_one()
        journal = (
            (
                await session.execute(
                    select(JournalEntry).where(JournalEntry.subject_id == corpus_run.process_id)
                )
            )
            .scalars()
            .all()
        )

    assert revisions >= 2, "the update should have appended a revision"
    assert journal, "a belief change with no journal entry is an unexplained change"
    assert any("weakened" in str(entry.changes) for entry in journal)


async def test_the_run_leaves_no_integrity_findings(corpus_run, session_factory):
    """A graph built by the real stages must satisfy the audits unaided."""
    audit = await full_audit(session_factory)

    assert audit.clean, [str(finding) for finding in audit.findings]


async def test_the_audits_still_fire_against_the_populated_graph(corpus_run, session_factory):
    """Fault injection on top of real data, not only on an empty database."""
    report = await run_fault_injection(session_factory)

    assert report.clean, [r.fault for r in report.missed]


async def test_phase_zero_is_evaluated_against_prd_section_28(corpus_run, session_factory):
    report = await evaluate_phase0(session_factory, provider=PROVIDER_NAME)

    by_number = {c.number: c for c in report.criteria}
    assert len(by_number) == 11

    # The nine the Phase 0 pipeline is supposed to deliver.
    for number in (1, 2, 3, 4, 5, 6, 8, 9, 10):
        assert by_number[number].met, (
            f"§28.{number} {by_number[number].name}: {by_number[number].detail}"
        )

    # Two are assigned to later phases and are deferred rather than failed.
    assert by_number[7].deferred_to == "Phase 1 (#29, agent doc §8.3-8.4)"
    assert by_number[11].deferred_to is not None
    assert {c.number for c in report.in_scope} == {1, 2, 3, 4, 5, 6, 8, 9, 10}
    assert report.passed


async def test_a_deferred_criterion_still_reports_what_it_measured(corpus_run, session_factory):
    """§28.7 was reassigned to Phase 1 (#73). The check did not stop running.

    A deferral that also stopped measuring would go stale silently: the Asset
    Quant agent could land in Phase 1 and this line would still say nothing.
    `met` stays false because it is false, and only the verdict is suspended.
    """
    report = await evaluate_phase0(session_factory, provider=PROVIDER_NAME)
    criterion = next(c for c in report.criteria if c.number == 7)

    assert criterion.status == "deferred"
    assert criterion.met is False, "the measurement is unchanged by the deferral"
    assert "0 Asset scorecard(s)" in criterion.detail
    # Deferred criteria neither pass nor fail the gate.
    assert criterion not in report.in_scope
    assert report.passed


async def test_the_report_states_what_a_scripted_run_does_not_establish(
    corpus_run, session_factory
):
    """The provider is named in the artefact so nobody reads it as model validation."""
    report = await evaluate_phase0(session_factory, provider=PROVIDER_NAME)
    markdown = render_markdown(report, notes=STANDING_NOTES)

    assert "`scripted` provider" in markdown
    assert "does not establish that the Process is the right one" in markdown
    assert "| 7 |" in markdown
