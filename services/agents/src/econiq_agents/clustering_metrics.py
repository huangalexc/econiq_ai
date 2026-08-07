"""Clustering evaluation for Event resolution (issue #7 eval hooks).

Cluster quality is measured pairwise: for every pair of Claims, did the system
agree with the gold labelling about whether they belong to the same Event? That
is the measure that matches what goes wrong downstream — a false merge destroys
evidence, a false split inflates it — and it needs no cluster-identity
alignment between the prediction and the gold set.

Deterministic and DB-free, so it runs in unit tests and in the Phase 0 gate
(issue #17) against a labelled corpus.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

Clustering = Mapping[str, Sequence[str]]
"""Cluster id → the Claim ids in it."""


@dataclass(frozen=True, slots=True)
class ClusteringMetrics:
    """Pairwise agreement between a predicted and a gold clustering."""

    pairs_evaluated: int
    true_positives: int
    false_positives: int
    false_negatives: int
    predicted_cluster_count: int
    gold_cluster_count: int
    unassigned: int = 0

    @property
    def precision(self) -> float:
        """Of the pairs we merged, how many belonged together."""
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        """Of the pairs that belonged together, how many we merged."""
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else 1.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    @property
    def false_merge_rate(self) -> float:
        """Fraction of merged pairs that should have stayed apart.

        The dangerous direction: a false merge silently collapses independent
        evidence into one Event and the loss is invisible downstream.
        """
        denominator = self.true_positives + self.false_positives
        return self.false_positives / denominator if denominator else 0.0

    @property
    def false_split_rate(self) -> float:
        """Fraction of same-Event pairs left apart.

        The inflationary direction: repetition survives as separate Events and
        gets counted as corroboration.
        """
        denominator = self.true_positives + self.false_negatives
        return self.false_negatives / denominator if denominator else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "pairs_evaluated": self.pairs_evaluated,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "false_merge_rate": round(self.false_merge_rate, 4),
            "false_split_rate": round(self.false_split_rate, 4),
            "predicted_cluster_count": self.predicted_cluster_count,
            "gold_cluster_count": self.gold_cluster_count,
            "unassigned": self.unassigned,
        }


def evaluate_clustering(predicted: Clustering, gold: Clustering) -> ClusteringMetrics:
    """Compare a predicted clustering against a gold one.

    Only Claims present in the gold set are scored. A Claim the system left
    unassigned is counted in ``unassigned`` and treated as its own singleton
    cluster: declining to cluster something is a false split, not a free pass.
    """
    gold_of = _membership(gold)
    predicted_of = _membership(predicted)

    scored = sorted(gold_of)
    unassigned = sum(1 for claim_id in scored if claim_id not in predicted_of)

    true_positives = false_positives = false_negatives = 0
    for left, right in combinations(scored, 2):
        same_gold = gold_of[left] == gold_of[right]
        same_predicted = (
            left in predicted_of
            and right in predicted_of
            and predicted_of[left] == predicted_of[right]
        )
        if same_gold and same_predicted:
            true_positives += 1
        elif same_predicted:
            false_positives += 1
        elif same_gold:
            false_negatives += 1

    return ClusteringMetrics(
        pairs_evaluated=len(scored) * (len(scored) - 1) // 2,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        predicted_cluster_count=len(predicted),
        gold_cluster_count=len(gold),
        unassigned=unassigned,
    )


def duplicate_suppression_rate(document_count: int, independent_source_count: int) -> float:
    """Fraction of documents that added no independent source.

    One Reuters story carried by twenty outlets scores 0.95 — which is the
    number that says the Event layer is doing its job (ontology §47).
    """
    if document_count <= 0:
        return 0.0
    return max(0.0, (document_count - independent_source_count) / document_count)


def _membership(clustering: Clustering) -> dict[str, str]:
    membership: dict[str, str] = {}
    for cluster_id, members in clustering.items():
        for member in members:
            membership[member] = cluster_id
    return membership


def clusters_from_pairs(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Build clusters from same-Event pairs. Convenience for labelling corpora."""
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for left, right in pairs:
        parent[find(left)] = find(right)

    clusters: dict[str, list[str]] = {}
    for item in sorted(parent):
        clusters.setdefault(find(item), []).append(item)
    return clusters
