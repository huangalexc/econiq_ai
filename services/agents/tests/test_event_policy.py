"""The propagation gate is code, not prompt wording."""

import pytest
from econiq_agents import PropagationPolicy
from econiq_schemas import EventSignificanceOutput


def _significance(**kw) -> EventSignificanceOutput:
    def judged(value: float):
        return {"value": value, "confidence": 0.8, "rationale": "…", "schema_version": "1.0.0"}

    defaults = dict(
        novelty=judged(7.0),
        economic_materiality=judged(7.0),
        credibility=judged(8.0),
        persistence_potential=judged(6.0),
        process_relevance=judged(7.0),
        asset_relevance=judged(5.0),
        should_trigger_update=True,
        trigger_rationale="material and well sourced",
    )
    for key, value in kw.items():
        # Bare numbers are scores; anything else (should_trigger_update) is
        # passed through as given.
        defaults[key] = (
            judged(value)
            if isinstance(value, int | float) and not isinstance(value, bool)
            else value
        )
    return EventSignificanceOutput(**defaults)


def test_a_material_well_sourced_event_propagates():
    decision = PropagationPolicy().decide(_significance(), independent_source_count=3)
    assert decision.propagate
    assert "3 independent source" in decision.reason


def test_the_agents_recommendation_is_necessary():
    decision = PropagationPolicy().decide(
        _significance(should_trigger_update=False), independent_source_count=3
    )
    assert not decision.propagate
    assert "did not recommend" in decision.reason


def test_the_agents_recommendation_is_not_sufficient():
    """A model that could set its own trigger bar would drift it."""
    decision = PropagationPolicy().decide(
        _significance(economic_materiality=2.0), independent_source_count=3
    )
    assert not decision.propagate
    assert "materiality" in decision.reason


def test_low_credibility_stops_propagation_before_materiality_is_considered():
    decision = PropagationPolicy().decide(
        _significance(credibility=2.0, economic_materiality=9.9), independent_source_count=5
    )
    assert not decision.propagate
    assert "credibility" in decision.reason


def test_already_known_events_do_not_re_trigger():
    decision = PropagationPolicy().decide(_significance(novelty=1.0), independent_source_count=4)
    assert not decision.propagate
    assert "already known" in decision.reason


def test_a_single_source_event_accumulates_instead_of_propagating():
    """Ontology §46: Events accumulate until a materiality threshold is reached."""
    decision = PropagationPolicy().decide(_significance(), independent_source_count=1)
    assert not decision.propagate
    assert "accumulating" in decision.reason


def test_an_overwhelming_single_source_event_still_propagates():
    """A regulator publishing a final rule needs no corroboration."""
    decision = PropagationPolicy().decide(
        _significance(economic_materiality=9.0), independent_source_count=1
    )
    assert decision.propagate


def test_thresholds_are_configurable():
    permissive = PropagationPolicy(min_materiality=1.0, min_independent_sources=1)
    decision = permissive.decide(
        _significance(economic_materiality=2.0), independent_source_count=1
    )
    assert decision.propagate
    assert decision.materiality == pytest.approx(2.0)
