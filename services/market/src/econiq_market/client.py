"""Tiingo client (issue #77).

Three endpoints: daily equity prices, FX prices, and the supported-ticker
universe. All return CSV or a zipped CSV, which is why this parses rather than
deserialises.

**The adjusted close is not a fact about a date.** Tiingo recomputes it whenever
a split or dividend occurs afterwards, so the adjusted close *for 3 March* is a
different number depending on when you ask. Agent doc §20 names this exactly —
"many financial datasets contain information that was revised after the original
observation date" — and it is the difference between a backtest and a fiction.

So :class:`PriceBar` carries both the raw close and the adjusted one, and the
ingest records when each was fetched. Storing only the adjusted close would make
every historical price silently reflect corporate actions the system could not
have known about, and nothing downstream would be able to tell.
"""

from __future__ import annotations

import csv
import io
import os
import zipfile
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from econiq_market.provider import Coverage

BASE_URL = "https://api.tiingo.com"
UNIVERSE_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"


class TiingoError(RuntimeError):
    """A request the caller cannot recover from by retrying."""


class MissingTokenError(TiingoError):
    """No API token. Raised at construction, not at request time.

    A client that constructs happily and fails on every call turns a
    configuration mistake into an intermittent-looking outage.
    """


@dataclass(frozen=True, slots=True)
class PriceBar:
    """One trading day.

    ``close`` and ``adj_close`` are both kept. The adjusted series is the one
    worth analysing and the raw one is the only one that is stable, so a
    point-in-time read needs both to tell whether a change is a price move or a
    corporate action applied after the fact.
    """

    symbol: str
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    adj_close: float | None
    adj_volume: float | None = None
    dividend: float = 0.0
    split_factor: float = 1.0

    @property
    def had_corporate_action(self) -> bool:
        """A day on which the adjustment factors for every earlier day changed."""
        return self.dividend != 0.0 or self.split_factor != 1.0


@dataclass(frozen=True, slots=True)
class FxBar:
    pair: str
    ts: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float


@dataclass(frozen=True, slots=True)
class UniverseEntry:
    ticker: str
    exchange: str | None
    asset_type: str | None
    price_currency: str | None
    start_date: date | None
    end_date: date | None

    @property
    def delisted(self) -> bool:
        """A ticker whose coverage has ended.

        Kept rather than filtered out. Dropping delisted names from the universe
        is how survivorship bias enters a system, and agent doc §19 lists it as
        a fault to inject for exactly that reason.
        """
        return self.end_date is not None


class TiingoClient:
    """Reads Tiingo. Does not decide what any of it means."""

    def __init__(
        self,
        token: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        resolved = token or os.getenv("TIINGO_API_TOKEN")
        if not resolved:
            raise MissingTokenError(
                "TIINGO_API_TOKEN is not set. The client refuses to start rather "
                "than failing on every request."
            )
        self._token = resolved
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> TiingoClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def coverage(self) -> Coverage:
        """What this vendor serves (tech rec §19).

        Declared rather than discovered. A caller asks before it analyses, so a
        thin comparison is a known limit rather than a surprise in the output.
        """
        from econiq_market.provider import TIINGO_COVERAGE

        return TIINGO_COVERAGE

    @property
    def http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise TiingoError("client used outside its context manager")
        return self._client

    async def daily_prices(
        self, ticker: str, *, start: date, end: date | None = None
    ) -> list[PriceBar]:
        params = {
            "startDate": start.isoformat(),
            "format": "csv",
            "token": self._token,
        }
        if end is not None:
            params["endDate"] = end.isoformat()
        text = await self._get(f"/tiingo/daily/{ticker}/prices", params)
        return list(parse_price_csv(ticker, text))

    async def fx_prices(self, pair: str, *, start: date, frequency: str = "1day") -> list[FxBar]:
        text = await self._get(
            f"/tiingo/fx/{pair}/prices",
            {
                "startDate": start.isoformat(),
                "resampleFreq": frequency,
                "format": "csv",
                "token": self._token,
            },
        )
        return list(parse_fx_csv(pair, text))

    async def universe(self) -> list[UniverseEntry]:
        """The supported-ticker list, which arrives as a zipped CSV."""
        response = await self.http.get(UNIVERSE_URL)
        if response.status_code != 200:
            raise TiingoError(f"universe download failed: {response.status_code}")
        return list(parse_universe_zip(response.content))

    async def _get(self, path: str, params: dict[str, str]) -> str:
        response = await self.http.get(f"{self._base_url}{path}", params=params)
        if response.status_code == 404:
            # Tiingo returns 404 for a symbol it does not cover, which is an
            # answer rather than an error: the caller records it unresolved.
            raise SymbolNotCoveredError(path.split("/")[-2])
        if response.status_code != 200:
            raise TiingoError(f"{response.status_code} from {path}: {response.text[:200]}")
        return response.text


class SymbolNotCoveredError(TiingoError):
    """Tiingo has no data for this symbol. Recorded, never guessed around."""

    def __init__(self, symbol: str) -> None:
        super().__init__(f"Tiingo does not cover {symbol}")
        self.symbol = symbol


# --------------------------------------------------------------------------- #
# Parsing. Separated from the client so it is testable without a network.
# --------------------------------------------------------------------------- #


def _number(row: dict[str, str], key: str) -> float | None:
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_price_csv(symbol: str, text: str) -> Iterable[PriceBar]:
    for row in csv.DictReader(io.StringIO(text)):
        raw_date = (row.get("date") or "").strip()
        close = _number(row, "close")
        if not raw_date or close is None:
            # A row with no close is not a trading day we can use. Skipped
            # rather than defaulted: a zero price would propagate into every
            # return calculation downstream.
            continue
        yield PriceBar(
            symbol=symbol,
            trade_date=date.fromisoformat(raw_date[:10]),
            open=_number(row, "open"),
            high=_number(row, "high"),
            low=_number(row, "low"),
            close=close,
            volume=_number(row, "volume"),
            adj_close=_number(row, "adjClose"),
            adj_volume=_number(row, "adjVolume"),
            dividend=_number(row, "divCash") or 0.0,
            split_factor=_number(row, "splitFactor") or 1.0,
        )


def parse_fx_csv(pair: str, text: str) -> Iterable[FxBar]:
    for row in csv.DictReader(io.StringIO(text)):
        raw = (row.get("date") or "").strip()
        close = _number(row, "close")
        if not raw or close is None:
            continue
        yield FxBar(
            pair=pair,
            ts=datetime.fromisoformat(raw.replace("Z", "+00:00")),
            open=_number(row, "open"),
            high=_number(row, "high"),
            low=_number(row, "low"),
            close=close,
        )


def parse_universe_zip(payload: bytes) -> Iterable[UniverseEntry]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".csv"))
        with archive.open(name) as handle:
            text = handle.read().decode("utf-8", errors="replace")
    yield from parse_universe_csv(text)


def parse_universe_csv(text: str) -> Iterable[UniverseEntry]:
    for row in csv.DictReader(io.StringIO(text)):
        ticker = (row.get("ticker") or "").strip()
        if not ticker:
            continue
        yield UniverseEntry(
            ticker=ticker.upper(),
            exchange=(row.get("exchange") or "").strip() or None,
            asset_type=(row.get("assetType") or "").strip() or None,
            price_currency=(row.get("priceCurrency") or "").strip() or None,
            start_date=_date(row.get("startDate")),
            end_date=_date(row.get("endDate")),
        )


def _date(raw: str | None) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


async def paginate(bars: Sequence[PriceBar]) -> AsyncIterator[PriceBar]:
    for bar in bars:
        yield bar
