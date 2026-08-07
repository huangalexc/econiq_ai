"""The declared pipeline — checked without a database or a model."""

from econiq_orchestration import BY_NAME, PIPELINE, DomainEvent, Stage, StageRegistry, stages_for
from econiq_orchestration.queue import Priority, backoff_for


def test_every_stage_is_reachable_from_an_event():
    """A stage nothing triggers would only ever run from the reconciler."""
    emitted = {event for stage in PIPELINE for event in stage.emits}
    emitted.add(DomainEvent.DOCUMENT_INGESTED)  # emitted by ingestion, outside the pipeline
    for stage in PIPELINE:
        assert set(stage.triggered_by) & emitted, stage.name


def test_the_chain_runs_document_to_asset():
    assert stages_for(DomainEvent.DOCUMENT_INGESTED)[0].name == Stage.EXTRACT_CLAIMS
    assert stages_for(DomainEvent.CLAIMS_EXTRACTED)[0].name == Stage.RESOLVE_EVENTS
    assert stages_for(DomainEvent.EVENT_PROPAGATED)[0].name == Stage.DISCOVER_PROCESSES
    assert stages_for(DomainEvent.CAPABILITY_UPDATED)[0].name == Stage.DISCOVER_ASSETS


def test_only_propagated_events_reach_the_process_layer():
    """The gate of ontology §46, expressed structurally."""
    assert stages_for(DomainEvent.EVENT_CREATED) == ()
    assert stages_for(DomainEvent.EVENT_UPDATED) == ()
    assert [s.name for s in stages_for(DomainEvent.EVENT_PROPAGATED)] == [Stage.DISCOVER_PROCESSES]


def test_state_fans_out_to_critique_and_capabilities():
    triggered = {stage.name for stage in stages_for(DomainEvent.STATE_RECORDED)}
    assert triggered == {Stage.CRITIQUE_PROCESS, Stage.MAP_CAPABILITIES}


def test_event_resolution_is_single_flighted():
    """Two concurrent passes over overlapping Claims would double-count evidence."""
    resolve = BY_NAME[Stage.RESOLVE_EVENTS]
    assert resolve.concurrency == 1
    assert resolve.subject_from_payload is False
    assert resolve.key_for(None) == Stage.RESOLVE_EVENTS


def test_expensive_stages_run_narrow_and_late():
    critique = BY_NAME[Stage.CRITIQUE_PROCESS]
    extract = BY_NAME[Stage.EXTRACT_CLAIMS]
    # The most expensive call in the pipeline, and nothing blocks on it.
    assert critique.concurrency == 1
    assert critique.priority > Priority.DEFAULT
    # Cheap, high-volume, safe to run wide.
    assert extract.concurrency > critique.concurrency
    assert extract.priority == Priority.LIVE


def test_backoff_grows_and_then_holds():
    assert backoff_for(1).total_seconds() == 30
    assert backoff_for(2).total_seconds() == 300
    assert backoff_for(3).total_seconds() == 1800
    assert backoff_for(9) == backoff_for(3)


def test_the_registry_reports_what_is_unwired():
    registry = StageRegistry()
    registry.register(Stage.RESOLVE_EVENTS, lambda _s, _p: [])  # type: ignore[arg-type]
    assert registry.registered == (Stage.RESOLVE_EVENTS,)
    assert Stage.DISCOVER_ASSETS in registry.unregistered


def test_an_unknown_stage_cannot_be_registered():
    import pytest

    with pytest.raises(KeyError, match="unknown stage"):
        StageRegistry().register("buy_things", lambda _s, _p: [])  # type: ignore[arg-type]
