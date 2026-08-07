"""Resolving Asset candidates and persisting exposures.

The resolution step is the point of this module. An agent proposes "gold" or
"MP Materials"; code decides what, if anything, that names:

* commodities and currencies resolve against the reference universe, which is a
  small closed set and therefore the *most* reliable class to resolve, not the
  least;
* equities resolve against Assets already in the graph, and otherwise stay
  Candidates until a security master exists (issue #47).

An unresolvable Candidate is kept, not discarded. It is the honest record that
the system found an expression it cannot yet name, and the rate of those is a
quality signal about discovery rather than something to hide.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from econiq_data_models import Asset, AssetCandidate, AssetExposure, Node
from econiq_ontology import AssetClass, EntityType, utcnow
from econiq_schemas import ProposedAssetCandidate, ProposedExposure
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.reference_universe import ReferenceInstrument, lookup

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    asset_id: uuid.UUID
    name: str
    asset_class: AssetClass
    created: bool
    matched_by: str
    """``reference``, ``symbol``, ``name`` or ``created``."""


@dataclass(frozen=True, slots=True)
class AssetResolution:
    candidate_id: uuid.UUID
    resolved: ResolvedAsset | None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.resolved is not None


@dataclass(frozen=True, slots=True)
class PersistedExposures:
    asset_id: uuid.UUID
    exposure_ids: list[uuid.UUID] = field(default_factory=list)
    offsetting: tuple[str, ...] = ()


class AssetWriter:
    """Turns proposals into Assets, or records why they could not be."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def resolve(
        self,
        proposal: ProposedAssetCandidate,
        *,
        capability_id: uuid.UUID,
        agent_run_id: uuid.UUID,
    ) -> AssetResolution:
        candidate_id = await self._record_candidate(
            proposal, capability_id=capability_id, agent_run_id=agent_run_id
        )

        if proposal.asset_class in (AssetClass.COMMODITY, AssetClass.CURRENCY):
            instrument = lookup(proposal.proposed_ticker) or lookup(proposal.proposed_name)
            if instrument is None:
                return await self._unresolved(
                    candidate_id,
                    f"{proposal.proposed_name!r} is not in the reference universe",
                )
            resolved = await self._upsert_reference(instrument, agent_run_id=agent_run_id)
            await self._link_candidate(candidate_id, resolved.asset_id)
            return AssetResolution(candidate_id=candidate_id, resolved=resolved)

        ticker = (proposal.proposed_ticker or "").strip().upper()
        if ticker and _TICKER.match(ticker):
            resolved = await self._upsert_listed(proposal, ticker, agent_run_id=agent_run_id)
            await self._link_candidate(candidate_id, resolved.asset_id)
            return AssetResolution(candidate_id=candidate_id, resolved=resolved)

        existing = await self._by_name(proposal.proposed_name)
        if existing is not None:
            await self._link_candidate(candidate_id, existing.asset_id)
            return AssetResolution(
                candidate_id=candidate_id,
                resolved=ResolvedAsset(
                    asset_id=existing.asset_id,
                    name=existing.name,
                    asset_class=existing.asset_class,
                    created=False,
                    matched_by="name",
                ),
            )

        # No ticker and no match. Kept as a Candidate rather than invented: a
        # security master arrives with issue #47, and guessing an identifier now
        # would put an unverifiable one in the graph.
        return await self._unresolved(
            candidate_id, "no usable identifier and no existing Asset of that name"
        )

    async def _unresolved(self, candidate_id: uuid.UUID, reason: str) -> AssetResolution:
        async with self.session_factory() as session:
            await session.execute(
                update(AssetCandidate)
                .where(AssetCandidate.asset_candidate_id == candidate_id)
                .values(resolution_note=reason)
            )
            await session.commit()
        return AssetResolution(candidate_id=candidate_id, resolved=None, reason=reason)

    async def _record_candidate(
        self,
        proposal: ProposedAssetCandidate,
        *,
        capability_id: uuid.UUID,
        agent_run_id: uuid.UUID,
    ) -> uuid.UUID:
        candidate_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                AssetCandidate(
                    asset_candidate_id=candidate_id,
                    proposed_name=proposal.proposed_name,
                    proposed_ticker=proposal.proposed_ticker,
                    proposed_exchange=proposal.proposed_exchange,
                    proposed_symbol=(
                        proposal.proposed_ticker
                        if proposal.asset_class in (AssetClass.COMMODITY, AssetClass.CURRENCY)
                        else None
                    ),
                    asset_class=proposal.asset_class,
                    capability_id=capability_id,
                    rationale=proposal.exposure_pathway,
                    confidence=proposal.confidence,
                    agent_run_id=agent_run_id,
                )
            )
            await session.commit()
        return candidate_id

    async def _link_candidate(self, candidate_id: uuid.UUID, asset_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(AssetCandidate)
                .where(AssetCandidate.asset_candidate_id == candidate_id)
                .values(resolved_asset_id=asset_id)
            )
            await session.commit()

    async def _upsert_reference(
        self, instrument: ReferenceInstrument, *, agent_run_id: uuid.UUID
    ) -> ResolvedAsset:
        """Create or reuse the Asset for a reference instrument.

        One node per instrument: gold reached through a strategic-minerals
        Process and gold reached through a monetary Process must be the same
        Asset, or the graph cannot show that two theses converge on it.
        """
        async with self.session_factory() as session:
            existing = await self._reference_match(session, instrument)
            if existing is not None:
                return ResolvedAsset(
                    asset_id=existing.asset_id,
                    name=existing.name,
                    asset_class=existing.asset_class,
                    created=False,
                    matched_by="reference",
                )

        asset_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(Node(node_id=asset_id, node_type=EntityType.ASSET))
            await session.flush()
            session.add(
                Asset(
                    asset_id=asset_id,
                    revision=1,
                    name=instrument.name,
                    asset_class=instrument.asset_class,
                    commodity_code=instrument.commodity_code,
                    contract_code=instrument.contract_code,
                    benchmark=instrument.benchmark,
                    currency_pair=instrument.currency_pair,
                    currency_code=instrument.currency_code,
                    currency=instrument.quote_currency,
                    country=instrument.country,
                    description=f"Reference instrument: {instrument.name}.",
                    agent_run_id=agent_run_id,
                )
            )
            await session.commit()
        return ResolvedAsset(
            asset_id=asset_id,
            name=instrument.name,
            asset_class=instrument.asset_class,
            created=True,
            matched_by="reference",
        )

    async def _upsert_listed(
        self, proposal: ProposedAssetCandidate, ticker: str, *, agent_run_id: uuid.UUID
    ) -> ResolvedAsset:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(Asset).where(
                        Asset.ticker == ticker,
                        Asset.asset_class == proposal.asset_class,
                        Asset.valid_to.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return ResolvedAsset(
                    asset_id=existing.asset_id,
                    name=existing.name,
                    asset_class=existing.asset_class,
                    created=False,
                    matched_by="symbol",
                )

        asset_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(Node(node_id=asset_id, node_type=EntityType.ASSET))
            await session.flush()
            session.add(
                Asset(
                    asset_id=asset_id,
                    revision=1,
                    name=proposal.proposed_name,
                    asset_class=proposal.asset_class,
                    ticker=ticker,
                    exchange=proposal.proposed_exchange,
                    country=proposal.geography,
                    agent_run_id=agent_run_id,
                )
            )
            await session.commit()
        return ResolvedAsset(
            asset_id=asset_id,
            name=proposal.proposed_name,
            asset_class=proposal.asset_class,
            created=True,
            matched_by="symbol",
        )

    async def _reference_match(
        self, session: AsyncSession, instrument: ReferenceInstrument
    ) -> Asset | None:
        query = select(Asset).where(
            Asset.asset_class == instrument.asset_class, Asset.valid_to.is_(None)
        )
        if instrument.commodity_code:
            query = query.where(Asset.commodity_code == instrument.commodity_code)
        elif instrument.currency_pair:
            query = query.where(Asset.currency_pair == instrument.currency_pair)
        else:
            query = query.where(Asset.name == instrument.name)
        return (await session.execute(query)).scalar_one_or_none()

    async def _by_name(self, name: str) -> Asset | None:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(Asset).where(Asset.name == name, Asset.valid_to.is_(None))
                )
            ).scalar_one_or_none()

    async def known_names(self, limit: int = 60) -> list[str]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Asset.name)
                    .where(Asset.valid_to.is_(None))
                    .order_by(Asset.created_at.desc())
                    .limit(limit)
                )
            ).scalars()
            return list(rows)


class ExposureWriter:
    """Appends exposure observations.

    Exposure is an observation, not a property: it changes as the business
    changes, and a historical snapshot must see the exposure believed at the
    time rather than today's (ontology §16, §33).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def persist(
        self,
        asset_id: uuid.UUID,
        target_id: uuid.UUID,
        exposures: list[ProposedExposure],
        *,
        target_type: EntityType,
        agent_run_id: uuid.UUID,
        observed_at: datetime,
        offsetting: tuple[str, ...] = (),
    ) -> PersistedExposures:
        ids: list[uuid.UUID] = []
        async with self.session_factory() as session:
            for exposure in exposures:
                exposure_id = uuid.uuid4()
                ids.append(exposure_id)
                session.add(
                    AssetExposure(
                        asset_exposure_id=exposure_id,
                        asset_id=asset_id,
                        target_id=target_id,
                        target_type=target_type,
                        exposure_kind=exposure.exposure_kind,
                        directness=exposure.directness.value,
                        magnitude=exposure.magnitude,
                        revenue_share=exposure.revenue_share,
                        quantitative_basis=exposure.quantitative_basis,
                        rationale=exposure.rationale,
                        confidence=exposure.confidence,
                        observed_at=observed_at,
                        agent_run_id=agent_run_id,
                    )
                )
            await session.commit()
        return PersistedExposures(asset_id=asset_id, exposure_ids=ids, offsetting=offsetting)

    async def latest_for(self, asset_id: uuid.UUID, target_id: uuid.UUID) -> list[AssetExposure]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(AssetExposure)
                    .where(
                        AssetExposure.asset_id == asset_id,
                        AssetExposure.target_id == target_id,
                    )
                    .order_by(AssetExposure.observed_at.desc())
                )
            ).scalars()
            return list(rows)


def resolution_rate(resolutions: list[AssetResolution]) -> float:
    """Share of proposals that became Assets.

    A discovery-quality metric: a step that mostly proposes things the system
    cannot name is not producing an investable universe.
    """
    if not resolutions:
        return 0.0
    return sum(1 for resolution in resolutions if resolution.ok) / len(resolutions)


def now() -> datetime:
    return utcnow()
