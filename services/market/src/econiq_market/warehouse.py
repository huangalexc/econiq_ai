"""The analytical layer (issue #36; tech rec §18).

Postgres is the system of record and stays that way. This is the research path
beside it: Parquet on disk, DuckDB over the top, Polars for the dataframe work.

The reason for a second copy is that the two workloads want opposite things.
Postgres serves the terminal — small point reads, strict transactions, one
Process at a time. The analog engine wants every price bar for two thousand
tickers across fifteen years, scanned twice. Running that against the operational
database means a research query can slow the product down, which quietly teaches
people not to run research queries.

**Exports are point-in-time by construction.** Each snapshot is written to a
directory named for the instant it was taken and never modified afterwards. That
is not filesystem hygiene: agent doc §20 requires a historical analysis to see
only what was knowable at the time, and a Parquet file that gets rewritten when
new data arrives silently changes every result computed from it. A dataset you
cannot re-derive is not reproducible, whatever the notebook says.

The `recorded_at` column travels into Parquet for the same reason it exists in
Postgres — Tiingo revises adjusted closes retroactively (#77), so "the price on
3 March" is a different number depending on when it was fetched, and the
snapshot must keep both clocks or a backtest reads the future.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
from econiq_data_models import AssetState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("econiq.market.warehouse")

#: Where snapshots live. A local path in development; an S3 prefix in
#: deployment, which DuckDB reads natively (tech rec §18's S3 → Parquet → DuckDB).
DEFAULT_ROOT = Path("research/datasets")

#: Bumped when a table's columns change. A snapshot directory carries it, so a
#: notebook pinned to v1 keeps reading v1 rather than silently getting new
#: columns and a different answer.
SCHEMA_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One immutable export."""

    root: Path
    taken_at: datetime
    schema_version: str = SCHEMA_VERSION

    @property
    def path(self) -> Path:
        stamp = self.taken_at.strftime("%Y%m%dT%H%M%SZ")
        return self.root / self.schema_version / stamp

    def table(self, name: str) -> Path:
        return self.path / f"{name}.parquet"

    @property
    def label(self) -> str:
        """What a notebook cites. Reproducibility begins with a name."""
        return f"{self.schema_version}/{self.taken_at.strftime('%Y%m%dT%H%M%SZ')}"


@dataclass(frozen=True, slots=True)
class ExportResult:
    snapshot: Snapshot
    rows: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.rows.values())


class Warehouse:
    """Exports Postgres to Parquet, and queries Parquet with DuckDB."""

    def __init__(self, root: Path | str = DEFAULT_ROOT) -> None:
        self.root = Path(root)

    # -- export ---------------------------------------------------------- #

    async def export(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        taken_at: datetime | None = None,
    ) -> ExportResult:
        """Write a new immutable snapshot.

        Never overwrites. An export at the same second as an existing one is a
        mistake worth failing on rather than a merge worth guessing at.
        """
        snapshot = Snapshot(root=self.root, taken_at=taken_at or datetime.now(UTC))
        if snapshot.path.exists():
            raise FileExistsError(
                f"snapshot {snapshot.label} already exists; snapshots are immutable"
            )
        snapshot.path.mkdir(parents=True)

        rows: dict[str, int] = {}
        async with session_factory() as session:
            rows["prices"] = _write(snapshot.table("prices"), await _prices(session))
        (snapshot.path / "MANIFEST.txt").write_text(
            "\n".join(
                [
                    f"snapshot: {snapshot.label}",
                    f"taken_at: {snapshot.taken_at.isoformat()}",
                    f"schema_version: {snapshot.schema_version}",
                    "",
                    "Immutable. Rows carry observed_at (the trading day) and",
                    "recorded_at (when the system learned it). A point-in-time",
                    "read filters on both — see agent doc §20.",
                    "",
                    *[f"{name}: {count} rows" for name, count in sorted(rows.items())],
                ]
            )
            + "\n"
        )
        logger.info("wrote snapshot %s (%d rows)", snapshot.label, sum(rows.values()))
        return ExportResult(snapshot=snapshot, rows=rows)

    # -- query ----------------------------------------------------------- #

    def latest(self) -> Snapshot | None:
        base = self.root / SCHEMA_VERSION
        if not base.exists():
            return None
        stamps = sorted(p.name for p in base.iterdir() if p.is_dir())
        if not stamps:
            return None
        return Snapshot(
            root=self.root,
            taken_at=datetime.strptime(stamps[-1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
        )

    def connect(self, snapshot: Snapshot | None = None) -> duckdb.DuckDBPyConnection:
        """A DuckDB connection with the snapshot's tables registered as views.

        Read-only by construction: the views point at Parquet files, and DuckDB
        cannot write through them. A research session that could mutate the
        dataset it is analysing would make every result unreproducible.
        """
        chosen = snapshot or self.latest()
        if chosen is None:
            raise FileNotFoundError(f"no snapshot under {self.root}. Run an export first.")
        connection = duckdb.connect(":memory:")
        for table in chosen.path.glob("*.parquet"):
            # DuckDB cannot bind a parameter inside CREATE VIEW, so the path is
            # inlined. Safe because it is a path this process just wrote, not
            # caller input, and the quote doubling covers the pathological
            # directory name rather than an untrusted one.
            literal = str(table).replace("'", "''")
            connection.execute(
                f"CREATE VIEW {table.stem} AS SELECT * FROM read_parquet('{literal}')"
            )
        return connection

    def frame(self, table: str, snapshot: Snapshot | None = None) -> pl.DataFrame:
        """One table as a Polars frame (tech rec §16: Polars by default)."""
        chosen = snapshot or self.latest()
        if chosen is None:
            raise FileNotFoundError(f"no snapshot under {self.root}")
        return pl.read_parquet(chosen.table(table))


def as_known_at(prices: pl.DataFrame, moment: datetime) -> pl.DataFrame:
    """Prices as they were understood at ``moment`` (agent doc §20).

    Two filters, and both matter. `observed_at <= moment` bounds which trading
    days existed. `recorded_at <= moment` bounds which *version* of each day is
    used — and dropping that second one is the mistake that makes a backtest
    look brilliant, because it hands every past day the adjustment factors that
    only exist after later splits and dividends.
    """
    return (
        prices.filter((pl.col("observed_at") <= moment) & (pl.col("recorded_at") <= moment))
        .sort(["asset_id", "observed_at", "recorded_at"])
        .group_by(["asset_id", "observed_at"])
        .last()
    )


async def _prices(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(AssetState))).scalars().all()
    return [
        {
            "asset_id": str(row.asset_id),
            "observed_at": row.observed_at,
            "recorded_at": row.recorded_at,
            "currency": row.currency,
            "close": _float(row.technical.get("close")),
            "adj_close": _float(row.technical.get("adj_close")),
            "volume": _float(row.technical.get("volume")),
            "dividend": _float((row.market_structure or {}).get("dividend")),
            "split_factor": _float((row.market_structure or {}).get("split_factor")),
            "source": row.source,
        }
        for row in rows
    ]


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _write(path: Path, rows: Sequence[dict[str, Any]]) -> int:
    if not rows:
        # An empty table still gets a file. A missing file and an empty one look
        # the same to a glob, and a notebook that silently skips a table is
        # worse than one that reads zero rows.
        pl.DataFrame(
            schema={
                "asset_id": pl.Utf8,
                "observed_at": pl.Datetime(time_zone="UTC"),
                "recorded_at": pl.Datetime(time_zone="UTC"),
                "currency": pl.Utf8,
                "close": pl.Float64,
                "adj_close": pl.Float64,
                "volume": pl.Float64,
                "dividend": pl.Float64,
                "split_factor": pl.Float64,
                "source": pl.Utf8,
            }
        ).write_parquet(path)
        return 0
    frame = pl.DataFrame(rows)
    # Postgres hands back `Etc/UTC` and Python's `datetime.UTC` is `UTC`; Polars
    # treats them as different dtypes and refuses to compare them. Normalised on
    # write so every snapshot has one timezone and a filter written against one
    # export works against all of them.
    frame = frame.with_columns(
        [
            pl.col(column).dt.convert_time_zone("UTC")
            for column in ("observed_at", "recorded_at")
            if column in frame.columns
        ]
    )
    frame.write_parquet(path)
    return frame.height
