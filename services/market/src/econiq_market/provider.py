"""The market-data vendor abstraction (issue #35; tech rec §19).

§19 asks for a `MarketDataProvider` with facets for equities, fundamentals,
ownership, options, commodities, FX and macro, and says plainly: *"don't couple
your internal Asset model to a specific vendor's schema."*

The protocol below is that shape, and Tiingo implements two of its seven facets.
The other five are not stubbed. A provider that answers `fundamentals()` with an
empty list is indistinguishable from a company with no fundamentals, and every
consumer downstream would have to know which vendor it was talking to to tell —
which is the coupling §19 exists to prevent. Instead a provider *declares* what
it covers, and asking for a facet it does not have raises.

**Why a declaration rather than duck typing.** The historical engine's whole
premise is comparing a current episode against past ones, and a comparison built
from four facets on one Asset and two on another is not a comparison. Coverage
has to be inspectable before the analysis runs, not discovered from a gap in the
output.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol, runtime_checkable

from econiq_market.client import FxBar, PriceBar, UniverseEntry


class Facet(StrEnum):
    """The data families §19 names. A provider declares which it serves."""

    EQUITIES = "equities"
    FUNDAMENTALS = "fundamentals"
    OWNERSHIP = "ownership"
    OPTIONS = "options"
    COMMODITIES = "commodities"
    FX = "fx"
    MACRO = "macro"


class FacetUnavailableError(RuntimeError):
    """Asked a provider for a facet it does not serve.

    An exception rather than an empty result, because empty is a legitimate
    answer — a company genuinely may have no ownership filings in a window — and
    conflating "we cannot see this" with "there is nothing here" is how a gap in
    coverage becomes a finding about the world.
    """

    def __init__(self, vendor: str, facet: Facet) -> None:
        super().__init__(f"{vendor} does not serve {facet.value}")
        self.vendor = vendor
        self.facet = facet


@dataclass(frozen=True, slots=True)
class Coverage:
    """What a vendor can answer, and over what."""

    vendor: str
    facets: frozenset[Facet]
    earliest: date | None = None
    #: Named gaps, so a caller can render "not sourced" with a reason rather
    #: than an empty cell (the pattern #75's comparison matrix already uses).
    notes: tuple[tuple[str, str], ...] = ()

    def requires(self, facet: Facet) -> None:
        if facet not in self.facets:
            raise FacetUnavailableError(self.vendor, facet)


@runtime_checkable
class MarketDataProvider(Protocol):
    """The canonical interface. Nothing above this layer names a vendor."""

    @property
    def coverage(self) -> Coverage: ...

    async def universe(self) -> Sequence[UniverseEntry]:
        """Every symbol the vendor knows, including delisted ones.

        Survivorship-freedom is a property of this method, and it is why the
        return type keeps `end_date`. A universe that quietly drops delisted
        names produces backtests that beat the market for a reason nobody
        notices (agent doc §19 lists survivorship bias as a fault to inject).
        """
        ...

    async def daily_prices(
        self, symbol: str, *, start: date, end: date | None = None
    ) -> Sequence[PriceBar]: ...

    async def fx_prices(
        self, pair: str, *, start: date, frequency: str = "1day"
    ) -> Sequence[FxBar]: ...


#: What Tiingo actually serves, and what it does not.
#:
#: The notes are the honest part. Phase 2's analog engine needs fundamentals to
#: compare past episodes on anything but price, and the gap is recorded here
#: rather than discovered when a comparison comes back thin.
TIINGO_COVERAGE = Coverage(
    vendor="tiingo",
    facets=frozenset({Facet.EQUITIES, Facet.FX}),
    # Tiingo's daily history reaches the 1960s for some US listings; the
    # practical floor for a broad universe is around 1990.
    earliest=date(1990, 1, 1),
    notes=(
        (
            "fundamentals",
            "Available on a paid Tiingo tier this deployment does not have. "
            "Blocks growth, margins, valuation and balance-sheet comparison (#75).",
        ),
        (
            "ownership",
            "No source. Blocks crowding and institutional-positioning analysis.",
        ),
        (
            "commodities",
            "Tiingo does not price them. The reference universe holds ~22; FRED "
            "is the likely source and needs its own provider.",
        ),
        (
            "macro",
            "No source. FRED would serve this alongside commodities.",
        ),
        (
            "options",
            "Out of scope for V1 — the ontology expresses theses through "
            "the underlying asset only (§14).",
        ),
    ),
)
