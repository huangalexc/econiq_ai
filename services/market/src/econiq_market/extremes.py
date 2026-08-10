"""Extreme-opportunity pattern search (issue #46; ui_concept §17).

§17 opens by saying what this is not: *"this should not be implemented as a
simple stock similarity search."* The chain it asks for runs

    historical extreme winner → archetype → State → characteristic
    configuration → current Process search → candidate Assets

which is a search over *configurations*, not over companies. The difference is
the whole feature. Finding companies that look like NVIDIA finds semiconductor
companies. Finding Processes whose configuration resembles the one that preceded
NVIDIA finds something worth reading.

**Half of that chain is not available yet.** Identifying historical extreme
outcomes needs prices, which exist. Attributing them to an archetype and a State
needs the historical Process timelines of #37, which need the document archive.
So :class:`Configuration` has the Process slots and they are explicitly empty,
with the reason attached — rather than the search quietly degrading into the
stock-similarity thing §17 told us not to build.

**Every output carries a review flag.** Agent doc §23 asks for human review
where errors have large downstream consequences, and tail-opportunity output is
the clearest case in the product: it is the screen most likely to be read as a
recommendation and the one where a false positive is most expensive. The flag is
a field on the result rather than a note in the UI, so it cannot be dropped by a
client that renders the table its own way.

The framing is not decoration either. §17 says this is "pattern discovery, not a
promise of future 10x returns", and :meth:`PatternMatch.caveat` generates that
sentence next to every row — because a table of ranked opportunities reads as a
recommendation unless something on the row says otherwise.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from econiq_market.outcomes import Outcome

#: What counts as extreme. A multiple rather than a percentile, because a
#: percentile of a small sample finds its own top decile however ordinary that
#: decile is — and the whole point is to study genuinely rare outcomes.
EXTREME_MULTIPLE = 3.0

#: The horizon extremes are judged over. Shorter windows catch noise; §36's
#: 24-month horizon is where a Process thesis would have played out.
EXTREME_HORIZON = "24m"

#: Below this many historical extremes, a "characteristic configuration" is one
#: or two anecdotes with a pattern drawn around them.
MIN_EXAMPLES = 5


@dataclass(frozen=True, slots=True)
class Configuration:
    """What a Process looked like before an extreme outcome.

    The Process fields are the point of §17's chain and are currently
    unpopulated. They are present rather than omitted so the shape of the answer
    is visible, and so the day #37 lands nothing above this has to change.
    """

    archetype: str | None = None
    state: str | None = None
    #: Process features at the observation — evidence acceleration, bottleneck
    #: severity, capability breadth. All from #37.
    process_features: dict[str, float] = field(default_factory=dict)
    #: What price alone can say about the moment.
    market_features: dict[str, float] = field(default_factory=dict)

    @property
    def has_process_context(self) -> bool:
        return self.archetype is not None and self.state is not None

    @property
    def missing(self) -> tuple[str, ...]:
        absent = []
        if self.archetype is None:
            absent.append("archetype")
        if self.state is None:
            absent.append("state")
        if not self.process_features:
            absent.append("process_features")
        return tuple(absent)


@dataclass(frozen=True, slots=True)
class ExtremeOutcome:
    """A historical outcome large enough to be worth studying."""

    outcome: Outcome
    horizon: str
    multiple: float
    configuration: Configuration

    @property
    def asset_id(self) -> str:
        return self.outcome.episode.asset_id


@dataclass(frozen=True, slots=True)
class PatternMatch:
    """A current Process whose configuration resembles a historical one.

    Not an opportunity, and not ranked against a return. `analog_strength` is
    how closely the configurations resemble each other and says nothing about
    what follows — which is exactly what §17 asks the screen to communicate and
    what a ranked table communicates the opposite of unless told to.
    """

    process_id: str
    process_name: str
    archetype: str | None
    state: str | None
    evidence_strength: float | None
    analog_strength: float
    based_on: int
    #: Agent doc §23. A field rather than a UI convention, so a client cannot
    #: render the table without it.
    requires_human_review: bool = True

    def caveat(self) -> str:
        """§17's framing, generated per row rather than written once in a header.

        A header is read on arrival and forgotten by the third row; this sits on
        the row a reader is actually looking at.
        """
        basis = (
            f"{self.based_on} historical configuration(s)"
            if self.based_on
            else "no historical configurations"
        )
        head = (
            f"Pattern discovery from {basis}. This is a structural resemblance, "
            "not a forecast and not a promise of outsized returns."
        )
        if self.based_on < MIN_EXAMPLES:
            head += f" Fewer than {MIN_EXAMPLES} examples: closer to an anecdote than to a pattern."
        return head


@dataclass(frozen=True, slots=True)
class SearchResult:
    matches: list[PatternMatch] = field(default_factory=list)
    extremes_found: int = 0
    #: Why the search is thinner than §17 describes.
    unavailable: tuple[tuple[str, str], ...] = (
        (
            "historical_process_context",
            "Extreme outcomes can be identified from prices, but attributing them "
            "to an archetype and a State needs the historical Process timelines "
            "of #37, which need the document archive. Without them this is a "
            "search over market configurations rather than over Process "
            "configurations, which is a weaker question than ui_concept §17 asks.",
        ),
    )

    @property
    def is_configuration_search(self) -> bool:
        """False while the Process half is missing — stated, not implied."""
        return all(match.archetype is not None for match in self.matches) and bool(self.matches)


def find_extremes(
    outcomes: Sequence[Outcome],
    *,
    horizon: str = EXTREME_HORIZON,
    multiple: float = EXTREME_MULTIPLE,
    configurations: dict[str, Configuration] | None = None,
) -> list[ExtremeOutcome]:
    """Historical outcomes at or above ``multiple``.

    An absolute threshold rather than a top-decile cut. A percentile finds its
    own top decile in any sample, however unremarkable that decile is, and the
    point of this search is that the examples were genuinely extreme.
    """
    found: list[ExtremeOutcome] = []
    for outcome in outcomes:
        value = outcome.returns.get(horizon)
        if value is None or value < multiple - 1.0:
            continue
        key = f"{outcome.episode.asset_id}@{outcome.episode.observed_at.isoformat()}"
        found.append(
            ExtremeOutcome(
                outcome=outcome,
                horizon=horizon,
                multiple=1.0 + value,
                configuration=(configurations or {}).get(key, Configuration()),
            )
        )
    found.sort(key=lambda item: item.multiple, reverse=True)
    return found


def search(
    extremes: Sequence[ExtremeOutcome],
    current: Sequence[tuple[str, str, str | None, str | None, float | None]],
) -> SearchResult:
    """Current Processes resembling the configurations that preceded extremes.

    ``current`` is ``(process_id, name, archetype, state, evidence_strength)``.

    Resemblance is computed over archetype and State, which is §17's chain. With
    no historical Process context the analog strength is zero for every row and
    the result says so — a search that returned confident scores from an absent
    half would be the stock-similarity search §17 opens by ruling out.
    """
    with_context = [item for item in extremes if item.configuration.has_process_context]
    matches: list[PatternMatch] = []

    for process_id, name, archetype, state, evidence in current:
        comparable = [
            item
            for item in with_context
            if item.configuration.archetype == archetype and item.configuration.state == state
        ]
        matches.append(
            PatternMatch(
                process_id=process_id,
                process_name=name,
                archetype=archetype,
                state=state,
                evidence_strength=evidence,
                # Zero rather than a fabricated number when nothing comparable
                # exists. A search with no basis should be visibly empty.
                analog_strength=(
                    sum(item.multiple for item in comparable) / len(comparable)
                    if comparable
                    else 0.0
                ),
                based_on=len(comparable),
            )
        )

    matches.sort(key=lambda item: item.analog_strength, reverse=True)
    return SearchResult(matches=matches, extremes_found=len(extremes))
