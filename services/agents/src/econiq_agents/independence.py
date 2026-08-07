"""Source independence (ontology §47).

Twenty articles repeating one Reuters report are not twenty pieces of evidence.
This module decides how many *independent* sources stand behind a cluster, and
it does so deterministically — the agent reports which publishers it saw, and
code decides what that is worth (agent doc §2.3).

Two collapses happen here:

1. **Same publisher.** Three pieces from the same outlet are one source.
2. **Syndication.** Different outlets running near-identical text are one
   source. Detected by token-shingle overlap, which survives the headline
   rewriting and truncation that syndication actually does to a wire story.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_TOKEN = re.compile(r"[a-z0-9]+")

#: Shingle overlap above which two documents are treated as the same report.
#: Set from the observation that genuine independent coverage of one event
#: shares entities and numbers but not sentence structure.
SYNDICATION_THRESHOLD = 0.6

#: Length of the token n-grams compared. Long enough that shared boilerplate
#: ("said in a statement on Monday") does not dominate.
SHINGLE_SIZE = 5


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """What independence assessment needs to know about a document."""

    document_id: str
    publisher: str | None
    text: str


@dataclass(frozen=True, slots=True)
class IndependenceAssessment:
    """How many distinct reports actually stand behind a cluster."""

    independent_source_count: int
    groups: tuple[tuple[str, ...], ...] = ()
    """Document ids grouped into one source each."""

    publishers: tuple[str, ...] = ()
    syndicated_document_ids: tuple[str, ...] = field(default_factory=tuple)
    """Documents collapsed into an earlier group as syndication."""

    @property
    def suppressed(self) -> int:
        """Documents that did not add an independent source."""
        return sum(len(group) - 1 for group in self.groups)


def shingles(text: str, size: int = SHINGLE_SIZE) -> frozenset[str]:
    tokens = _TOKEN.findall(text.lower())
    if len(tokens) < size:
        return frozenset({" ".join(tokens)}) if tokens else frozenset()
    return frozenset(" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1))


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def assess_independence(
    documents: Sequence[SourceDocument],
    *,
    syndication_threshold: float = SYNDICATION_THRESHOLD,
) -> IndependenceAssessment:
    """Group documents into independent sources.

    An unknown publisher is treated as its own source rather than merged with
    other unknowns: over-counting one uncertain source is a smaller error than
    silently collapsing genuinely independent reporting.
    """
    if not documents:
        return IndependenceAssessment(independent_source_count=0)

    groups: list[list[SourceDocument]] = []
    group_shingles: list[frozenset[str]] = []
    syndicated: list[str] = []

    for document in documents:
        document_shingles = shingles(document.text)
        placed = False
        for index, group in enumerate(groups):
            same_publisher = (
                document.publisher is not None and document.publisher == group[0].publisher
            )
            syndicated_copy = jaccard(document_shingles, group_shingles[index]) >= (
                syndication_threshold
            )
            if same_publisher or syndicated_copy:
                group.append(document)
                if syndicated_copy and not same_publisher:
                    syndicated.append(document.document_id)
                placed = True
                break
        if not placed:
            groups.append([document])
            group_shingles.append(document_shingles)

    publishers = sorted({d.publisher for d in documents if d.publisher})
    return IndependenceAssessment(
        independent_source_count=len(groups),
        groups=tuple(tuple(d.document_id for d in group) for group in groups),
        publishers=tuple(publishers),
        syndicated_document_ids=tuple(syndicated),
    )
