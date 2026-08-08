"""Market data ingestion (issue #77)."""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from econiq_data_models import Asset, AssetState, Node, QuantitativeObservation
from econiq_market import (
    MarketIngest,
    MissingTokenError,
    SymbolNotCoveredError,
    TiingoClient,
    latest_known_at,
    parse_price_csv,
    parse_universe_csv,
    parse_universe_zip,
)
from econiq_ontology import AssetClass, EntityType
from sqlalchemy import select

PRICES = """\
date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,divCash,splitFactor
2026-03-02,101.5,102.0,100.0,100.5,120000,50.75,51.0,50.0,50.25,240000,0.0,1.0
2026-03-03,103.0,103.5,101.0,101.5,130000,51.5,51.75,50.5,50.75,260000,0.0,1.0
2026-03-04,104.0,104.5,102.0,103.0,140000,104.0,104.5,102.0,103.0,140000,0.0,2.0
"""


def test_a_client_without_a_token_refuses_to_start(monkeypatch):
    """A client that constructs happily and fails on every call turns a
    configuration mistake into an intermittent-looking outage."""
    monkeypatch.delenv("TIINGO_API_TOKEN", raising=False)

    with pytest.raises(MissingTokenError, match="TIINGO_API_TOKEN"):
        TiingoClient()


def test_both_the_raw_and_adjusted_close_are_parsed():
    """The adjusted close changes retroactively; the raw one does not. A
    disagreement between two fetches is only interpretable if both are kept."""
    bars = list(parse_price_csv("MP", PRICES))

    assert len(bars) == 3
    assert bars[0].close == 101.5
    assert bars[0].adj_close == 50.75
    assert bars[0].close != bars[0].adj_close


def test_a_split_day_is_flagged_because_it_revises_every_earlier_day():
    bars = list(parse_price_csv("MP", PRICES))

    assert bars[2].split_factor == 2.0
    assert bars[2].had_corporate_action is True
    assert bars[0].had_corporate_action is False


def test_a_row_with_no_close_is_skipped_rather_than_zeroed():
    """A zero price would propagate into every return calculation downstream."""
    bars = list(parse_price_csv("MP", "date,close,adjClose\n2026-03-02,,\n2026-03-03,10.0,10.0\n"))

    assert [bar.trade_date for bar in bars] == [date(2026, 3, 3)]


def test_a_delisted_ticker_is_kept_in_the_universe():
    """Dropping delisted names is how survivorship bias enters a system
    (agent doc §19 lists it as a fault to inject)."""
    entries = list(
        parse_universe_csv(
            "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
            "MP,NYSE,Stock,USD,2020-01-01,\n"
            "GONE,NYSE,Stock,USD,2015-01-01,2023-06-30\n"
        )
    )

    assert [e.ticker for e in entries] == ["MP", "GONE"]
    assert entries[0].delisted is False
    assert entries[1].delisted is True


def test_the_universe_is_read_from_the_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "supported_tickers.csv",
            "ticker,exchange,assetType,priceCurrency,startDate,endDate\nMP,NYSE,Stock,USD,2020-01-01,\n",
        )

    entries = list(parse_universe_zip(payload.getvalue()))

    assert [e.ticker for e in entries] == ["MP"]


def _client(handler) -> TiingoClient:
    transport = httpx.MockTransport(handler)
    return TiingoClient("test-token", client=httpx.AsyncClient(transport=transport))


async def test_an_uncovered_symbol_is_an_answer_not_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not found")

    with pytest.raises(SymbolNotCoveredError) as caught:
        await _client(handler).daily_prices("NOPE", start=date(2026, 1, 1))

    assert caught.value.symbol == "NOPE"


async def test_the_token_is_sent_and_csv_is_requested():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, text=PRICES)

    await _client(handler).daily_prices("MP", start=date(2026, 3, 1))

    assert seen["token"] == "test-token"
    assert seen["format"] == "csv"
    assert seen["startDate"] == "2026-03-01"


# --------------------------------------------------------------------------- #
# The ingest
# --------------------------------------------------------------------------- #

pytestmark_integration = pytest.mark.integration


async def _asset(session_factory, *, ticker: str | None, asset_class: AssetClass) -> uuid.UUID:
    asset_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=asset_id, node_type=EntityType.ASSET))
        await session.flush()
        session.add(
            Asset(
                asset_id=asset_id,
                revision=1,
                name=ticker or "Commodity",
                asset_class=asset_class,
                ticker=ticker if asset_class is not AssetClass.COMMODITY else None,
                commodity_code="NDPR" if asset_class is AssetClass.COMMODITY else None,
                benchmark="Asian Metal NdPr Oxide" if asset_class is AssetClass.COMMODITY else None,
                currency="USD",
            )
        )
        await session.commit()
    return asset_id


def _ingest(session_factory, text: str = PRICES) -> MarketIngest:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=text)

    return MarketIngest(_client(handler), session_factory)


@pytest.mark.integration
async def test_prices_land_with_both_clocks(session_factory):
    await _asset(session_factory, ticker="MP", asset_class=AssetClass.COMMON_STOCK)
    fetched = datetime(2026, 3, 5, 12, tzinfo=UTC)

    result = await _ingest(session_factory).run(now=fetched, start=date(2026, 3, 1))

    assert result.bars == 3
    async with session_factory() as session:
        rows = (
            (await session.execute(select(AssetState).order_by(AssetState.observed_at)))
            .scalars()
            .all()
        )
    assert [row.observed_at.date() for row in rows] == [
        date(2026, 3, 2),
        date(2026, 3, 3),
        date(2026, 3, 4),
    ]
    # Both clocks: what was true, and when we learned it.
    assert all(row.recorded_at == fetched for row in rows)
    assert rows[0].technical["close"] == 101.5
    assert rows[0].technical["adj_close"] == 50.75
    assert rows[2].market_structure["corporate_action"] is True


@pytest.mark.integration
async def test_a_refetch_appends_rather_than_overwrites(session_factory):
    """Overwriting would make every historical price silently reflect corporate
    actions the system could not have known about (agent doc §20)."""
    await _asset(session_factory, ticker="MP", asset_class=AssetClass.COMMON_STOCK)
    first = datetime(2026, 3, 5, tzinfo=UTC)
    later = datetime(2026, 4, 5, tzinfo=UTC)

    await _ingest(session_factory).run(now=first, start=date(2026, 3, 1))
    # The same days, re-adjusted after a split.
    revised = PRICES.replace("50.75", "25.375").replace("51.5", "25.75")
    await _ingest(session_factory, revised).run(now=later, start=date(2026, 3, 1))

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(AssetState).where(
                        AssetState.observed_at == datetime(2026, 3, 2, tzinfo=UTC)
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2
    # The raw close is unchanged; only the adjustment moved.
    assert {row.technical["close"] for row in rows} == {101.5}
    assert {row.technical["adj_close"] for row in rows} == {50.75, 25.375}


@pytest.mark.integration
async def test_a_point_in_time_read_gets_the_adjustment_known_at_the_time(session_factory):
    """The newest row whose `recorded_at` precedes the cut-off — not simply the
    newest row. Taking the newest would hand a backtest an adjustment factor it
    could not have known."""
    asset_id = await _asset(session_factory, ticker="MP", asset_class=AssetClass.COMMON_STOCK)
    first = datetime(2026, 3, 5, tzinfo=UTC)
    later = datetime(2026, 4, 5, tzinfo=UTC)

    await _ingest(session_factory).run(now=first, start=date(2026, 3, 1))
    await _ingest(session_factory, PRICES.replace("50.75", "25.375")).run(
        now=later, start=date(2026, 3, 1)
    )

    async with session_factory() as session:
        as_known_then = await latest_known_at(
            session, asset_id, as_of=first + timedelta(days=1), trading_day=date(2026, 3, 2)
        )
        as_known_now = await latest_known_at(
            session, asset_id, as_of=later + timedelta(days=1), trading_day=date(2026, 3, 2)
        )

    assert as_known_then is not None and as_known_now is not None
    assert as_known_then.technical["adj_close"] == 50.75
    assert as_known_now.technical["adj_close"] == 25.375


@pytest.mark.integration
async def test_a_commodity_is_reported_unresolved_rather_than_proxied(session_factory):
    """Tiingo prices equities and FX. A proxy relationship that is implied
    rather than recorded is the silent substitution the Asset layer prevents."""
    await _asset(session_factory, ticker=None, asset_class=AssetClass.COMMODITY)

    result = await _ingest(session_factory).run(now=datetime(2026, 3, 5, tzinfo=UTC))

    # Not priceable at all, so it never reaches the fetch.
    assert result.results == []
    assert result.coverage == 0.0


@pytest.mark.integration
async def test_an_uncovered_ticker_is_recorded_not_skipped(session_factory):
    """An Asset with no price data is a real state of the world, and the Quant
    agent has to be able to say so."""
    await _asset(session_factory, ticker="NOPE", asset_class=AssetClass.COMMON_STOCK)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not found")

    result = await MarketIngest(_client(handler), session_factory).run(
        now=datetime(2026, 3, 5, tzinfo=UTC)
    )

    assert len(result.unresolved) == 1
    assert "does not cover" in result.unresolved[0].unresolved_reason


@pytest.mark.integration
async def test_a_close_is_also_written_as_a_quantitative_observation(session_factory):
    await _asset(session_factory, ticker="MP", asset_class=AssetClass.COMMON_STOCK)

    await _ingest(session_factory).run(now=datetime(2026, 3, 5, tzinfo=UTC), start=date(2026, 3, 1))

    async with session_factory() as session:
        rows = (await session.execute(select(QuantitativeObservation))).scalars().all()

    assert len(rows) == 3
    assert all(row.metric == "close" for row in rows)
    assert all(row.reported_vs_derived == "reported" for row in rows)
    # A re-fetch is a new observation of the same fact, not a restatement.
    assert all(row.restated is False for row in rows)


# --------------------------------------------------------------------------- #
# Vendor abstraction (#35) and the analytical layer (#36)
# --------------------------------------------------------------------------- #


def test_a_provider_declares_what_it_covers_rather_than_returning_empty():
    """An empty result is indistinguishable from a company with no
    fundamentals; a declaration is not (tech rec §19)."""
    from econiq_market import Facet, FacetUnavailableError, TIINGO_COVERAGE

    assert Facet.EQUITIES in TIINGO_COVERAGE.facets
    assert Facet.FX in TIINGO_COVERAGE.facets
    assert Facet.FUNDAMENTALS not in TIINGO_COVERAGE.facets

    TIINGO_COVERAGE.requires(Facet.EQUITIES)
    with pytest.raises(FacetUnavailableError):
        TIINGO_COVERAGE.requires(Facet.FUNDAMENTALS)


def test_every_missing_facet_carries_a_reason():
    """So a caller renders 'not sourced, because…' rather than an empty cell."""
    from econiq_market import TIINGO_COVERAGE

    named = {name for name, _ in TIINGO_COVERAGE.notes}
    assert {"fundamentals", "ownership", "commodities", "macro"} <= named
    assert all(reason for _, reason in TIINGO_COVERAGE.notes)


def test_the_client_satisfies_the_provider_protocol():
    from econiq_market import MarketDataProvider

    assert isinstance(TiingoClient("token"), MarketDataProvider)


@pytest.mark.integration
async def test_a_snapshot_is_immutable(session_factory, tmp_path):
    """A Parquet file that gets rewritten silently changes every result already
    computed from it (agent doc §20)."""
    from econiq_market import Warehouse

    warehouse = Warehouse(tmp_path)
    taken = datetime(2026, 8, 7, 12, tzinfo=UTC)
    await warehouse.export(session_factory, taken_at=taken)

    with pytest.raises(FileExistsError, match="immutable"):
        await warehouse.export(session_factory, taken_at=taken)


@pytest.mark.integration
async def test_prices_reach_duckdb_with_both_clocks(session_factory, tmp_path):
    from econiq_market import Warehouse

    await _asset(session_factory, ticker="MP", asset_class=AssetClass.COMMON_STOCK)
    await _ingest(session_factory).run(now=datetime(2026, 3, 5, tzinfo=UTC), start=date(2026, 3, 1))

    warehouse = Warehouse(tmp_path)
    result = await warehouse.export(session_factory)

    assert result.rows["prices"] == 3
    connection = warehouse.connect()
    columns = {row[0] for row in connection.execute("DESCRIBE prices").fetchall()}
    # Both clocks survive the export, or a backtest cannot be point-in-time.
    assert {"observed_at", "recorded_at", "close", "adj_close"} <= columns
    assert connection.execute("SELECT count(*) FROM prices").fetchone()[0] == 3


@pytest.mark.integration
async def test_a_point_in_time_read_over_parquet_ignores_later_revisions(session_factory, tmp_path):
    """The mistake that makes a backtest look brilliant: handing every past day
    the adjustment factors that only exist after later corporate actions."""
    from econiq_market import Warehouse, as_known_at

    await _asset(session_factory, ticker="MP", asset_class=AssetClass.COMMON_STOCK)
    first = datetime(2026, 3, 5, tzinfo=UTC)
    later = datetime(2026, 4, 5, tzinfo=UTC)
    await _ingest(session_factory).run(now=first, start=date(2026, 3, 1))
    await _ingest(session_factory, PRICES.replace("50.75", "25.375")).run(
        now=later, start=date(2026, 3, 1)
    )

    warehouse = Warehouse(tmp_path)
    await warehouse.export(session_factory)
    prices = warehouse.frame("prices")

    as_then = as_known_at(prices, first + timedelta(days=1))
    as_now = as_known_at(prices, later + timedelta(days=1))

    march_2 = datetime(2026, 3, 2, tzinfo=UTC)
    then_value = as_then.filter(pl_col_eq("observed_at", march_2))["adj_close"][0]
    now_value = as_now.filter(pl_col_eq("observed_at", march_2))["adj_close"][0]
    assert then_value == 50.75
    assert now_value == 25.375


def pl_col_eq(column: str, value):  # noqa: ANN001, ANN201 - test helper
    import polars as pl

    return pl.col(column) == value


@pytest.mark.integration
async def test_an_empty_table_still_gets_a_file(session_factory, tmp_path):
    """A missing file and an empty one look the same to a glob, and a notebook
    that silently skips a table is worse than one that reads zero rows."""
    from econiq_market import Warehouse

    warehouse = Warehouse(tmp_path)
    result = await warehouse.export(session_factory)

    assert result.rows["prices"] == 0
    assert result.snapshot.table("prices").exists()
    assert (result.snapshot.path / "MANIFEST.txt").exists()
