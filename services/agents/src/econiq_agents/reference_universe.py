"""The non-equity reference universe.

Identifier resolution is deterministic work (agent doc §2.3). For equities that
eventually means a vendor security master; for commodities and currencies it
means a small closed universe that can simply be enumerated — which makes those
the *easiest* asset classes to resolve correctly, not the hardest.

This exists because a Commodity Supply Cycle is frequently expressed most
cleanly by the commodity itself rather than by a producer's equity, and a
Process driven by monetary or trade policy may be expressed in a currency. An
Asset Discovery step that could only resolve tickers would silently convert
every thesis into an equity thesis — not because that is the right expression,
but because it is the only one the code could name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from econiq_ontology import AssetClass

_NORMALIZE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class ReferenceInstrument:
    """A non-equity instrument the system can name without a vendor feed."""

    name: str
    asset_class: AssetClass
    aliases: tuple[str, ...] = ()
    commodity_code: str | None = None
    contract_code: str | None = None
    benchmark: str | None = None
    currency_pair: str | None = None
    currency_code: str | None = None
    country: str | None = None
    quote_currency: str | None = None


#: Precious and industrial metals, energy and agriculture. Not exhaustive — the
#: point is that the common expressions of a commodity cycle resolve without a
#: model being asked to assert an identifier.
COMMODITIES: tuple[ReferenceInstrument, ...] = (
    ReferenceInstrument(
        name="Gold",
        asset_class=AssetClass.COMMODITY,
        aliases=("gold", "xau", "gold bullion", "gold spot"),
        commodity_code="XAU",
        contract_code="COMEX:GC",
        benchmark="LBMA Gold PM",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Silver",
        asset_class=AssetClass.COMMODITY,
        aliases=("silver", "xag", "silver bullion", "silver spot"),
        commodity_code="XAG",
        contract_code="COMEX:SI",
        benchmark="LBMA Silver",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Platinum",
        asset_class=AssetClass.COMMODITY,
        aliases=("platinum", "xpt"),
        commodity_code="XPT",
        contract_code="NYMEX:PL",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Palladium",
        asset_class=AssetClass.COMMODITY,
        aliases=("palladium", "xpd"),
        commodity_code="XPD",
        contract_code="NYMEX:PA",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Copper",
        asset_class=AssetClass.COMMODITY,
        aliases=("copper", "hg", "lme copper", "copper cathode"),
        commodity_code="HG",
        contract_code="COMEX:HG",
        benchmark="LME Copper Grade A",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Aluminium",
        asset_class=AssetClass.COMMODITY,
        aliases=("aluminium", "aluminum", "lme aluminium"),
        commodity_code="ALU",
        benchmark="LME Aluminium",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Nickel",
        asset_class=AssetClass.COMMODITY,
        aliases=("nickel", "lme nickel"),
        commodity_code="NI",
        benchmark="LME Nickel",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Zinc",
        asset_class=AssetClass.COMMODITY,
        aliases=("zinc", "lme zinc"),
        commodity_code="ZN",
        benchmark="LME Zinc",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Lithium carbonate",
        asset_class=AssetClass.COMMODITY,
        aliases=("lithium", "lithium carbonate", "battery-grade lithium"),
        commodity_code="LIC",
        benchmark="Fastmarkets Lithium Carbonate CIF",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Cobalt",
        asset_class=AssetClass.COMMODITY,
        aliases=("cobalt", "lme cobalt"),
        commodity_code="CO",
        benchmark="LME Cobalt",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Uranium",
        asset_class=AssetClass.COMMODITY,
        aliases=("uranium", "u3o8", "yellowcake"),
        commodity_code="U3O8",
        benchmark="UxC U3O8 Spot",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Neodymium-praseodymium oxide",
        asset_class=AssetClass.COMMODITY,
        aliases=("ndpr", "neodymium", "praseodymium", "ndpr oxide", "rare earth oxide"),
        commodity_code="NDPR",
        benchmark="Asian Metal NdPr Oxide",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Iron ore",
        asset_class=AssetClass.COMMODITY,
        aliases=("iron ore", "iodex", "62% fe"),
        commodity_code="TIO",
        benchmark="Platts IODEX 62% Fe",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="WTI crude oil",
        asset_class=AssetClass.COMMODITY,
        aliases=("wti", "crude", "crude oil", "west texas intermediate"),
        commodity_code="CL",
        contract_code="NYMEX:CL",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Brent crude oil",
        asset_class=AssetClass.COMMODITY,
        aliases=("brent", "brent crude", "north sea brent"),
        commodity_code="CO",
        contract_code="ICE:B",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Henry Hub natural gas",
        asset_class=AssetClass.COMMODITY,
        aliases=("natural gas", "henry hub", "us natural gas"),
        commodity_code="NG",
        contract_code="NYMEX:NG",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="TTF natural gas",
        asset_class=AssetClass.COMMODITY,
        aliases=("ttf", "dutch ttf", "european gas", "eu natural gas"),
        commodity_code="TTF",
        contract_code="ICE:TFM",
        quote_currency="EUR",
    ),
    ReferenceInstrument(
        name="Thermal coal",
        asset_class=AssetClass.COMMODITY,
        aliases=("thermal coal", "newcastle coal", "api2"),
        commodity_code="COAL",
        benchmark="Newcastle 6000 kcal",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Wheat",
        asset_class=AssetClass.COMMODITY,
        aliases=("wheat", "chicago wheat"),
        commodity_code="ZW",
        contract_code="CBOT:ZW",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Corn",
        asset_class=AssetClass.COMMODITY,
        aliases=("corn", "maize"),
        commodity_code="ZC",
        contract_code="CBOT:ZC",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Soybeans",
        asset_class=AssetClass.COMMODITY,
        aliases=("soybeans", "soybean", "soya"),
        commodity_code="ZS",
        contract_code="CBOT:ZS",
        quote_currency="USD",
    ),
    ReferenceInstrument(
        name="Lumber",
        asset_class=AssetClass.COMMODITY,
        aliases=("lumber", "timber", "softwood lumber"),
        commodity_code="LBR",
        contract_code="CME:LBR",
        quote_currency="USD",
    ),
)


#: Major and commodity-linked currency pairs. Quoted against USD except where
#: convention says otherwise, which matters because the sign of an exposure
#: depends on which side of the pair the Process pushes.
CURRENCIES: tuple[ReferenceInstrument, ...] = (
    ReferenceInstrument(
        name="US dollar",
        asset_class=AssetClass.CURRENCY,
        aliases=("usd", "us dollar", "dollar", "dxy"),
        currency_code="USD",
    ),
    ReferenceInstrument(
        name="EUR/USD",
        asset_class=AssetClass.CURRENCY,
        aliases=("eurusd", "eur/usd", "euro"),
        currency_pair="EURUSD",
        currency_code="EUR",
    ),
    ReferenceInstrument(
        name="USD/JPY",
        asset_class=AssetClass.CURRENCY,
        aliases=("usdjpy", "usd/jpy", "yen", "japanese yen"),
        currency_pair="USDJPY",
        currency_code="JPY",
    ),
    ReferenceInstrument(
        name="GBP/USD",
        asset_class=AssetClass.CURRENCY,
        aliases=("gbpusd", "gbp/usd", "sterling", "pound"),
        currency_pair="GBPUSD",
        currency_code="GBP",
    ),
    ReferenceInstrument(
        name="USD/CNY",
        asset_class=AssetClass.CURRENCY,
        aliases=("usdcny", "usd/cny", "renminbi", "yuan", "usdcnh"),
        currency_pair="USDCNY",
        currency_code="CNY",
    ),
    ReferenceInstrument(
        name="AUD/USD",
        asset_class=AssetClass.CURRENCY,
        aliases=("audusd", "aud/usd", "australian dollar", "aussie"),
        currency_pair="AUDUSD",
        currency_code="AUD",
    ),
    ReferenceInstrument(
        name="USD/CAD",
        asset_class=AssetClass.CURRENCY,
        aliases=("usdcad", "usd/cad", "canadian dollar", "loonie"),
        currency_pair="USDCAD",
        currency_code="CAD",
    ),
    ReferenceInstrument(
        name="USD/CHF",
        asset_class=AssetClass.CURRENCY,
        aliases=("usdchf", "usd/chf", "swiss franc"),
        currency_pair="USDCHF",
        currency_code="CHF",
    ),
    ReferenceInstrument(
        name="USD/MXN",
        asset_class=AssetClass.CURRENCY,
        aliases=("usdmxn", "usd/mxn", "mexican peso"),
        currency_pair="USDMXN",
        currency_code="MXN",
    ),
    ReferenceInstrument(
        name="USD/BRL",
        asset_class=AssetClass.CURRENCY,
        aliases=("usdbrl", "usd/brl", "brazilian real"),
        currency_pair="USDBRL",
        currency_code="BRL",
    ),
    ReferenceInstrument(
        name="USD/INR",
        asset_class=AssetClass.CURRENCY,
        aliases=("usdinr", "usd/inr", "indian rupee"),
        currency_pair="USDINR",
        currency_code="INR",
    ),
    ReferenceInstrument(
        name="USD/KRW",
        asset_class=AssetClass.CURRENCY,
        aliases=("usdkrw", "usd/krw", "korean won"),
        currency_pair="USDKRW",
        currency_code="KRW",
    ),
)


REFERENCE_UNIVERSE: tuple[ReferenceInstrument, ...] = COMMODITIES + CURRENCIES


def _normalize(value: str) -> str:
    return _NORMALIZE.sub(" ", value.strip().lower()).strip()


_BY_ALIAS: dict[str, ReferenceInstrument] = {}
for _instrument in REFERENCE_UNIVERSE:
    for _alias in (_instrument.name, *_instrument.aliases):
        _BY_ALIAS.setdefault(_normalize(_alias), _instrument)
    for _code in (
        _instrument.commodity_code,
        _instrument.currency_pair,
        _instrument.contract_code,
    ):
        if _code:
            _BY_ALIAS.setdefault(_normalize(_code), _instrument)


def lookup(name_or_code: str | None) -> ReferenceInstrument | None:
    """Resolve a commodity or currency by name, alias or code.

    Exact-match only. A fuzzy match here would let "copper mining" resolve to
    the copper price, which is a different Asset with a different exposure.
    """
    if not name_or_code:
        return None
    return _BY_ALIAS.get(_normalize(name_or_code))


def resolvable_names(asset_class: AssetClass | None = None) -> tuple[str, ...]:
    """Instrument names to show the discovery agent.

    A model cannot propose gold as an expression of a strategic-minerals Process
    if it does not know the system can name gold.
    """
    return tuple(
        instrument.name
        for instrument in REFERENCE_UNIVERSE
        if asset_class is None or instrument.asset_class is asset_class
    )


NON_EQUITY_CLASSES = frozenset(
    {AssetClass.COMMODITY, AssetClass.CURRENCY, AssetClass.BOND, AssetClass.INDEX}
)
