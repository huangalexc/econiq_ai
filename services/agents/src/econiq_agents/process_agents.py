"""Process Discovery and Process Update agents (issue #8, agent doc §6.1–§6.2).

The heart of Phase 0: Events stop being a stream and start accumulating into
persistent Processes.

The boundary these two agents must not cross is the Asset layer. "Do not
identify stocks yet" is not stylistic advice — the whole reason the ontology has
a Bottleneck and a Capability layer is that jumping from an Event to a ticker is
the failure mode this system exists to avoid. ``LayerBoundaryEvaluator`` checks
it mechanically.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from econiq_llm import Agent, EvaluationCheck, Evaluator, ModelTier
from econiq_schemas import (
    AgentInput,
    AgentOutput,
    ProcessDiscoveryInput,
    ProcessDiscoveryOutput,
    ProcessUpdateInput,
    ProcessUpdateOutput,
)

from econiq_agents.prompts import PROCESS_DISCOVERY_V1, PROCESS_UPDATE_V1

#: Bare tickers ("$MP", "NYSE: MP") and the vocabulary of a security
#: recommendation. Deliberately narrow: the check should fire on an agent that
#: crossed into the Asset layer, not on ordinary economic prose.
_TICKER = re.compile(r"(?:\$[A-Z]{1,5}\b|\b(?:NYSE|NASDAQ|LSE|TSX|ASX)\s*:\s*[A-Z.]{1,6}\b)")
_ASSET_VOCABULARY = re.compile(
    # "long" and "short" are excluded on their own: "long lead times" and
    # "short supply" are ordinary industrial economics, and a check that fires
    # on them is noise rather than a guardrail.
    r"\b(?:share price|shares? of|stock price|price target|market cap|"
    r"buy|sell|overweight|underweight|long position|short position|"
    r"going long|valuation multiple)\b",
    re.IGNORECASE,
)


class LayerBoundaryEvaluator:
    """Flags output that reaches past the agent's ontology layer.

    A heuristic, and honest about it: it catches the obvious crossings — a
    ticker, a price target, a recommendation — and will not catch a subtly
    asset-flavoured argument. That is still worth having, because the obvious
    crossings are the ones that reach a user and destroy trust.
    """

    def __init__(self, *, layer: str) -> None:
        self.layer = layer

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        text = _prose_of(output)
        tickers = sorted(set(_TICKER.findall(text)))
        vocabulary = sorted({match.lower() for match in _ASSET_VOCABULARY.findall(text)})
        return (
            EvaluationCheck(
                name="no_asset_identifiers",
                passed=not tickers,
                detail=None
                if not tickers
                else f"tickers named at the {self.layer} layer: {tickers}",
            ),
            EvaluationCheck(
                name="no_investment_language",
                passed=not vocabulary,
                detail=(
                    None
                    if not vocabulary
                    else f"asset vocabulary at the {self.layer} layer: {vocabulary}"
                ),
            ),
        )


def _prose_of(output: AgentOutput) -> str:
    """Every free-text field in an output, concatenated.

    Walks the dump rather than naming fields, so a new prose field added to a
    schema is covered without anyone remembering to update this.
    """
    collected: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            collected.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(output.model_dump(mode="json"))
    return "\n".join(collected)


class ProcessDiscoveryAgent(Agent[ProcessDiscoveryInput, ProcessDiscoveryOutput]):
    """Event → Process (agent doc §6.1).

    Reasoning tier, and the most consequential agent in Phase 0: a spurious
    Process contaminates everything downstream of it, and a missed one means the
    development is invisible no matter how good the later layers are.
    """

    name = "process_discovery"
    version = "1.0.0"
    ontology_layer = "Event → Process"
    tier = ModelTier.REASONING

    input_schema = ProcessDiscoveryInput
    output_schema = ProcessDiscoveryOutput
    prompt = PROCESS_DISCOVERY_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        from econiq_llm import CitationEvaluator

        return (CitationEvaluator(), LayerBoundaryEvaluator(layer="Process"))

    def build_user_content(self, payload: ProcessDiscoveryInput) -> str:
        lines = [
            "Event:",
            f"  {payload.event.title}",
            f"  {payload.event.description}",
            f"  occurred {payload.event.timestamp.date().isoformat()}, "
            f"materiality {payload.event.materiality:.1f}, "
            f"novelty {payload.event.novelty:.1f}",
        ]
        if payload.claim_texts:
            lines += ["", "Supporting Claims:"]
            lines += [f"- [{cid}] {text}" for cid, text in payload.claim_texts.items()]
        lines += ["", "Existing Processes:"]
        if payload.existing_processes:
            for process in payload.existing_processes:
                state = process.current_state.value if process.current_state else "no state yet"
                archetype = process.archetype.value if process.archetype else "unclassified"
                lines.append(
                    f"- [{process.process_id}] {process.name} ({archetype}, {state})\n"
                    f"    {process.description}"
                )
        else:
            lines.append("(none — the graph is empty)")
        return "\n".join(lines)


class ProcessUpdateAgent(Agent[ProcessUpdateInput, ProcessUpdateOutput]):
    """Applies an evidenced delta to a Process (agent doc §6.2)."""

    name = "process_update"
    version = "1.0.0"
    ontology_layer = "Event → Process"
    tier = ModelTier.REASONING

    input_schema = ProcessUpdateInput
    output_schema = ProcessUpdateOutput
    prompt = PROCESS_UPDATE_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        from econiq_llm import CitationEvaluator

        return (CitationEvaluator(), LayerBoundaryEvaluator(layer="Process"))

    def build_user_content(self, payload: ProcessUpdateInput) -> str:
        process = payload.process
        confidence = (
            f"{process.state_confidence:.2f}" if process.state_confidence is not None else "unknown"
        )
        lines = [
            f"Process: {process.name}",
            f"  {process.description}",
            f"  archetype: {process.archetype.value if process.archetype else 'unclassified'}",
            f"  current State: {process.current_state.value if process.current_state else 'none'}"
            f" (confidence {confidence})",
        ]
        if payload.current_features:
            lines += ["", "Current State features:"]
            lines += [
                f"- {name}: {value:.2f}" for name, value in sorted(payload.current_features.items())
            ]
        if payload.open_bottleneck_names:
            lines += ["", "Open Bottlenecks: " + ", ".join(payload.open_bottleneck_names)]
        lines += [
            "",
            "New Event:",
            f"  {payload.event.title}",
            f"  {payload.event.description}",
            f"  occurred {payload.event.timestamp.date().isoformat()}",
        ]
        if payload.claim_texts:
            lines += ["", "Supporting Claims:"]
            lines += [f"- [{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)
