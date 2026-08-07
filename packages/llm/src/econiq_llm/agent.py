"""The base ``Agent`` abstraction (tech rec §12).

An agent is a narrow, typed, bounded unit: input schema, output schema, system
prompt, model tier, evaluator. Deliberately not a framework — the ontology must
not depend on whichever agent framework is fashionable (tech rec §13), so this
is ordinary Python over ``LLMService`` and the schemas package.

Every run produces an ``AgentAttribution`` recording agent name, agent version,
model, prompt version, timestamp and both schema versions (agent doc §21). That
record travels with the output into the database; it is not reconstructed later.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from econiq_ontology import AgentAttribution, utcnow
from econiq_schemas import AgentInput, AgentOutput

from econiq_llm.config import ModelTier
from econiq_llm.observability import CallRecord
from econiq_llm.prompts import SHARED_AGENT_PREAMBLE, PromptTemplate
from econiq_llm.service import LLMService
from econiq_llm.types import TokenUsage


@dataclass(frozen=True, slots=True)
class EvaluationCheck:
    """One deterministic assertion about an agent's output.

    Checks are code, not LLM judgement: "did every cited claim id appear in the
    input" is decidable, so it is decided (agent doc §2.3).
    """

    name: str
    passed: bool
    detail: str | None = None
    blocking: bool = True
    """Whether failing this check should stop the output being persisted.

    Some findings are worth recording without refusing the work — "this
    Commodity Supply Cycle considered no direct commodity exposure" is a real
    quality signal, but discarding the equities the agent did find would leave
    the graph emptier rather than better.
    """


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    checks: tuple[EvaluationCheck, ...] = ()

    @property
    def passed(self) -> bool:
        """Whether the output may be persisted. Advisories do not block."""
        return all(check.passed for check in self.checks if check.blocking)

    @property
    def failures(self) -> tuple[EvaluationCheck, ...]:
        """Blocking checks that failed."""
        return tuple(check for check in self.checks if not check.passed and check.blocking)

    @property
    def advisories(self) -> tuple[EvaluationCheck, ...]:
        """Non-blocking findings — recorded, surfaced, but not refused."""
        return tuple(check for check in self.checks if not check.passed and not check.blocking)


class Evaluator(Protocol):
    """Deterministic post-conditions on an agent's output."""

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]: ...


class CitationEvaluator:
    """Every cited Claim id must be one the agent was actually shown.

    This catches the most damaging failure an evidence-based system can have: a
    fabricated citation. It is checkable, so it is checked at the boundary
    rather than trusted (agent doc §2.4).
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        available = _available_claim_ids(payload)
        if not available:
            return ()
        cited = _cited_claim_ids(output)
        invented = cited - available
        return (
            EvaluationCheck(
                name="citations_resolve",
                passed=not invented,
                detail=None if not invented else f"claim ids not in input: {sorted(invented)}",
            ),
        )


@dataclass(slots=True)
class AgentRunResult[TOut: AgentOutput]:
    """Everything the orchestrator needs to persist one agent run."""

    output: TOut
    attribution: AgentAttribution
    calls: list[CallRecord] = field(default_factory=list)
    evaluation: EvaluationReport = field(default_factory=EvaluationReport)

    @property
    def usage(self) -> TokenUsage:
        total = TokenUsage()
        for call in self.calls:
            total = total + call.usage
        return total

    @property
    def cost_usd(self) -> float | None:
        if any(call.cost_usd is None for call in self.calls):
            return None
        return sum(call.cost_usd or 0.0 for call in self.calls)


class Agent[TIn: AgentInput, TOut: AgentOutput](ABC):
    """Base class for every agent in the system.

    Subclasses declare their contract as class attributes and, at minimum,
    implement :meth:`build_user_content`. The default implementation serializes
    the typed input — agents receive structured state, not prose.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    ontology_layer: ClassVar[str]
    tier: ClassVar[ModelTier] = ModelTier.STANDARD
    effort: ClassVar[str | None] = None
    #: Tools this agent may call. Phase 0 agents are single-shot and declare
    #: none; the field is part of the contract from the start (tech rec §12).
    tools: ClassVar[tuple[str, ...]] = ()

    input_schema: type[TIn]
    output_schema: type[TOut]
    prompt: PromptTemplate

    def __init__(
        self,
        service: LLMService,
        *,
        evaluators: Sequence[Evaluator] | None = None,
        model: str | None = None,
    ) -> None:
        self.service = service
        self.model = model or service.model_for(self.tier)
        self.evaluators: tuple[Evaluator, ...] = tuple(
            evaluators if evaluators is not None else self.default_evaluators()
        )

    def default_evaluators(self) -> Sequence[Evaluator]:
        """Checks that run unless the caller supplies its own.

        Citation resolution is the universal one — every agent that cites is
        checked for fabricated ids. Agents with a stronger check available
        override this.
        """
        return (CitationEvaluator(),)

    @abstractmethod
    def build_user_content(self, payload: TIn) -> str:
        """Render the typed input into the user turn."""

    def system_prompt(self, payload: TIn) -> str:
        """The rendered system prompt, with the shared epistemic rules appended."""
        return f"{self.prompt.render()}\n\n{SHARED_AGENT_PREAMBLE}"

    async def run(self, payload: TIn) -> AgentRunResult[TOut]:
        if not isinstance(payload, self.input_schema):
            raise TypeError(
                f"{self.name} expects {self.input_schema.__name__}, got {type(payload).__name__}"
            )

        call = await self.service.structured(
            output_model=self.output_schema,
            system=self.system_prompt(payload),
            user_content=self.build_user_content(payload),
            model=self.model,
            agent_name=self.name,
            agent_version=self.version,
            prompt_version=self.prompt.qualified_version,
            effort=self.effort,
            metadata={"agent": self.name, "layer": self.ontology_layer},
        )

        attribution = AgentAttribution(
            agent_name=self.name,
            agent_version=self.version,
            model=f"{self.service.provider.name}:{call.model}",
            prompt_version=self.prompt.qualified_version,
            timestamp=utcnow(),
            input_object_versions={"input": payload.schema_version},
            output_schema_version=call.value.schema_version,
        )

        checks: list[EvaluationCheck] = []
        for evaluator in self.evaluators:
            checks.extend(evaluator.evaluate(payload, call.value))

        return AgentRunResult(
            output=call.value,
            attribution=attribution,
            calls=call.calls,
            evaluation=EvaluationReport(tuple(checks)),
        )


def _available_claim_ids(payload: AgentInput) -> set[str]:
    """Claim ids visible in an agent input, wherever the schema puts them."""
    found: set[str] = set()
    data = payload.model_dump()
    for key, value in data.items():
        if key == "claim_texts" and isinstance(value, dict):
            found |= {str(k) for k in value}
        elif key in ("claims", "supporting_claim_ids") and isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and "claim_id" in item:
                    found.add(str(item["claim_id"]))
                elif isinstance(item, str):
                    found.add(item)
        elif isinstance(value, dict) and "supporting_claim_ids" in value:
            found |= {str(cid) for cid in value["supporting_claim_ids"]}
    return found


def _cited_claim_ids(output: AgentOutput) -> set[str]:
    """Every ``supporting_claim_ids`` / ``contradicting_claim_ids`` in the tree."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("supporting_claim_ids", "contradicting_claim_ids") and isinstance(
                    value, list
                ):
                    found.update(str(v) for v in value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(output.model_dump())
    return found


def is_concrete_agent(obj: object) -> bool:
    """Whether ``obj`` is an instantiable ``Agent`` subclass. Used by the registry."""
    return (
        inspect.isclass(obj)
        and issubclass(obj, Agent)
        and not inspect.isabstract(obj)
        and hasattr(obj, "name")
    )
