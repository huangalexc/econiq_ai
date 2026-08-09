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
from econiq_market.distribution import (
    INDICATIVE_BELOW,
    DispersionNote,
    Distribution,
    across_horizons,
    dispersion,
    summarise,
)
from econiq_market.ingest import (
    DEFAULT_BACKFILL,
    SOURCE,
    IngestResult,
    MarketIngest,
    SymbolResult,
    latest_known_at,
)
from econiq_market.outcomes import (
    HORIZONS,
    Episode,
    Outcome,
    compute,
    episodes_from,
    frozen_before,
)
from econiq_market.pointintime import (
    REQUIRED_COLUMNS,
    LeakageError,
    LeakageFinding,
    Lens,
    assert_clean,
    inspect,
    lenses,
)
from econiq_market.provider import (
    TIINGO_COVERAGE,
    Coverage,
    Facet,
    FacetUnavailableError,
    MarketDataProvider,
)
from econiq_market.warehouse import (
    SCHEMA_VERSION,
    ExportResult,
    Snapshot,
    Warehouse,
    as_known_at,
)

__all__ = [
    "DEFAULT_BACKFILL",
    "HORIZONS",
    "INDICATIVE_BELOW",
    "REQUIRED_COLUMNS",
    "SCHEMA_VERSION",
    "SOURCE",
    "TIINGO_COVERAGE",
    "Coverage",
    "DispersionNote",
    "Distribution",
    "Episode",
    "ExportResult",
    "Facet",
    "FacetUnavailableError",
    "FxBar",
    "IngestResult",
    "LeakageError",
    "LeakageFinding",
    "Lens",
    "MarketDataProvider",
    "MarketIngest",
    "MissingTokenError",
    "Outcome",
    "PriceBar",
    "Snapshot",
    "SymbolNotCoveredError",
    "SymbolResult",
    "TiingoClient",
    "TiingoError",
    "UniverseEntry",
    "Warehouse",
    "across_horizons",
    "as_known_at",
    "assert_clean",
    "compute",
    "dispersion",
    "episodes_from",
    "frozen_before",
    "inspect",
    "latest_known_at",
    "lenses",
    "parse_fx_csv",
    "parse_price_csv",
    "parse_universe_csv",
    "parse_universe_zip",
    "summarise",
]
