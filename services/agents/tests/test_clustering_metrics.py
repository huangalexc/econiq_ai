"""Cluster quality, measured pairwise."""

import pytest
from econiq_agents import clusters_from_pairs, evaluate_clustering

GOLD = {"e1": ["c1", "c2", "c3"], "e2": ["c4", "c5"]}


def test_a_perfect_clustering_scores_one():
    metrics = evaluate_clustering(GOLD, GOLD)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.false_merge_rate == 0.0
    assert metrics.false_split_rate == 0.0


def test_a_false_merge_costs_precision():
    """Merging two Events destroys evidence — the dangerous direction."""
    predicted = {"p1": ["c1", "c2", "c3", "c4", "c5"]}
    metrics = evaluate_clustering(predicted, GOLD)

    assert metrics.recall == 1.0
    assert metrics.false_positives == 6  # every cross-event pair
    assert metrics.precision == pytest.approx(4 / 10)
    assert metrics.false_merge_rate == pytest.approx(6 / 10)


def test_a_false_split_costs_recall():
    """Splitting one Event inflates evidence — repetition survives as corroboration."""
    predicted = {"p1": ["c1", "c2"], "p2": ["c3"], "p3": ["c4", "c5"]}
    metrics = evaluate_clustering(predicted, GOLD)

    assert metrics.precision == 1.0
    assert metrics.false_negatives == 2  # c1-c3 and c2-c3
    assert metrics.recall == pytest.approx(2 / 4)
    assert metrics.false_split_rate == pytest.approx(0.5)


def test_leaving_a_claim_unassigned_is_a_false_split_not_a_free_pass():
    predicted = {"p1": ["c1", "c2"], "p2": ["c4", "c5"]}
    metrics = evaluate_clustering(predicted, GOLD)

    assert metrics.unassigned == 1
    assert metrics.recall == pytest.approx(2 / 4)


def test_singletons_on_both_sides_score_perfectly():
    singletons = {"a": ["c1"], "b": ["c2"]}
    metrics = evaluate_clustering(singletons, singletons)
    assert metrics.f1 == 1.0
    assert metrics.pairs_evaluated == 1


def test_clusters_can_be_built_from_labelled_pairs():
    clusters = clusters_from_pairs([("c1", "c2"), ("c2", "c3"), ("c4", "c5")])
    assert sorted(sorted(members) for members in clusters.values()) == [
        ["c1", "c2", "c3"],
        ["c4", "c5"],
    ]
