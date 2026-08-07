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

    # The eight the pipeline is supposed to deliver.
    for number in (1, 2, 3, 4, 5, 6, 8, 9, 10):
        assert by_number[number].met, (
            f"§28.{number} {by_number[number].name}: {by_number[number].detail}"
        )

    # Criterion 11 is Phase 2 work and is deferred rather than failed.
    assert by_number[11].deferred_to is not None
    assert by_number[11].status == "deferred"


async def test_asset_comparison_is_the_one_criterion_phase_zero_does_not_reach(
    corpus_run, session_factory
):
    """§28.7 needs the Asset Quant and Asset Quality agents (agent doc §8.3-8.4).

    Phase 0's issue list stops at "basic Asset discovery & exposure mapping"
    (#12), so nothing writes an asset_quality scorecard. This is a real gap
    between PRD §28 and phases.txt, and the gate reports it rather than
    quietly redefining the criterion as met.
    """
    report = await evaluate_phase0(session_factory, provider=PROVIDER_NAME)
    criterion = next(c for c in report.criteria if c.number == 7)

    assert criterion.met is False
    assert criterion.deferred_to is None, "not deferred — it is genuinely unmet"
    assert report.passed is False


async def test_the_report_states_what_a_scripted_run_does_not_establish(
    corpus_run, session_factory
):
    """The provider is named in the artefact so nobody reads it as model validation."""
    report = await evaluate_phase0(session_factory, provider=PROVIDER_NAME)
    markdown = render_markdown(report, notes=STANDING_NOTES)

    assert "`scripted` provider" in markdown
    assert "does not establish that the Process is the right one" in markdown
    assert "| 7 |" in markdown
