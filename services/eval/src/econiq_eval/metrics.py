"""Metric primitives.

Deliberately small and deterministic. Nothing here calls a model — a metric that
depends on a model's opinion cannot be used to judge that model, and the whole
point of the harness is to answer agent doc §26's question ("does this agent
improve the downstream system?") rather than "does the output sound intelligent?"

Event clustering metrics are *not* redefined here: ``econiq_agents`` already
computes pairwise precision, recall and the false merge/split rates that issue #7
was measured against, and the harness imports those rather than growing a second
definition that could quietly disagree.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    """Set-comparison metrics for agents that emit labels or items."""

    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else 0.0

    @property
    def recall(self) -> float:
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def compare_sets[T](predicted: Iterable[T], gold: Iterable[T]) -> ClassificationMetrics:
    predicted_set, gold_set = set(predicted), set(gold)
    return ClassificationMetrics(
        true_positives=len(predicted_set & gold_set),
        false_positives=len(predicted_set - gold_set),
        false_negatives=len(gold_set - predicted_set),
    )


@dataclass(frozen=True, slots=True)
class AccuracyMetrics:
    """Single-label accuracy, with the confusion kept rather than summarised.

    ``near_misses`` counts predictions the grader was told to treat as adjacent
    — a State one step early on the archetype's machine is a different kind of
    error from a State on the wrong machine entirely, and collapsing both into
    "wrong" hides the distinction that would tell you which to fix.
    """

    correct: int
    near_misses: int
    total: int
    confusion: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def tolerant_accuracy(self) -> float:
        return (self.correct + self.near_misses) / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "correct": self.correct,
            "near_misses": self.near_misses,
            "total": self.total,
            "accuracy": round(self.accuracy, 4),
            "tolerant_accuracy": round(self.tolerant_accuracy, 4),
        }


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    """How well stated confidences match observed correctness.

    This measures calibration; it does not assert it. Ontology §35 forbids
    calling model confidences "probabilities" until they have been validated,
    and this is the measurement that would eventually earn that word. Reported
    with the bin counts so a Brier score computed from eleven samples cannot be
    mistaken for evidence.
    """

    brier: float
    bins: tuple[tuple[float, float, float, int], ...]
    """(bin_floor, mean_confidence, observed_rate, count) per occupied bin."""

    sample_size: int

    @property
    def max_deviation(self) -> float:
        """Largest gap between claimed confidence and observed rate."""
        return max((abs(mean - rate) for _, mean, rate, _ in self.bins), default=0.0)

    def as_dict(self) -> dict[str, object]:
        return {
            "brier": round(self.brier, 4),
            "max_deviation": round(self.max_deviation, 4),
            "sample_size": self.sample_size,
            "bins": [
                {
                    "floor": floor,
                    "mean_confidence": round(mean, 4),
                    "observed_rate": round(rate, 4),
                    "count": count,
                }
                for floor, mean, rate, count in self.bins
            ],
        }


def calibration(
    outcomes: Sequence[tuple[float, bool]], *, bin_count: int = 5
) -> CalibrationMetrics:
    """Brier score and a reliability table over ``(confidence, was_correct)``."""
    if not outcomes:
        return CalibrationMetrics(brier=0.0, bins=(), sample_size=0)

    brier = sum((c - float(hit)) ** 2 for c, hit in outcomes) / len(outcomes)

    width = 1.0 / bin_count
    buckets: dict[int, list[tuple[float, bool]]] = {}
    for confidence, hit in outcomes:
        # Clamped so a confidence of exactly 1.0 lands in the top bin rather
        # than a bin of its own.
        index = min(int(confidence / width), bin_count - 1)
        buckets.setdefault(index, []).append((confidence, hit))

    bins = tuple(
        (
            round(index * width, 4),
            sum(c for c, _ in items) / len(items),
            sum(1 for _, hit in items if hit) / len(items),
            len(items),
        )
        for index, items in sorted(buckets.items())
    )
    return CalibrationMetrics(brier=brier, bins=bins, sample_size=len(outcomes))


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0
