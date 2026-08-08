"""Writing market data into the system of record (issue #77).

One rule governs this module: **a price row says what was true on a trading day,
and separately when we learned it.** Every row carries ``observed_at`` (the
close) and ``recorded_at`` (the fetch), and a re-fetch of a past window appends
rather than updates.

That is not tidiness. Tiingo's adjusted close for a past date changes whenever a
split or dividend happens after it, so overwriting would make every historical
price silently reflect corporate actions the system could not have known about.
A backtest reading those numbers would be reading the future, and would look
like it was working (agent doc §20).

Two consequences worth stating because they surprise people:

* the same trading day legitimately appears many times, once per fetch, and a
  point-in-time read takes the newest row whose ``recorded_at`` precedes the
  cut-off — not the newest row;
* the raw close is stored alongside the adjusted one, because the raw close is
  the only figure that does not change, and a disagreement between two fetches
  is only interpretable if both are present.

Symbols Tiingo does not cover are recorded as unresolved rather than skipped
silently. An Asset with no price data is a real state of the world and the Quant
agent (#75) has to be able to say so.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from econiq_data_models import Asset, AssetState, QuantitativeObservation
from econiq_ontology import AssetClass, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_market.client import PriceBar, SymbolNotCoveredError, TiingoClient

logger = logging.getLogger("econiq.market.ingest")

SOURCE = "tiingo"

#: How far back a first fetch reaches. Two years is enough for the relative
#: strength and volatility windows the Quant agent needs (#75) without pulling
#: decades nobody looks at.
DEFAULT_BACKFILL = timedelta(days=730)


@dataclass(frozen=True, slots=True)
class SymbolResult:
    asset_id: uuid.UUID
    symbol: str
    bars: int = 0
    corporate_actions: int = 0
    unresolved_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.unresolved_reason is None


@dataclass(frozen=True, slots=True)
class IngestResult:
    results: list[SymbolResult] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=utcnow)

    @property
    def bars(self) -> int:
        return sum(result.bars for result in self.results)

    @property
    def unresolved(self) -> list[SymbolResult]:
        return [result for result in self.results if not result.ok]

    @property
    def coverage(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for result in self.results if result.ok) / len(self.results)


class MarketIngest:
    """Fetches prices for the Assets the graph knows about."""

    def __init__(
        self,
        client: TiingoClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.client = client
        self.session_factory = session_factory

    async def run(
        self,
        *,
        asset_ids: Sequence[uuid.UUID] | None = None,
        start: date | None = None,
        now: datetime | None = None,
    ) -> IngestResult:
        fetched_at = now or utcnow()
        window_start = start or (fetched_at - DEFAULT_BACKFILL).date()

        async with self.session_factory() as session:
            assets = await self._priceable(session, asset_ids)

        results: list[SymbolResult] = []
        for asset_id, symbol, asset_class, currency in assets:
            results.append(
                await self._one(asset_id, symbol, asset_class, currency, window_start, fetched_at)
            )
        return IngestResult(results=results, fetched_at=fetched_at)

    # ------------------------------------------------------------------ #

    async def _one(
        self,
        asset_id: uuid.UUID,
        symbol: str,
        asset_class: AssetClass,
        currency: str | None,
        start: date,
        fetched_at: datetime,
    ) -> SymbolResult:
        try:
            if asset_class is AssetClass.CURRENCY:
                bars = [
                    PriceBar(
                        symbol=symbol,
                        trade_date=bar.ts.date(),
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=None,
                        adj_close=bar.close,
                    )
                    for bar in await self.client.fx_prices(symbol, start=start)
                ]
            else:
                bars = await self.client.daily_prices(symbol, start=start)
        except SymbolNotCoveredError as exc:
            logger.info("tiingo does not cover %s", symbol)
            return SymbolResult(asset_id=asset_id, symbol=symbol, unresolved_reason=str(exc))
        except Exception as exc:  # one bad symbol must not stop the whole run
            logger.warning("fetch failed for %s: %s", symbol, exc)
            return SymbolResult(asset_id=asset_id, symbol=symbol, unresolved_reason=str(exc))

        if not bars:
            return SymbolResult(
                asset_id=asset_id,
                symbol=symbol,
                unresolved_reason="covered but no bars in the requested window",
            )

        await self._store(asset_id, symbol, bars, currency, fetched_at)
        return SymbolResult(
            asset_id=asset_id,
            symbol=symbol,
            bars=len(bars),
            corporate_actions=sum(1 for bar in bars if bar.had_corporate_action),
        )

    async def _store(
        self,
        asset_id: uuid.UUID,
        symbol: str,
        bars: Sequence[PriceBar],
        currency: str | None,
        fetched_at: datetime,
    ) -> None:
        async with self.session_factory() as session:
            for bar in bars:
                observed_at = datetime.combine(bar.trade_date, datetime.min.time(), tzinfo=UTC)
                session.add(
                    AssetState(
                        asset_state_id=uuid.uuid4(),
                        asset_id=asset_id,
                        currency=currency,
                        observed_at=observed_at,
                        # `recorded_at` defaults to now, which is what makes a
                        # point-in-time read able to ask for the adjustment
                        # factors known at the time rather than today's.
                        recorded_at=fetched_at,
                        technical={
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            # Both, always. The raw close is the only figure
                            # that does not move; the adjusted one is the one
                            # worth analysing. Storing one loses the ability to
                            # tell a price move from a corporate action.
                            "close": bar.close,
                            "adj_close": bar.adj_close,
                            "volume": bar.volume,
                            "adj_volume": bar.adj_volume,
                        },
                        market_structure={
                            "dividend": bar.dividend,
                            "split_factor": bar.split_factor,
                            "corporate_action": bar.had_corporate_action,
                        },
                        fundamental={},
                        valuation={},
                        source=f"{SOURCE}:{symbol}",
                    )
                )
                session.add(
                    QuantitativeObservation(
                        observation_id=uuid.uuid4(),
                        subject_id=asset_id,
                        metric="close",
                        value=bar.close,
                        unit="price",
                        currency=currency,
                        period_start=bar.trade_date,
                        period_end=bar.trade_date,
                        period_type="daily",
                        reported_vs_derived="reported",
                        # Never `restated`: a re-fetch of the same day is a new
                        # observation of the same fact, and the restatement flag
                        # is reserved for a source revising a *reported* number.
                        restated=False,
                        observed_at=observed_at,
                        recorded_at=fetched_at,
                        # No source document: a price is a vendor observation
                        # rather than something extracted from a filing, so the
                        # provenance goes in `source_location` and
                        # `source_document_id` stays null rather than pointing
                        # at a document that does not exist.
                        source_location={"vendor": SOURCE, "symbol": symbol},
                    )
                )
            await session.commit()

    async def _priceable(
        self, session: AsyncSession, asset_ids: Sequence[uuid.UUID] | None
    ) -> list[tuple[uuid.UUID, str, AssetClass, str | None]]:
        """Current Assets that have a symbol Tiingo could recognise.

        Commodities are excluded and that is the coverage gap #77 names: Tiingo
        prices equities, ETFs and FX, and the reference universe also holds
        about twenty commodities. They are left out rather than mapped to a
        proxy here, because a proxy relationship that is implied rather than
        recorded is exactly the kind of silent substitution the Asset layer
        exists to prevent.
        """
        query = select(Asset).where(Asset.valid_to.is_(None))
        if asset_ids:
            query = query.where(Asset.asset_id.in_(asset_ids))
        rows = (await session.execute(query)).scalars().all()

        priceable: list[tuple[uuid.UUID, str, AssetClass, str | None]] = []
        for row in rows:
            if row.asset_class is AssetClass.CURRENCY:
                symbol = row.currency_pair
            elif row.asset_class in {
                AssetClass.COMMON_STOCK,
                AssetClass.ETF,
                AssetClass.INDEX,
            }:
                symbol = row.ticker
            else:
                symbol = None
            if symbol:
                priceable.append((row.asset_id, symbol, row.asset_class, row.currency))
        return priceable


async def latest_known_at(
    session: AsyncSession,
    asset_id: uuid.UUID,
    *,
    as_of: datetime,
    trading_day: date | None = None,
) -> AssetState | None:
    """The price row for a day *as it was understood at* ``as_of``.

    The newest row whose ``recorded_at`` precedes the cut-off — not simply the
    newest row. Those differ whenever a fetch after the cut-off revised the
    adjusted close, and taking the newest would hand a backtest an adjustment
    factor it could not have known.
    """
    query = select(AssetState).where(
        AssetState.asset_id == asset_id,
        AssetState.recorded_at <= as_of,
    )
    if trading_day is not None:
        day = datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC)
        query = query.where(AssetState.observed_at == day)
    else:
        query = query.where(AssetState.observed_at <= as_of)

    return (
        await session.execute(
            query.order_by(AssetState.observed_at.desc(), AssetState.recorded_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
