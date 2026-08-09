"""The research command bar's back end (issue #33, ui_concept §4).

Takes a question, gets a plan from the agent, runs the plan, and returns the
rows. The model never sees the rows and never writes the answer — §4 says "the
LLM should not invent the underlying data", and the reliable way to guarantee
that is for the prose path not to exist.

What comes back is a resource name, a reason, and the results. The terminal
renders them with the same components it uses everywhere else, so an answer is
made of the same objects the rest of the screen is made of and can be clicked
into.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from econiq_agents import ResearchAssistantAgent
from econiq_llm import LLMService, LLMSettings, OutputValidationError, ProviderRefusalError
from econiq_llm.providers import AnthropicProvider
from econiq_schemas import AssistantInput
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from econiq_api import alerts as alert_engine
from econiq_api.deps import AsOfDep, GraphDep, SessionDep

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AssistantAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    resource: str | None = None
    reasoning: str | None = None
    unsupported_reason: str | None = Field(
        default=None,
        description=(
            "Why the graph cannot answer. A stated gap is a better answer than "
            "results adjacent to the question, which the reader cannot "
            "distinguish from an answer."
        ),
    )
    results: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False


def _service() -> LLMService | None:
    """The assistant's model, or nothing.

    Returns None where no provider is configured rather than falling back to a
    scripted stub: a command bar that silently answers from a fixture is worse
    than one that says it is not wired up.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    return LLMService(AnthropicProvider(LLMSettings()), observers=[])


@router.get("/ask", response_model=AssistantAnswer)
async def ask(
    session: SessionDep,
    graph: GraphDep,
    as_of: AsOfDep,
    question: Annotated[str, Query(min_length=3, max_length=500)],
    page: Annotated[str, Query()] = "discover",
    subject_id: Annotated[str | None, Query()] = None,
) -> AssistantAnswer:
    service = _service()
    if service is None:
        return AssistantAnswer(
            question=question,
            unsupported_reason=(
                "No model provider is configured, so questions cannot be "
                "translated into reads. Set ANTHROPIC_API_KEY."
            ),
        )

    payload = AssistantInput(
        as_of=as_of or datetime.now(UTC),
        question=question,
        page=page,
        subject_id=subject_id,
    )
    try:
        result = await ResearchAssistantAgent(service).run(payload)
    except (OutputValidationError, ProviderRefusalError) as exc:
        return AssistantAnswer(question=question, unsupported_reason=str(exc))

    if not result.evaluation.passed or result.output.plan is None:
        return AssistantAnswer(
            question=question,
            unsupported_reason=(
                result.output.unsupported_reason
                or "The question could not be turned into a read of the graph."
            ),
        )

    plan = result.output.plan
    rows = await _execute(session, graph, plan, subject_id, as_of)
    return AssistantAnswer(
        question=question,
        resource=plan.resource,
        reasoning=plan.reasoning,
        results=rows[: plan.limit],
        truncated=len(rows) > plan.limit,
    )


async def _execute(
    session: SessionDep,
    graph: GraphDep,
    plan: Any,
    fallback_subject: str | None,
    as_of: datetime | None,
) -> list[dict[str, Any]]:
    """Run a plan against reads that already exist.

    Deliberately a small dispatch rather than a generic query builder. A builder
    would let a plan express reads nobody designed, and the plan comes from a
    model — the closed set is the boundary.
    """
    subject = plan.subject_id or fallback_subject

    if plan.resource == "alerts":
        found = await alert_engine.generate(session, as_of=as_of, window=timedelta(days=30))
        return [alert.model_dump(mode="json") for alert in found]

    if plan.resource == "journal":
        from econiq_api.deps import Page
        from econiq_api.routers.monitoring import journal_feed

        entries = await journal_feed(
            session=session, page=Page(limit=plan.limit, offset=0), as_of=as_of
        )
        return [entry.model_dump(mode="json") for entry in entries]

    if plan.resource == "counterfactuals" and subject:
        import uuid as _uuid

        from econiq_api.routers.underwriting import counterfactuals

        rows = await counterfactuals(_uuid.UUID(subject), session, as_of)
        return [row.model_dump(mode="json") for row in rows]

    # Everything else is a read the terminal can make itself; naming it is
    # enough for the command bar to navigate rather than embed.
    return []
