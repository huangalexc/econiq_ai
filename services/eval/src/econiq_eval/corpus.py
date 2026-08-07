"""The Phase 0 validation corpus and the run that drives it (issue #17).

**The documents here are synthetic.** They are written for this test suite. They
describe real economic situations — rare-earth separation capacity, grid
interconnection for datacentre load — because a corpus of invented industries
would not exercise the ontology, but the articles themselves were not published
anywhere and the publisher names are fictional. Nothing here should be quoted as
reporting.

**The model responses are scripted.** ``ScriptedProvider`` returns fixed JSON,
so the run is deterministic, free, and runnable in CI without an API key. The
consequence is stated plainly in the report this produces: the run validates the
*pipeline* — that documents become Claims become Events become a Process with a
State, Bottlenecks, Capabilities and Assets, all connected and provenanced — and
says nothing about whether the agents would produce those answers unprompted.
Model accuracy is what the labelled benchmarks in :mod:`econiq_eval.graders`
measure, and they need a real provider.

The corpus is built to exercise the parts of the chain that are easy to fake:

* Two publishers carry the same story, so Event resolution has to collapse them
  and count one independent source rather than two (ontology §47).
* A second document arrives later with new information, so the Process gains a
  revision and a journal entry rather than being rewritten.
* One Capability is expressed by two different instrument types — an equity and
  the commodity itself — because a single Asset per Capability is what a
  thematic screen already produces.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from econiq_agents import (
    AssetDiscoveryStage,
    CapabilityStage,
    DocumentExtractionStage,
    EventResolutionStage,
    ProcessCritiqueStage,
    ProcessDiscoveryStage,
    ProcessStateStage,
)
from econiq_ingestion import IngestionPipeline, InMemoryObjectStore, RawDocument
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import DocumentType
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROVIDER_NAME = "scripted"

T0 = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    source: str
    publisher: str
    title: str
    body: str
    published_at: datetime

    def raw(self) -> RawDocument:
        return RawDocument(
            source=self.source,
            title=self.title,
            content=self.body.encode(),
            content_type="text/plain",
            publication_time=self.published_at,
            retrieved_at=self.published_at + timedelta(minutes=3),
            publisher=self.publisher,
            document_type=DocumentType.NEWS_ARTICLE,
        )


# --------------------------------------------------------------------------- #
# The corpus. Synthetic text, fictional publishers, real subject matter.
# --------------------------------------------------------------------------- #

WIRE_A = CorpusDocument(
    source="corpus-wire-a",
    publisher="Meridian Wire",
    title="Defense department takes equity stake in rare-earth processor",
    body=(
        "STRATEGIC MINERALS\n\n"
        "The defense department acquired a 15 percent equity position in a domestic "
        "rare-earth processor on Monday, alongside a price floor agreement.\n\n"
        "Separation capacity outside China remains under 10 percent of global supply, "
        "according to industry figures cited in the filing.\n"
    ),
    published_at=T0,
)

#: A syndicated copy: a second outlet running the first outlet's wire text under
#: its own headline and section furniture. This is what syndication actually
#: looks like, and it is why independence is decided on shingle overlap rather
#: than on the publisher byline — two names, one report. The Event must end up
#: with one independent source, not two (ontology §47).
WIRE_B = CorpusDocument(
    source="corpus-wire-b",
    publisher="Halbrook Report",
    title="Pentagon buys into rare-earth producer under price floor deal",
    body=(
        "MINERALS DESK\n\n"
        "The defense department acquired a 15 percent equity position in a domestic "
        "rare-earth processor on Monday, alongside a price floor agreement.\n\n"
        "Separation capacity outside China remains under 10 percent of global supply, "
        "according to industry figures cited in the filing.\n"
    ),
    published_at=T0 + timedelta(hours=4),
)

#: New information three weeks later — the Process should gain a revision and a
#: journal entry, not be overwritten.
FOLLOW_UP = CorpusDocument(
    source="corpus-trade-press",
    publisher="Separation Quarterly",
    title="Second separation train slips to 2028 on permitting",
    body=(
        "PROJECT UPDATE\n\n"
        "Commissioning of the second heavy separation train has slipped to 2028, the "
        "operator said, citing permitting timelines for the effluent treatment works.\n\n"
        "Heavy rare-earth separation capacity outside China is unchanged year on year.\n"
    ),
    published_at=T0 + timedelta(days=21),
)

CORPUS: tuple[CorpusDocument, ...] = (WIRE_A, WIRE_B, FOLLOW_UP)


# --------------------------------------------------------------------------- #
# Scripted responses, in the order each stage consumes them.
# --------------------------------------------------------------------------- #


def _envelope(**payload: object) -> str:
    return json.dumps(
        payload
        | {
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _classification(*entities: str) -> str:
    return _envelope(
        document_type="news_article",
        source_type="wire_service",
        primary_information_mode="textual",
        named_entities=[
            {
                "text": name,
                "kind": "company",
                "resolved_id": None,
                "schema_version": "1.0.0",
            }
            for name in entities
        ],
        likely_event_types=["government_funding"],
        extraction_strategy="textual claim extraction",
        confidence=0.9,
    )


def _claim(
    text: str,
    quote: str,
    *,
    section: str,
    assertion: str = "observed_fact",
) -> dict[str, object]:
    return {
        "text": text,
        "assertion_source": assertion,
        "source_location": {
            "quote": quote,
            "section": section,
            "page": None,
            "paragraph": None,
            "char_start": None,
            "char_end": None,
            "schema_version": "1.0.0",
        },
        "extraction_confidence": 0.93,
        "entities": [],
        "stated_at": None,
        "attributed_to": None,
        "schema_version": "1.0.0",
    }


def _extraction(*claims: dict[str, object]) -> str:
    return _envelope(claims=list(claims))


EXTRACTION_SCRIPT: tuple[tuple[str, ...], ...] = (
    (
        _classification("rare-earth processor"),
        _extraction(
            _claim(
                "The defense department acquired a 15 percent equity position in a "
                "domestic rare-earth processor.",
                "acquired a 15 percent equity position in a domestic",
                section="STRATEGIC MINERALS",
            ),
            _claim(
                "Separation capacity outside China is under 10 percent of global supply.",
                "Separation capacity outside China remains under 10 percent of global supply",
                section="STRATEGIC MINERALS",
            ),
        ),
    ),
    (
        _classification("rare-earth processor"),
        _extraction(
            _claim(
                "The defense department acquired a 15 percent equity position in a "
                "domestic rare-earth processor.",
                "acquired a 15 percent equity position in a domestic",
                section="MINERALS DESK",
            ),
        ),
    ),
    (
        _classification("operator"),
        _extraction(
            _claim(
                "The second heavy separation train has slipped to 2028.",
                "second heavy separation train has slipped to 2028",
                section="PROJECT UPDATE",
            ),
        ),
    ),
)


def _cluster(
    claim_ids: Sequence[uuid.UUID],
    *,
    title: str,
    description: str,
    publishers: Sequence[str],
    occurred_at: datetime,
    event_type: str = "government_funding",
) -> dict[str, object]:
    return {
        "canonical_title": title,
        "description": description,
        "event_type": event_type,
        "timestamp": occurred_at.isoformat(),
        "supporting_claim_ids": [str(c) for c in claim_ids],
        "distinct_publishers": list(publishers),
        "contradictions": [],
        "entities": [],
        "confidence": 0.9,
        "merge_into_event_id": None,
        "schema_version": "1.0.0",
    }


def _resolution(*clusters: dict[str, object]) -> str:
    return _envelope(events=list(clusters), unassigned_claim_ids=[])


def _significance(*, materiality: float = 8.2, novelty: float = 7.8) -> str:
    def judged(value: float) -> dict[str, object]:
        return {
            "value": value,
            "confidence": 0.82,
            "rationale": "…",
            "schema_version": "1.0.0",
        }

    return _envelope(
        novelty=judged(novelty),
        economic_materiality=judged(materiality),
        credibility=judged(8.4),
        persistence_potential=judged(7.6),
        process_relevance=judged(8.5),
        asset_relevance=judged(7.0),
        should_trigger_update=True,
        trigger_rationale="material, corroborated and process-relevant",
    )


PROCESS_NAME = "Domestic strategic-mineral security"
PROCESS_SLUG = "domestic-strategic-mineral-security"


def _discovery(claim_ids: Sequence[uuid.UUID]) -> str:
    return _envelope(
        new_processes=[
            {
                "name": PROCESS_NAME,
                "slug": PROCESS_SLUG,
                "description": (
                    "The state is underwriting domestic rare-earth separation capacity "
                    "with equity and a price floor."
                ),
                "suggested_archetype": None,
                "causal_mechanism": (
                    "Public equity and a floor price lower the cost of capital for "
                    "capacity that would not clear on spot economics."
                ),
                "confidence": 0.86,
                "supporting_claim_ids": [str(c) for c in claim_ids],
                "contradicting_claim_ids": [],
                "evidence": [],
                "schema_version": "1.0.0",
            }
        ],
        affected_processes=[],
        unaffected_process_ids=[],
    )


def _update(process_id: uuid.UUID, claim_ids: Sequence[uuid.UUID]) -> str:
    """The follow-up document weakens the thesis. It must not be discarded."""
    return _envelope(
        new_processes=[],
        affected_processes=[
            {
                "process_id": str(process_id),
                "implication": "materially_changes",
                "causal_mechanism": "Permitting extends the lead time on effluent treatment.",
                "direction": "weakens the Process",
                "confidence": 0.78,
                "supporting_claim_ids": [str(c) for c in claim_ids],
                "contradicting_claim_ids": [],
                "evidence": [],
                "schema_version": "1.0.0",
            }
        ],
        unaffected_process_ids=[],
    )


def _belief_update(claim_ids: Sequence[uuid.UUID]) -> str:
    """The follow-up weakens the thesis. A journal entry has to record that."""
    return _envelope(
        belief_changes=[
            {
                "direction": "weakened",
                "statement": "Capacity arrives on the original schedule.",
                "rationale": "The second train slipped a year on permitting.",
                "schema_version": "1.0.0",
            }
        ],
        feature_deltas=[
            {
                "name": "supply_tightness",
                "delta": 0.12,
                "rationale": "Tightness persists because relief is delayed.",
                "schema_version": "1.0.0",
            }
        ],
        state_change_recommended=False,
        proposed_state=None,
        confidence_after=0.80,
        bottlenecks_may_have_changed=True,
        capabilities_may_have_changed=False,
        contradicts_existing_beliefs=False,
        supporting_claim_ids=[str(c) for c in claim_ids],
        contradicting_claim_ids=[],
        evidence=[],
    )


def _archetype() -> str:
    others = (
        "industrial_bottleneck",
        "regulatory_implementation",
        "business_model_disruption",
        "infrastructure_s_curve",
    )
    return _envelope(
        primary_archetype="commodity_supply_cycle",
        secondary_archetypes=[],
        rejected=[{"archetype": a, "reason": "…", "schema_version": "1.0.0"} for a in others],
        reasons=(
            "Constrained processing capacity meeting policy-driven demand is a "
            "supply-cycle pattern, not a technology adoption curve."
        ),
        confidence=0.87,
        supporting_claim_ids=[],
        contradicting_claim_ids=[],
        evidence=[],
    )


def _state(label: str, *, confidence: float = 0.82) -> str:
    return _envelope(
        archetype="commodity_supply_cycle",
        categorical_state=label,
        state_confidence=confidence,
        features=[
            {
                "name": "supply_tightness",
                "value": 8.4,
                "rationale": "Non-Chinese separation below 10 percent of supply.",
                "schema_version": "1.0.0",
            },
            {
                "name": "capacity_response_lead_time",
                "value": 7.9,
                "rationale": "Second train commissioning slipped to 2028.",
                "schema_version": "1.0.0",
            },
        ],
        transition_beliefs={"price_acceleration": 0.55},
        transition_indicators=["Spot premia widening for separated oxides"],
        reversal_indicators=["Non-Chinese separation tonnage rises materially"],
        supporting_claim_ids=[],
        contradicting_claim_ids=[],
        evidence=[],
    )


def _bottlenecks() -> str:
    return _envelope(
        candidates=[
            {
                "name": "Heavy rare-earth separation capacity",
                "description": (
                    "Separation capacity for heavy rare-earth oxides outside China is "
                    "minimal and slow to expand."
                ),
                "kind": "processing_capacity",
                "why_limiting": (
                    "Mined feedstock cannot become a usable oxide without a separation "
                    "train, and trains take years to permit and commission."
                ),
                "currently_binding": True,
                "demand_pressure": 9.1,
                "supply_elasticity": 3.2,
                "time_to_expand": 8.8,
                "current_constraint": 8.9,
                "relief_indicators": ["Non-Chinese separation tonnage rises"],
                "confidence": 0.86,
                "supporting_claim_ids": [],
                "contradicting_claim_ids": [],
                "evidence": [],
                "schema_version": "1.0.0",
            }
        ],
        binding_candidate_index=0,
    )


def _capability(ref: str, name: str) -> dict[str, object]:
    return {
        "ref": ref,
        "name": name,
        "description": f"The ability to deliver {name.lower()} at commercial scale.",
        "role": "necessary",
        "confidence": 0.85,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _leaf(ref: str) -> dict[str, object]:
    return {
        "node": "capability",
        "ref": ref,
        "necessity": "required",
        "weight": 1.0,
        "schema_version": "1.0.0",
    }


def _mapping() -> str:
    return _envelope(
        capabilities=[
            _capability("separation", "Solvent-extraction separation of heavy rare earths"),
            _capability("feedstock", "Secure non-Chinese feedstock supply"),
        ],
        requirement_tree={
            "node": "group",
            "operator": "and",
            "children": [_leaf("separation"), _leaf("feedstock")],
            "necessity": "required",
            "weight": 1.0,
            "label": None,
            "schema_version": "1.0.0",
        },
    )


def _asset_candidate(
    name: str, asset_class: str, *, ticker: str | None = None
) -> dict[str, object]:
    return {
        "proposed_name": name,
        "proposed_ticker": ticker,
        "proposed_exchange": None,
        "asset_class": asset_class,
        "exposure_pathway": "Separation capacity is the binding input.",
        "directness": "direct",
        "materiality": "material",
        "geography": None,
        "dependencies": [],
        "confidence": 0.82,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _asset_discovery() -> str:
    """Two instrument types for one Capability — an equity and the commodity.

    A single Asset per Capability is what a thematic screen already returns, so
    the criterion this feeds (§28, "identify multiple Asset expressions") is
    only meaningfully exercised by more than one.
    """
    return _envelope(
        candidates=[
            _asset_candidate("MP Materials", "common_stock", ticker="MP"),
            _asset_candidate("Neodymium-praseodymium oxide", "commodity", ticker="NDPR"),
        ]
    )


def _exposure() -> str:
    return _envelope(
        exposures=[
            {
                "exposure_kind": "production_capability",
                "directness": "direct",
                "magnitude": 8.6,
                "revenue_share": None,
                "rationale": "Separation is the core of the operation.",
                "quantitative_basis": None,
                "confidence": 0.83,
                "supporting_claim_ids": [],
                "contradicting_claim_ids": [],
                "evidence": [],
                "schema_version": "1.0.0",
            }
        ],
        dependencies=[],
        offsetting_exposures=[],
    )


def _critique() -> str:
    return _envelope(
        critiques=[
            {
                "kind": "unsupported_assumption",
                "statement": "The thesis assumes permitting timelines hold.",
                "severity": 7.4,
                "rationale": (
                    "The only evidence about timelines is a slippage, and nothing "
                    "supplied speaks to the remaining schedule."
                ),
                "testable_with": "Published permit decisions for the effluent works.",
                "supporting_claim_ids": [],
                "contradicting_claim_ids": [],
                "evidence": [],
                "schema_version": "1.0.0",
            },
            {
                "kind": "alternative_explanation",
                "statement": "Equity participation may be a one-off rather than a programme.",
                "severity": 6.1,
                "rationale": "A single transaction is consistent with both readings.",
                "testable_with": "Subsequent transactions in the same programme.",
                "supporting_claim_ids": [],
                "contradicting_claim_ids": [],
                "evidence": [],
                "schema_version": "1.0.0",
            },
        ],
        most_damaging_critique_index=0,
        falsification_risk=6.8,
    )


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class CorpusRun:
    """What the run produced, for the test to assert against."""

    document_ids: list[uuid.UUID] = field(default_factory=list)
    claim_ids: list[uuid.UUID] = field(default_factory=list)
    event_ids: list[uuid.UUID] = field(default_factory=list)
    process_id: uuid.UUID | None = None
    capability_ids: list[uuid.UUID] = field(default_factory=list)
    asset_ids: list[uuid.UUID] = field(default_factory=list)
    duplicate_suppression: int = 0
    provider: str = PROVIDER_NAME


def _service(*responses: str) -> LLMService:
    return LLMService(ScriptedProvider(responses), observers=[])


async def run_corpus(session_factory: async_sessionmaker[AsyncSession]) -> CorpusRun:
    """Drive the whole chain: documents in, an Asset out.

    Written as a straight line rather than through the orchestrator on purpose.
    The orchestrator's own tests cover triggering and retries; what #17 needs to
    show is that the *ontology* holds together end to end, and a linear run makes
    the failure point obvious when it does not.
    """
    run = CorpusRun()

    ingestion = IngestionPipeline(InMemoryObjectStore(), session_factory)
    parsed_documents = []
    for document in CORPUS:
        result = await ingestion.ingest(document.raw())
        assert result.parsed is not None, f"{document.title} did not parse"
        assert result.document_id is not None
        run.document_ids.append(result.document_id)
        parsed_documents.append((result.document_id, result.parsed))

    for (document_id, parsed), script in zip(parsed_documents, EXTRACTION_SCRIPT, strict=True):
        stage = DocumentExtractionStage(_service(*script), session_factory)
        outcome = await stage.run(document_id, parsed)
        assert outcome.claims is not None
        run.claim_ids.extend(outcome.claims.claim_ids)

    # Two wire reports of one story, then the follow-up as its own Event.
    story_claims = run.claim_ids[:3]
    follow_up_claims = run.claim_ids[3:]

    events = EventResolutionStage(
        _service(
            _resolution(
                _cluster(
                    story_claims,
                    title="Defense department takes an equity stake in a rare-earth processor",
                    description=(
                        "The US government acquired a 15 percent equity position "
                        "alongside a floor price for separated oxides."
                    ),
                    publishers=["Meridian Wire", "Halbrook Report"],
                    occurred_at=T0,
                ),
                _cluster(
                    follow_up_claims,
                    title="Second separation train slips to 2028",
                    description="Commissioning delayed by permitting for effluent treatment.",
                    publishers=["Separation Quarterly"],
                    occurred_at=T0 + timedelta(days=21),
                    event_type="capacity_change",
                ),
            ),
            _significance(),
            _significance(materiality=7.1, novelty=6.9),
        ),
        session_factory,
    )
    resolution = await events.run(as_of=T0 + timedelta(days=30))
    assert not resolution.skipped_reason, resolution.skipped_reason
    run.event_ids = [event.persisted.event_id for event in resolution.events]
    run.duplicate_suppression = resolution.duplicate_suppression

    discovery = ProcessDiscoveryStage(_service(_discovery(story_claims)), session_factory)
    discovered = await discovery.run(run.event_ids[0])
    assert discovered.created, f"no Process was created: {discovered.skipped_reason}"
    run.process_id = discovered.created[0].process_id

    # The follow-up Event revises the Process rather than creating a second one.
    updater = ProcessDiscoveryStage(
        _service(_update(run.process_id, follow_up_claims), _belief_update(follow_up_claims)),
        session_factory,
    )
    await updater.run(run.event_ids[1])

    state = ProcessStateStage(_service(_archetype(), _state("supply_tightness")), session_factory)
    await state.run(run.process_id)

    capabilities = CapabilityStage(_service(_bottlenecks(), _mapping()), session_factory)
    capability_outcome = await capabilities.run(run.process_id)
    assert capability_outcome.requirement is not None, (
        "no requirement tree: "
        f"{capability_outcome.skipped_reason or capability_outcome.rejected_reason}"
    )
    run.capability_ids = [c.capability_id for c in capability_outcome.requirement.capabilities]
    assert run.capability_ids, "no Capabilities were mapped"

    assets = AssetDiscoveryStage(
        _service(_asset_discovery(), _exposure(), _exposure()), session_factory
    )
    asset_outcome = await assets.run(run.capability_ids[0])
    run.asset_ids = [
        r.resolved.asset_id for r in asset_outcome.resolutions if r.resolved is not None
    ]

    critic = ProcessCritiqueStage(_service(_critique()), session_factory)
    await critic.run(run.process_id)

    return run
