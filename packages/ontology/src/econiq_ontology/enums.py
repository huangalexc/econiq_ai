"""Closed vocabularies of the ontology.

Every enum here is a contract shared by the database, the agents and (later)
the frontend. Adding a member is an additive schema change; renaming or
removing one is breaking.
"""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    """Node types in the economic graph.

    Mirrors the top-level ontology chain (ontology §3). Every node registered in
    the graph declares one of these, which is what makes typed edges checkable.
    """

    DOCUMENT = "document"
    CLAIM = "claim"
    EVENT = "event"
    PROCESS = "process"
    BOTTLENECK = "bottleneck"
    CAPABILITY = "capability"
    ASSET = "asset"


class DocumentType(StrEnum):
    """Ontology §4."""

    NEWS_ARTICLE = "news_article"
    GOVERNMENT_ANNOUNCEMENT = "government_announcement"
    LEGISLATION = "legislation"
    REGULATORY_FILING = "regulatory_filing"
    EARNINGS_RELEASE = "earnings_release"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    INVESTOR_PRESENTATION = "investor_presentation"
    COMPANY_FILING = "company_filing"
    INDUSTRY_REPORT = "industry_report"
    STATISTICAL_RELEASE = "statistical_release"
    QUANTITATIVE_DATASET = "quantitative_dataset"
    OTHER = "other"


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    EXTRACTED = "extracted"
    FAILED = "failed"
    SKIPPED = "skipped"


class ClaimType(StrEnum):
    """Ontology §5 — the epistemic character of a proposition.

    The distinction is load-bearing: a hypothesis must never accumulate as
    evidence the way a reported claim does.
    """

    REPORTED_CLAIM = "reported_claim"
    DERIVED_FACT = "derived_fact"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"


class EpistemicStatus(StrEnum):
    """Agent doc §2.5 — agents must distinguish these, never blur them."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    HYPOTHESIZED = "hypothesized"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class EventType(StrEnum):
    """Ontology §6. Coarse routing categories, not a taxonomy of the world."""

    POLICY_ANNOUNCEMENT = "policy_announcement"
    POLICY_ENACTMENT = "policy_enactment"
    REGULATORY_ACTION = "regulatory_action"
    GOVERNMENT_FUNDING = "government_funding"
    CORPORATE_ACTION = "corporate_action"
    GUIDANCE_CHANGE = "guidance_change"
    CAPEX_ANNOUNCEMENT = "capex_announcement"
    CAPACITY_CHANGE = "capacity_change"
    SUPPLY_DISRUPTION = "supply_disruption"
    DEMAND_SHIFT = "demand_shift"
    PRICE_MOVE = "price_move"
    TECHNOLOGY_MILESTONE = "technology_milestone"
    MACRO_POLICY = "macro_policy"
    DATA_RELEASE = "data_release"
    OTHER = "other"


class ProcessArchetype(StrEnum):
    """Ontology §8. Each archetype has its own State machine — see
    ``econiq_ontology.archetypes``."""

    INFRASTRUCTURE_S_CURVE = "infrastructure_s_curve"
    COMMODITY_SUPPLY_CYCLE = "commodity_supply_cycle"
    INDUSTRIAL_BOTTLENECK = "industrial_bottleneck"
    REGULATORY_IMPLEMENTATION = "regulatory_implementation"
    BUSINESS_MODEL_DISRUPTION = "business_model_disruption"


class ProcessStatus(StrEnum):
    """Lifecycle of the Process object itself, distinct from its economic
    State (ontology §7 vs §10)."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    DORMANT = "dormant"
    INVALIDATED = "invalidated"
    MERGED = "merged"
    CONCLUDED = "concluded"


class CausalRole(StrEnum):
    """Ontology §9 — Driver and Mechanism are roles in a relationship, not
    subclasses of Process. A Process can be a Driver in one edge and a
    Mechanism in another."""

    DRIVER = "driver"
    MECHANISM = "mechanism"


class RelationshipType(StrEnum):
    """Typed edges (ui_concept §9.1).

    The canonical chain is::

        Process --influences--> Process
        Process --creates--> Bottleneck
        Bottleneck --requires--> Capability
        Capability --expressed_by--> Asset

    Additional types carry evidence and direct Event exposure (ontology §15).
    """

    INFLUENCES = "influences"
    CREATES = "creates"
    REQUIRES = "requires"
    EXPRESSED_BY = "expressed_by"
    AFFECTS = "affects"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"


class LogicOperator(StrEnum):
    """Ontology §12 — Capability requirements form logical structures."""

    AND = "and"
    OR = "or"


class Necessity(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class BottleneckKind(StrEnum):
    """Ontology §11 — what class of constraint blocks the Process."""

    PHYSICAL_CAPACITY = "physical_capacity"
    INPUT_SUPPLY = "input_supply"
    PROCESSING_CAPACITY = "processing_capacity"
    INFRASTRUCTURE = "infrastructure"
    REGULATORY_PERMITTING = "regulatory_permitting"
    CAPITAL = "capital"
    LABOR_SKILLS = "labor_skills"
    TECHNOLOGY = "technology"
    LOGISTICS = "logistics"
    OTHER = "other"


class CritiqueKind(StrEnum):
    """The seven lines of attack the Process Critic must take (agent doc §6.5).

    A closed vocabulary because the critic's coverage is measurable: an
    adversarial pass that only ever finds "contradictory evidence" is not
    attacking the thesis from seven directions.
    """

    UNSUPPORTED_ASSUMPTION = "unsupported_assumption"
    MISSING_CAUSAL_LINK = "missing_causal_link"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    ALTERNATIVE_EXPLANATION = "alternative_explanation"
    HISTORICAL_COUNTEREXAMPLE = "historical_counterexample"
    FALSIFYING_INDICATOR = "falsifying_indicator"
    SPURIOUS_CORRELATION = "spurious_correlation"


class CritiqueStatus(StrEnum):
    """What became of a critique.

    Critiques are never deleted. A thesis that survived an attack is stronger
    than one that was never attacked, and that is only visible if the attacks
    remain on the record.
    """

    OPEN = "open"
    ADDRESSED = "addressed"
    """Later evidence answered it."""

    DISMISSED = "dismissed"
    """A human judged it not to apply."""

    CONFIRMED = "confirmed"
    """It turned out to be right — the thesis was damaged."""


class EvidenceDependenceKind(StrEnum):
    """How two pieces of evidence fail to be independent (agent doc §10.2).

    Ontology §47 says twenty articles repeating one report are not twenty
    pieces of evidence. Within one Event, syndication is detectable from text
    overlap. *Across* Events it is not: two outlets can report the same company
    statement in entirely different words, days apart, and the observation
    behind them is still one observation.

    The kinds are ordered by how much they reduce independence. A shared source
    means one observation; derivative reporting means one observation plus
    commentary; a repeated claim means the same assertion made twice, which may
    or may not rest on the same observation.
    """

    SHARED_SOURCE = "shared_source"
    """Both rest on the same primary document or statement."""

    DERIVATIVE_REPORTING = "derivative_reporting"
    """One reports the other rather than observing independently."""

    REPEATED_CLAIM = "repeated_claim"
    """The same assertion restated, without a new observation behind it."""


class AssetClass(StrEnum):
    """Ontology §14. V1 expresses theses through the underlying asset only —
    options and derivatives are explicitly out of scope."""

    COMMON_STOCK = "common_stock"
    ETF = "etf"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    BOND = "bond"
    INDEX = "index"


class ExposureKind(StrEnum):
    """Ontology §16 'Process Exposure' — how an Asset touches the Process."""

    REVENUE = "revenue"
    INCREMENTAL_EARNINGS = "incremental_earnings"
    CAPACITY = "capacity"
    MARKET_SHARE = "market_share"
    PRODUCTION_CAPABILITY = "production_capability"
    STRATEGIC_POSITIONING = "strategic_positioning"
    GEOGRAPHIC = "geographic"


class ScoreFamily(StrEnum):
    """Ontology §17. These three are never collapsed into one number, anywhere.

    Trade quality is V2 and is present only so that stored scores can never be
    mislabelled; nothing in V1 produces it.
    """

    THESIS_QUALITY = "thesis_quality"
    ASSET_QUALITY = "asset_quality"
    TRADE_QUALITY = "trade_quality"


class ThesisQualityDimension(StrEnum):
    """Ontology §17 — 'Is the underlying Process real, coherent and likely to
    continue?'

    The nine axes of ontology §42, plus ``DATA_QUALITY``. Agent doc §11.1 lists
    ten and §42 lists nine; the extra one is data quality, and it is kept
    because it asks a question no other axis does — how reliable the underlying
    observations are, as distinct from how many there are
    (``ACCUMULATED_EVIDENCE``) or how independent
    (``EVIDENCE_INDEPENDENCE``). A restated filing and a measured tonnage are
    not equally good inputs, and without this axis nothing says so.
    """

    LOGICAL_COHERENCE = "logical_coherence"
    ACCUMULATED_EVIDENCE = "accumulated_evidence"
    STATE_CONFIDENCE = "state_confidence"
    HISTORICAL_PRECEDENT = "historical_precedent"
    COUNTERFACTUAL_ROBUSTNESS = "counterfactual_robustness"
    EVIDENCE_INDEPENDENCE = "evidence_independence"
    CAUSAL_COHERENCE = "causal_coherence"
    DATA_QUALITY = "data_quality"
    CONTRADICTION = "contradiction"
    UNCERTAINTY = "uncertainty"


class AssetQualityDimension(StrEnum):
    """Ontology §17 — 'Is this Asset a strong expression of the Process?'"""

    CAPABILITY_FIT = "capability_fit"
    PROCESS_EXPOSURE = "process_exposure"
    OPERATING_LEVERAGE = "operating_leverage"
    FIRST_MOVER_ADVANTAGE = "first_mover_advantage"
    VERTICAL_INTEGRATION = "vertical_integration"
    MARKET_SHARE = "market_share"
    BALANCE_SHEET = "balance_sheet"
    VALUATION = "valuation"
    INSTITUTIONAL_POSITIONING = "institutional_positioning"
    TECHNICAL_CONFIRMATION = "technical_confirmation"
