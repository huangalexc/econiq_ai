"""The Agent abstraction: typed I/O, provenance, and deterministic checks."""

import json
from datetime import UTC, datetime

import pytest
from econiq_llm import (
    Agent,
    LLMService,
    ModelTier,
    PromptTemplate,
    ScriptedProvider,
)
from econiq_ontology import ProcessArchetype
from econiq_ontology import ProcessStateLabel as S
from econiq_schemas import ProcessStateInput, ProcessStateOutput, ProcessSummary

NOW = datetime(2026, 8, 6, tzinfo=UTC)

PROMPT = PromptTemplate(
    name="process_state",
    version="1.0.0",
    template="Estimate the current State of this Process.",
)


class ProcessStateAgent(Agent[ProcessStateInput, ProcessStateOutput]):
    name = "process_state"
    version = "1.0.0"
    ontology_layer = "Process → Process State"
    tier = ModelTier.REASONING
    input_schema = ProcessStateInput
    output_schema = ProcessStateOutput
    prompt = PROMPT

    def build_user_content(self, payload: ProcessStateInput) -> str:
        return payload.model_dump_json(indent=2)


def _payload(**kw):
    defaults = dict(
        as_of=NOW,
        process=ProcessSummary(
            process_id="proc_ai_infrastructure",
            name="AI infrastructure expansion",
            description="…",
            archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
        ),
        archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
        permitted_states=[S.ACCELERATION, S.INFRASTRUCTURE_EXPANSION],
        claim_texts={"claim_1842": "Microsoft raised capex guidance."},
    )
    return ProcessStateInput(**{**defaults, **kw})


def _response(**kw):
    body = {
        "archetype": "infrastructure_s_curve",
        "categorical_state": "acceleration",
        "state_confidence": 0.82,
        "features": [{"name": "capex_acceleration", "value": 8.7, "rationale": "…"}],
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
    return json.dumps({**body, **kw})


def _agent(*responses):
    service = LLMService(ScriptedProvider(responses), observers=[])
    return ProcessStateAgent(service), service


async def test_run_returns_typed_output_with_full_attribution():
    agent = _agent(_response())[0]
    result = await agent.run(_payload())

    assert result.output.categorical_state is S.ACCELERATION
    attribution = result.attribution
    assert attribution.agent_name == "process_state"
    assert attribution.agent_version == "1.0.0"
    assert attribution.prompt_version == PROMPT.qualified_version
    assert attribution.model.startswith("scripted:")
    assert attribution.input_object_versions == {"input": "1.0.0"}
    assert attribution.output_schema_version == "1.0.0"


async def test_the_reasoning_tier_selects_the_configured_model():
    agent, service = _agent(_response())
    assert agent.model == service.settings.reasoning_model


async def test_shared_epistemic_rules_reach_every_prompt():
    agent, service = _agent(_response())
    await agent.run(_payload())
    system = service.provider.requests[0].system
    assert "Confidence values are your belief" in system
    assert "Do not compute figures" in system


async def test_a_fabricated_citation_fails_the_deterministic_check():
    """The most damaging failure an evidence-based system can have."""
    agent = _agent(_response(supporting_claim_ids=["claim_9999"]))[0]
    result = await agent.run(_payload())

    assert not result.evaluation.passed
    failure = result.evaluation.failures[0]
    assert failure.name == "citations_resolve"
    assert "claim_9999" in (failure.detail or "")


async def test_real_citations_pass():
    agent = _agent(_response())[0]
    result = await agent.run(_payload())
    assert result.evaluation.passed


async def test_the_wrong_input_type_is_refused_before_a_call_is_made():
    agent, service = _agent(_response())
    with pytest.raises(TypeError, match="expects ProcessStateInput"):
        await agent.run("just a string")  # type: ignore[arg-type]
    assert service.provider.requests == []
