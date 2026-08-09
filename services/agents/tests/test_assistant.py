"""The grounded research assistant (issue #33; PRD §18)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from econiq_agents.assistant import (
    PlanEvaluator,
    ResearchAssistantAgent,
    ScopeEvaluator,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_schemas import AssistantInput, AssistantOutput

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _plan(**overrides) -> str:
    plan = {
        "resource": "journal",
        "subject_id": None,
        "filters": [],
        "limit": 20,
        "reasoning": "Belief changes are recorded in the journal.",
        "schema_version": "1.0.0",
        **overrides,
    }
    return json.dumps(
        {
            "plan": plan,
            "unsupported_reason": None,
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _refusal(reason: str) -> str:
    return json.dumps(
        {
            "plan": None,
            "unsupported_reason": reason,
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _question(text: str = "Why did confidence increase this week?", **kwargs) -> AssistantInput:
    return AssistantInput(as_of=NOW, question=text, **kwargs)


def test_the_output_has_no_field_to_answer_in():
    """§2.5: chat is an interface, not the product. No amount of prompting
    reliably stops a model writing a fluent paragraph about data it was not
    given — removing the field it would write into does."""
    fields = set(AssistantOutput.model_fields)

    assert "answer" not in fields
    assert "response" not in fields
    assert "summary" not in fields
    assert fields >= {"plan", "unsupported_reason"}


def test_a_plan_and_a_refusal_are_mutually_exclusive():
    with pytest.raises(ValueError, match="exactly one"):
        AssistantOutput.model_validate_json(
            json.dumps(
                {
                    "plan": None,
                    "unsupported_reason": None,
                    "abstained": False,
                    "abstention_reason": None,
                    "uncertainty_notes": [],
                    "schema_version": "1.0.0",
                }
            )
        )


def test_an_unknown_resource_is_rejected_before_anything_is_fetched():
    """A plan is executed verbatim, so an invented endpoint is either a
    hallucination or an attempt to reach one that was not offered."""
    output = AssistantOutput.model_validate_json(_plan(resource="admin_users"))

    checks = PlanEvaluator().evaluate(_question(), output)

    assert checks[0].passed is False
    assert checks[0].blocking is True


def test_an_unsupported_operator_is_rejected():
    output = AssistantOutput.model_validate_json(
        _plan(
            filters=[
                {"field": "name", "operator": "regex", "value": ".*", "schema_version": "1.0.0"}
            ]
        )
    )

    assert PlanEvaluator().evaluate(_question(), output)[0].passed is False


def test_a_single_node_read_without_a_subject_is_rejected():
    """It would return the whole table and read as an answer about everything."""
    output = AssistantOutput.model_validate_json(_plan(resource="timeline"))

    checks = PlanEvaluator().evaluate(_question(), output)

    assert checks[0].passed is False
    assert "no subject" in checks[0].detail


def test_the_subject_may_come_from_the_page_rather_than_the_plan():
    """§22 makes the assistant context-aware: on a Process page the subject is
    the Process, and the model should not have to restate it."""
    output = AssistantOutput.model_validate_json(_plan(resource="timeline"))

    checks = PlanEvaluator().evaluate(_question(page="process", subject_id="p1"), output)

    assert checks[0].passed is True


def test_a_refusal_must_name_the_gap():
    """§4: the LLM should not invent the underlying data. An admission is a good
    answer; a plan returning something adjacent is worse, because the reader
    cannot tell from the rows."""
    good = AssistantOutput.model_validate_json(
        _refusal("The graph records no price data, so relative performance is unavailable.")
    )

    assert PlanEvaluator().evaluate(_question(), good)[0].passed is True


def test_a_forecast_question_is_flagged():
    """This system records what is known and how it was learned; it does not
    forecast and it does not advise."""
    output = AssistantOutput.model_validate_json(_plan())

    checks = ScopeEvaluator().evaluate(_question("Should I buy this before the split?"), output)

    assert checks[0].passed is False
    assert checks[0].blocking is False


async def test_the_agent_is_told_where_the_question_was_asked_from():
    agent = ResearchAssistantAgent(LLMService(ScriptedProvider([]), observers=[]))

    content = agent.build_user_content(
        _question(page="process", subject_id="p1", subject_label="Minerals")
    )

    assert "Asked from: process" in content
    assert "Currently viewing: Minerals" in content
    assert "journal" in content


async def test_a_well_formed_plan_passes_end_to_end():
    service = LLMService(ScriptedProvider([_plan()]), observers=[])

    result = await ResearchAssistantAgent(service).run(_question())

    assert result.evaluation.passed
    assert result.output.plan is not None
    assert result.output.plan.resource == "journal"
    assert result.output.plan.reasoning
