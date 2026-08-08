"""The grounded research assistant (issue #33; ui_concept §4, §22; PRD §18).

Chat is an interface, not the product (§2.5). So this agent cannot produce an
answer — its output schema has no field for one. It emits a *plan*: which stored
read would answer the question. Code runs the plan, and the narration is
assembled from the rows that came back.

That inversion is the whole design. PRD §18 requires answers to cite platform
objects and invent nothing, and no amount of prompting reliably prevents a model
from writing a fluent paragraph about data it was not given. Removing the field
it would write into does.

The consequence worth accepting: the assistant can only answer questions the
domain API already answers. "Why did confidence increase this week?" becomes a
journal read, and the answer is the journal entries. A question the graph does
not hold gets a refusal naming the gap, which §4 is comfortable with — it says
"the LLM should not invent the underlying data".
"""

from __future__ import annotations

from collections.abc import Sequence

from econiq_llm import Agent, EvaluationCheck, Evaluator, ModelTier
from econiq_schemas import AgentInput, AgentOutput, AssistantInput, AssistantOutput

from econiq_agents.prompts import RESEARCH_ASSISTANT_V1

#: Reads the assistant may plan. A closed set, because an open one becomes a
#: path the model constructs, and a constructed path is an injection surface.
RESOURCES: frozenset[str] = frozenset(
    {
        "discover",
        "processes",
        "process_detail",
        "timeline",
        "journal",
        "alerts",
        "capabilities",
        "confluence",
        "assets",
        "comparison",
        "counterfactuals",
        "evidence",
    }
)

OPERATORS: frozenset[str] = frozenset({"eq", "in", "gte", "lte"})

#: Reads that describe one node. Planning one without a subject would return the
#: whole table and read as an answer about everything.
NEEDS_SUBJECT: frozenset[str] = frozenset(
    {"process_detail", "timeline", "counterfactuals", "evidence", "comparison"}
)


class PlanEvaluator:
    """The plan must name a resource that exists and can actually be run.

    Blocking. A plan is executed verbatim, so an unknown resource is either a
    hallucinated endpoint or an attempt to reach one that was not offered, and
    both should fail before anything is fetched.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, AssistantOutput) or not isinstance(payload, AssistantInput):
            return ()
        plan = output.plan
        if plan is None:
            return (
                EvaluationCheck(
                    name="refusal_names_the_gap",
                    passed=bool(output.unsupported_reason),
                    detail="a refusal says what the graph does not hold",
                ),
            )

        problems: list[str] = []
        if plan.resource not in RESOURCES:
            problems.append(f"unknown resource {plan.resource!r}")
        bad_operators = [f.operator for f in plan.filters if f.operator not in OPERATORS]
        if bad_operators:
            problems.append(f"unsupported operators {bad_operators}")
        if plan.resource in NEEDS_SUBJECT and not (plan.subject_id or payload.subject_id):
            problems.append(f"{plan.resource} describes one node but no subject was given")

        return (
            EvaluationCheck(
                name="plan_is_runnable",
                passed=not problems,
                detail="; ".join(problems) if problems else f"plans a {plan.resource} read",
            ),
        )


class ScopeEvaluator:
    """No forecasting, no advice.

    Advisory rather than blocking: the check reads the question, and a question
    containing "should" is not necessarily a request for advice. What matters is
    that the plan returns recorded rows, which the schema already guarantees —
    this exists so the pattern is visible in the run record when it happens.
    """

    _OUT_OF_SCOPE = ("should i", "will it", "price target", "forecast", "predict")

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(payload, AssistantInput):
            return ()
        question = payload.question.lower()
        hits = [phrase for phrase in self._OUT_OF_SCOPE if phrase in question]
        return (
            EvaluationCheck(
                name="question_is_about_the_record",
                passed=not hits,
                detail=(
                    "asks about what is recorded"
                    if not hits
                    else f"asks for a forecast or advice: {hits}"
                ),
                blocking=False,
            ),
        )


class ResearchAssistantAgent(Agent[AssistantInput, AssistantOutput]):
    """Turns a question into a read. Never into an answer."""

    name = "research_assistant"
    version = "1.0.0"
    ontology_layer = "Query"
    tier = ModelTier.FAST

    input_schema = AssistantInput
    output_schema = AssistantOutput
    prompt = RESEARCH_ASSISTANT_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (PlanEvaluator(), ScopeEvaluator())

    def build_user_content(self, payload: AssistantInput) -> str:
        lines = [f"Question: {payload.question}", "", f"Asked from: {payload.page}"]
        if payload.subject_id:
            lines.append(f"Currently viewing: {payload.subject_label or payload.subject_id}")
            lines.append(f"  id: {payload.subject_id}")
        lines += ["", "Resources available:"]
        lines += [f"- {name}" for name in sorted(payload.available_resources or RESOURCES)]
        return "\n".join(lines)
