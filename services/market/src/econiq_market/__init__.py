"""Market data ingestion (issue #77).

Tiingo for equities, ETFs and FX. Commodities are not covered and are recorded
as unresolved rather than proxied, because a proxy relationship that is implied
rather than stored is the kind of silent substitution the Asset layer exists to
prevent.

The whole package turns on one distinction: a price says what was true on a
trading day, and separately when we learned it. Tiingo revises adjusted closes
retroactively, so a system that stores only "the price on 3 March" is storing a
number that changes — and a backtest reading it would be reading the future.
"""

from econiq_market.client import (
    FxBar,
    MissingTokenError,
    PriceBar,
    SymbolNotCoveredError,
    TiingoClient,
    TiingoError,
    UniverseEntry,
    parse_fx_csv,
    parse_price_csv,
    parse_universe_csv,
    parse_universe_zip,
)
from econiq_market.ingest import (
    DEFAULT_BACKFILL,
    SOURCE,
    IngestResult,
    MarketIngest,
    SymbolResult,
    latest_known_at,
)

__all__ = [
    "DEFAULT_BACKFILL",
    "SOURCE",
    "FxBar",
    "IngestResult",
    "MarketIngest",
    "MissingTokenError",
    "PriceBar",
    "SymbolNotCoveredError",
    "SymbolResult",
    "TiingoClient",
    "TiingoError",
    "UniverseEntry",
    "latest_known_at",
    "parse_fx_csv",
    "parse_price_csv",
    "parse_universe_csv",
    "parse_universe_zip",
]
