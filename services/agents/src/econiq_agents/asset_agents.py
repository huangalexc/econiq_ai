"""Asset Discovery and Asset Exposure agents (issue #12, agent doc §8.1–§8.2).

The first point in the system where naming an instrument is permitted — and the
last agent layer of Phase 0. Everything upstream refused to name a security
precisely so that when one is finally named, the chain from document to
instrument is inspectable at every step.

Two things are still withheld from these agents. They do not rank (§8.1 ends
"do not rank Assets yet"; ranking needs quantitative data that arrives in Phase
3), and they do not assert identifiers — an LLM proposes "gold", and code
decides that means XAU.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from econiq_llm import Agent, CitationEvaluator, EvaluationCheck, Evaluator, ModelTier
from econiq_ontology import AssetClass, ProcessArchetype
from econiq_schemas import (
    AgentInput,
    AgentOutput,
    AssetDiscoveryInput,
    AssetDiscoveryOutput,
    AssetExposureInput,
    AssetExposureOutput,
    ExposureMateriality,
)

from econiq_agents.prompts import ASSET_DISCOVERY_V1, ASSET_EXPOSURE_V1
from econiq_agents.reference_universe import NON_EQUITY_CLASSES, lookup

#: Archetypes whose thesis is frequently expressed most cleanly by something
#: other than an equity. Used for an advisory check, not a rule — an equity-only
#: answer can be right, but on these it is worth noticing.
NON_EQUITY_ARCHETYPES = frozenset(
    {
        ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
        ProcessArchetype.INDUSTRIAL_BOTTLENECK,
    }
)


class AssetDiscoveryAgent(Agent[AssetDiscoveryInput, AssetDiscoveryOutput]):
    """Capability → Asset universe (agent doc §8.1)."""

    name = "asset_discovery"
    version = "1.0.0"
    ontology_layer = "Capability → Asset Candidate"
    tier = ModelTier.REASONING

    input_schema = AssetDiscoveryInput
    output_schema = AssetDiscoveryOutput
    prompt = ASSET_DISCOVERY_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (CitationEvaluator(), NoRankingEvaluator(), InstrumentBreadthEvaluator())

    def build_user_content(self, payload: AssetDiscoveryInput) -> str:
        lines = [
            f"Capability: {payload.capability_name}",
            f"  {payload.capability_description}",
        ]
        if payload.process_names:
            lines += ["", "Upstream Processes: " + ", ".join(payload.process_names)]
        if payload.geographic_constraint:
            lines += ["", f"Geographic constraint: {payload.geographic_constraint}"]
        if payload.known_asset_names:
            lines += [
                "",
                "Assets already in the graph (reuse the exact name where you mean one "
                "of these): " + ", ".join(payload.known_asset_names),
            ]
        return "\n".join(lines)


class NoRankingEvaluator:
    """Discovery finds the universe; it does not order it.

    §8.1 ends "Do not rank Assets yet", and the reason is structural: ranking
    without the quantitative data of Phase 3 is ranking on narrative, which is
    exactly the judgement this system defers until it can be checked.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, AssetDiscoveryOutput) or len(output.candidates) < 2:
            return ()
        # A confidence spread wide enough to be an implicit ordering is the
        # observable form of ranking in this schema.
        confidences = [candidate.confidence for candidate in output.candidates]
        spread = max(confidences) - min(confidences)
        strictly_ordered = all(earlier > later for earlier, later in pairwise(confidences))
        ranked = strictly_ordered and spread > 0.3
        return (
            EvaluationCheck(
                name="candidates_are_not_ranked",
                passed=not ranked,
                detail=(
                    None
                    if not ranked
                    else "candidates are ordered by descending confidence — this is a "
                    "ranking, and ranking belongs to a later agent with quantitative data"
                ),
                blocking=False,
            ),
        )


class InstrumentBreadthEvaluator:
    """Notices when a Process was expressed only through equities.

    A commodity shortage is expressed by the commodity more directly than by any
    one producer, whose costs, hedging, jurisdiction and balance sheet all sit
    between the thesis and the outcome. Reaching only for equities because they
    are easier to name is a real blind spot — but an equity-only answer can also
    be correct, so this records rather than refuses.
    """

    def __init__(self, archetype: ProcessArchetype | None = None) -> None:
        self.archetype = archetype

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(output, AssetDiscoveryOutput) or not output.candidates:
            return ()
        classes = {candidate.asset_class for candidate in output.candidates}
        considered_non_equity = bool(classes & NON_EQUITY_CLASSES)
        relevant = self.archetype in NON_EQUITY_ARCHETYPES if self.archetype else False

        checks = [
            EvaluationCheck(
                name="instrument_classes_considered",
                passed=considered_non_equity or not relevant,
                detail=(
                    None
                    if considered_non_equity or not relevant
                    else f"{self.archetype.value if self.archetype else 'this Process'} "
                    "produced only equity expressions; the underlying commodity or "
                    "currency may be the cleaner exposure"
                ),
                blocking=False,
            )
        ]
        unresolvable = sorted(
            {
                candidate.proposed_name
                for candidate in output.candidates
                if candidate.asset_class in (AssetClass.COMMODITY, AssetClass.CURRENCY)
                and lookup(candidate.proposed_ticker) is None
                and lookup(candidate.proposed_name) is None
            }
        )
        checks.append(
            EvaluationCheck(
                name="non_equity_candidates_resolve",
                passed=not unresolvable,
                detail=(
                    None if not unresolvable else f"not in the reference universe: {unresolvable}"
                ),
                blocking=False,
            )
        )
        return tuple(checks)


class AssetExposureAgent(Agent[AssetExposureInput, AssetExposureOutput]):
    """Asset → exposure (agent doc §8.2)."""

    name = "asset_exposure"
    version = "1.0.0"
    ontology_layer = "Asset"
    tier = ModelTier.STANDARD

    input_schema = AssetExposureInput
    output_schema = AssetExposureOutput
    prompt = ASSET_EXPOSURE_V1

    def default_evaluators(self) -> Sequence[Evaluator]:
        return (CitationEvaluator(), QuantitativeBasisEvaluator())

    def build_user_content(self, payload: AssetExposureInput) -> str:
        lines = [
            f"Asset: {payload.asset_name}",
            f"Capability: {payload.capability_name}",
        ]
        if payload.business_description:
            lines += ["", payload.business_description]
        if payload.reported_segment_data:
            lines += ["", "Reported figures:"]
            lines += [
                f"- {name}: {value:,.0f}"
                for name, value in sorted(payload.reported_segment_data.items())
            ]
        if payload.claim_texts:
            lines += ["", "Evidence:"]
            lines += [f"- [{cid}] {text}" for cid, text in payload.claim_texts.items()]
        return "\n".join(lines)


class QuantitativeBasisEvaluator:
    """A revenue share must rest on a figure that was actually supplied.

    The schema already requires a ``quantitative_basis`` string alongside a
    revenue share. This checks the harder half: that the basis refers to
    something in the input rather than a number the model recalled, which is how
    a plausible-looking exposure estimate becomes untraceable.
    """

    def evaluate(self, payload: AgentInput, output: AgentOutput) -> Sequence[EvaluationCheck]:
        if not isinstance(payload, AssetExposureInput) or not isinstance(
            output, AssetExposureOutput
        ):
            return ()
        quantified = [e for e in output.exposures if e.revenue_share is not None]
        if not quantified:
            return ()
        if not payload.reported_segment_data and not payload.claim_texts:
            return (
                EvaluationCheck(
                    name="revenue_share_has_supplied_evidence",
                    passed=False,
                    detail="a revenue share was given but no figures or Claims were supplied",
                ),
            )
        return (EvaluationCheck(name="revenue_share_has_supplied_evidence", passed=True),)


def material_candidates(output: AssetDiscoveryOutput) -> list[int]:
    """Indices of candidates whose exposure the agent called material.

    Incidental exposures are kept as Candidates but are not promoted to Assets:
    a company that touches the Capability somewhere is not an expression of it,
    and letting those into the graph is how an Asset universe becomes a list of
    everything adjacent to a theme.
    """
    return [
        index
        for index, candidate in enumerate(output.candidates)
        if candidate.materiality is ExposureMateriality.MATERIAL
    ]
