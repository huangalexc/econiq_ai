"""The validation-and-repair loop: the boundary that protects the ontology."""

import json

import pytest
from econiq_llm import (
    CollectingObserver,
    LLMService,
    OutputValidationError,
    ScriptedProvider,
    TokenUsage,
    estimate_cost_usd,
)
from econiq_ontology import ProcessArchetype
from econiq_ontology import ProcessStateLabel as S
from econiq_schemas import ProcessStateOutput

VALID = {
    "archetype": "infrastructure_s_curve",
    "categorical_state": "acceleration",
    "state_confidence": 0.82,
    "features": [],
    "transition_beliefs": {"infrastructure_expansion": 0.4},
    "transition_indicators": [],
    "reversal_indicators": [],
    "supporting_claim_ids": ["claim_1842"],
    "contradicting_claim_ids": [],
    "evidence": [],
    "abstained": False,
    "abstention_reason": None,
    "uncertainty_notes": [],
    "schema_version": "1.0.0",
}


def _service(*responses):
    observer = CollectingObserver()
    provider = ScriptedProvider(responses)
    return LLMService(provider, observers=[observer]), provider, observer


async def _run(service, **kw):
    return await service.structured(
        output_model=ProcessStateOutput,
        system="…",
        user_content="…",
        model="claude-opus-5",
        agent_name="process_state",
        agent_version="1.0.0",
        prompt_version="process_state@1.0.0+abc",
        **kw,
    )


async def test_valid_output_is_returned_and_accounted_for():
    service, _, observer = _service(json.dumps(VALID))
    call = await _run(service)
    assert call.value.categorical_state is S.ACCELERATION
    assert call.value.archetype is ProcessArchetype.INFRASTRUCTURE_S_CURVE
    assert call.attempts == 1
    assert observer.calls[0].ok


async def test_json_wrapped_in_a_code_fence_is_recovered():
    service, _, _ = _service(f"Here you go:\n```json\n{json.dumps(VALID)}\n```")
    call = await _run(service)
    assert call.attempts == 1


async def test_an_invalid_state_transition_is_repaired_not_accepted():
    """An illegal transition must never reach the database — the service shows
    the model the error and asks for a correction."""
    broken = {**VALID, "transition_beliefs": {"discovery": 0.9}}
    service, provider, observer = _service(json.dumps(broken), json.dumps(VALID))
    call = await _run(service)

    assert call.attempts == 2
    assert [c.ok for c in observer.calls] == [False, True]
    repair_turn = provider.requests[1].messages[-1].content
    assert "did not satisfy the required schema" in repair_turn
    assert "cannot transition" in repair_turn


async def test_a_hallucinated_field_is_rejected_by_extra_forbid():
    hallucinated = {**VALID, "price_target": 42}
    service, _, _ = _service(json.dumps(hallucinated), json.dumps(VALID))
    call = await _run(service)
    assert call.attempts == 2


async def test_persistent_invalidity_fails_loudly_rather_than_half_validating():
    bad = json.dumps({"archetype": "infrastructure_s_curve"})
    service, _, observer = _service(bad, bad, bad)
    with pytest.raises(OutputValidationError) as excinfo:
        await _run(service)
    assert excinfo.value.attempts == 3
    assert all(not c.ok for c in observer.calls)


async def test_non_json_output_is_treated_as_a_validation_failure():
    service, _, _ = _service("I'm not able to answer that.", json.dumps(VALID))
    call = await _run(service)
    assert call.attempts == 2


async def test_recursive_schemas_fall_back_to_an_inline_schema_prompt():
    from econiq_schemas import CapabilityMappingOutput

    payload: dict[str, object] = {
        "capabilities": [],
        "requirement_tree": None,
        "abstained": False,
        "abstention_reason": None,
        "uncertainty_notes": [],
        "schema_version": "1.0.0",
    }
    service, provider, _ = _service(json.dumps(payload))
    await service.structured(
        output_model=CapabilityMappingOutput,
        system="Map this bottleneck.",
        user_content="…",
        model="claude-opus-5",
        agent_name="capability_mapping",
        agent_version="1.0.0",
        prompt_version="capability_mapping@1.0.0+abc",
    )
    request = provider.requests[0]
    assert request.json_schema is None
    assert "JSON Schema" in request.system


def test_cost_is_none_for_unpriced_models_rather_than_zero():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    assert estimate_cost_usd("claude-opus-5", usage) == pytest.approx(5.0)
    assert estimate_cost_usd("claude-haiku-4-5-20251001", usage) == pytest.approx(1.0)
    assert estimate_cost_usd("some-future-model", usage) is None


def test_a_partial_cost_total_is_reported_as_unknown():
    observer = CollectingObserver()
    from econiq_llm import CallRecord

    observer.record(
        CallRecord(
            agent_name="a",
            agent_version="1",
            prompt_version="p",
            provider="x",
            model="claude-opus-5",
            attempt=1,
            usage=TokenUsage(),
            latency_ms=1.0,
            cost_usd=0.5,
            ok=True,
        )
    )
    assert observer.total_cost_usd == pytest.approx(0.5)
    observer.record(
        CallRecord(
            agent_name="a",
            agent_version="1",
            prompt_version="p",
            provider="x",
            model="mystery",
            attempt=1,
            usage=TokenUsage(),
            latency_ms=1.0,
            cost_usd=None,
            ok=True,
        )
    )
    assert observer.total_cost_usd is None
