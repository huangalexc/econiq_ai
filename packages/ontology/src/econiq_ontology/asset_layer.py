"""Asset Candidate → Asset → Asset State (ontology §14–§16).

An Asset is an investable projection of an upstream Process/Capability
configuration — never the Process itself. V1 expresses a thesis through the
underlying asset only; options and derivatives are explicitly out of scope
(ontology §14).
"""

from __future__ import annotations

import uuid
from typing import Literal, Self

from pydantic import Field, model_validator

from econiq_ontology.base import Confidence, Entity, OntologyModel, Score10, TemporalObservation
from econiq_ontology.enums import AssetClass, EntityType, ExposureKind
from econiq_ontology.provenance import AgentAttribution, EntityRef, EvidenceRef


class AssetIdentifiers(OntologyModel):
    """Market identifiers. Resolution is deterministic work — an LLM may propose
    a ticker, but only code may assert one (agent doc §2.3).

    Deliberately not equity-only. A Commodity Supply Cycle is often expressed
    most cleanly by the commodity itself rather than by a producer's equity, and
    a Process driven by monetary policy may be expressed in a currency. An
    identifier model that only knew about tickers would quietly push every
    thesis into the equity market.
    """

    # Equities and funds
    ticker: str | None = None
    exchange: str | None = None
    isin: str | None = None
    figi: str | None = None
    cik: str | None = None
    cusip: str | None = None

    # Commodities: the metal, energy or agricultural unit itself
    commodity_code: str | None = Field(
        default=None, description="Standard code, e.g. XAU (gold), XAG (silver), HG (copper)."
    )
    contract_code: str | None = Field(
        default=None, description="Futures contract, e.g. 'COMEX:GC' — the traded expression."
    )
    benchmark: str | None = Field(
        default=None, description="Reference price, e.g. 'LBMA Gold PM', 'Platts IODEX 62%'."
    )

    # Currencies
    currency_pair: str | None = Field(
        default=None, pattern=r"^[A-Z]{3}[A-Z]{3}$", description="e.g. USDJPY."
    )
    currency_code: str | None = Field(
        default=None, pattern=r"^[A-Z]{3}$", description="ISO 4217, when the Asset is one currency."
    )


class AssetCandidate(OntologyModel):
    """A proposed Asset, before identifier resolution (ontology §3).

    The Asset Discovery agent emits Candidates; a deterministic resolution step
    turns a Candidate into an ``Asset`` (or discards it). Keeping the two apart
    is what stops an unresolvable LLM guess from entering the graph as fact.
    """

    proposed_name: str
    proposed_identifiers: AssetIdentifiers = Field(default_factory=AssetIdentifiers)
    asset_class: AssetClass
    capability_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None
    rationale: str
    confidence: Confidence
    resolved_asset_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _anchored(self) -> Self:
        if self.capability_id is None and self.process_id is None:
            raise ValueError("an AssetCandidate must anchor to a Capability or Process")
        return self


class Asset(Entity):
    """An investable security or underlying economic instrument (ontology §14)."""

    entity_type: Literal[EntityType.ASSET] = EntityType.ASSET

    name: str = Field(min_length=1)
    asset_class: AssetClass
    identifiers: AssetIdentifiers = Field(default_factory=AssetIdentifiers)
    country: str | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    is_active: bool = True
    attribution: AgentAttribution | None = None

    @model_validator(mode="after")
    def _identifiers_match_the_asset_class(self) -> Self:
        """Every Asset must be identifiable in the way its class is traded.

        A ticker is the wrong requirement for gold and a meaningless one for a
        currency pair; requiring one anyway is how a system ends up expressing
        every thesis through equities.
        """
        identifiers = self.identifiers
        required: dict[AssetClass, tuple[str, ...]] = {
            AssetClass.COMMON_STOCK: ("ticker",),
            AssetClass.ETF: ("ticker",),
            AssetClass.COMMODITY: ("commodity_code", "contract_code", "benchmark"),
            AssetClass.CURRENCY: ("currency_pair", "currency_code"),
            AssetClass.INDEX: ("ticker", "benchmark"),
            AssetClass.BOND: ("isin", "cusip", "ticker"),
        }
        accepted = required[self.asset_class]
        if not any(getattr(identifiers, field) for field in accepted):
            raise ValueError(f"{self.asset_class.value} requires one of: {', '.join(accepted)}")
        return self


class AssetExposure(TemporalObservation):
    """How much of an Asset is actually exposed to a Process or Capability
    (ontology §16, 'Process Exposure').

    This is the join between the economic graph and the investable universe, and
    the reason an Asset page can show *why* it was surfaced. Exposure is an
    observation, not a property: it changes as the business changes.
    """

    asset_id: uuid.UUID
    target: EntityRef = Field(description="The Process or Capability being expressed.")
    exposure_kind: ExposureKind
    magnitude: Score10 = Field(description="Strength of the exposure, 0-10.")
    revenue_share: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of revenue attributable, when measurable.",
    )
    confidence: Confidence
    rationale: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    attribution: AgentAttribution | None = None

    @model_validator(mode="after")
    def _target_is_expressible(self) -> Self:
        if self.target.entity_type not in (EntityType.PROCESS, EntityType.CAPABILITY):
            raise ValueError("exposure target must be a Process or a Capability")
        return self


class FundamentalState(OntologyModel):
    """Ontology §16 'Fundamental'. Populated by the Phase 3 financial ETL
    (issue #48) — deterministic, never LLM-asserted."""

    revenue_growth: float | None = None
    earnings_growth: float | None = None
    free_cash_flow: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    roic: float | None = None
    net_debt_to_ebitda: float | None = None
    capex_intensity: float | None = None
    operating_leverage: float | None = None


class ValuationState(OntologyModel):
    """Ontology §16 'Valuation'."""

    pe: float | None = None
    ev_sales: float | None = None
    ev_ebitda: float | None = None
    fcf_yield: float | None = None
    relative_valuation_percentile: float | None = Field(default=None, ge=0.0, le=1.0)
    valuation_vs_history_percentile: float | None = Field(default=None, ge=0.0, le=1.0)


class MarketStructureState(OntologyModel):
    """Ontology §16 'Market Structure'."""

    institutional_ownership: float | None = Field(default=None, ge=0.0, le=1.0)
    insider_ownership: float | None = Field(default=None, ge=0.0, le=1.0)
    short_interest: float | None = Field(default=None, ge=0.0)
    crowding: Score10 | None = None
    analyst_positioning: Score10 | None = None
    average_daily_volume_usd: float | None = Field(default=None, ge=0.0)


class TechnicalState(OntologyModel):
    """Ontology §16 'Technical State'. Produced by the Phase 3 technical
    analysis service (issue #49)."""

    relative_strength: Score10 | None = None
    momentum: Score10 | None = None
    volatility: float | None = Field(default=None, ge=0.0)
    volatility_contraction: Score10 | None = None
    accumulation: Score10 | None = None
    breakout_distance: float | None = None
    above_200dma: bool | None = None


class AssetState(TemporalObservation):
    """An Asset's own state, independent of the Process (ontology §16).

    Used for Asset Quality and Asset Ranking — never for deciding whether the
    underlying Process is true. The contract is defined here in Phase 0 so the
    schema is stable; the fields are populated from Phase 3 onward (issues
    #47–#50). Phase 0/1 surfaces must treat unpopulated groups as absent, not
    as zero.
    """

    asset_id: uuid.UUID
    fundamental: FundamentalState = Field(default_factory=FundamentalState)
    valuation: ValuationState = Field(default_factory=ValuationState)
    market_structure: MarketStructureState = Field(default_factory=MarketStructureState)
    technical: TechnicalState = Field(default_factory=TechnicalState)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
