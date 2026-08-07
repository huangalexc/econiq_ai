"""Level 1 and Level 2 graders (agent doc §17).

Each grader takes a labelled case and what the system actually produced, and
returns `Grade`s. They are pure functions over data: no database, no model, no
network. That is what makes a regression between two prompt versions
attributable to the prompt rather than to the harness.

**Invariants versus targets.** Some checks are deterministic facts about the
system — a quote either is in the document or it is not — and failing one is a
defect regardless of dataset size. Others are quality levels (recall, accuracy)
whose thresholds this repository chose; the agent doc names the metrics (§4.2,
§5.1, §6.4) but sets no numbers. Grading three cases against an invented recall
bar produces a red build that means nothing, so targets are advisory until
:data:`MIN_SAMPLES_FOR_TARGETS` cases exist, and say so in their detail line.
The distinction mirrors ``EvaluationCheck.blocking`` in ``econiq_llm``, for the
same reason: a check nobody can act on is a check people learn to ignore.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from econiq_agents import evaluate_clustering
from econiq_agents.clustering_metrics import Clustering
from econiq_ontology import LogicOperator, ProcessArchetype, ProcessStateLabel, states_for

from econiq_eval.datasets import (
    AssetCase,
    CapabilityCase,
    EventCase,
    ExtractionCase,
    ProcessCase,
)
from econiq_eval.metrics import AccuracyMetrics, ClassificationMetrics, compare_sets

#: Below this many cases, quality targets are reported but not enforced.
MIN_SAMPLES_FOR_TARGETS = 20

#: Provisional. Chosen by this repository, not by the agent doc, and expected to
#: move once the benchmarks are large enough for the numbers to mean something.
TARGETS: dict[str, float] = {
    "extraction.precision": 0.80,
    "extraction.recall": 0.70,
    "extraction.attribution_accuracy": 0.80,
    "events.cluster_f1": 0.75,
    "events.false_merge_rate": 0.10,
    "process.archetype_accuracy": 0.80,
    "process.state_accuracy": 0.60,
    "process.state_tolerant_accuracy": 0.85,
    "capability.requirement_f1": 0.70,
    "asset.recall": 0.70,
    "asset.precision": 0.60,
}


class EvalLevel(StrEnum):
    """Agent doc §17. Levels 3 and 4 need realised outcomes (Phase 2)."""

    COMPONENT = "component"
    STRUCTURAL = "structural"
    PREDICTIVE = "predictive"
    OUTCOME = "outcome"


@dataclass(frozen=True, slots=True)
class Grade:
    name: str
    level: EvalLevel
    passed: bool
    detail: str
    score: float | None = None
    threshold: float | None = None
    blocking: bool = True
    metrics: dict[str, object] = field(default_factory=dict)

    @property
    def advisory(self) -> bool:
        return not self.blocking and not self.passed


@dataclass(frozen=True, slots=True)
class GradeSet:
    """Grades for one benchmark section."""

    section: str
    grades: tuple[Grade, ...]
    cases_graded: int

    @property
    def passed(self) -> bool:
        """Advisory failures do not sink the set — that is what advisory means."""
        return all(g.passed for g in self.grades if g.blocking)

    @property
    def failures(self) -> tuple[Grade, ...]:
        return tuple(g for g in self.grades if g.blocking and not g.passed)

    @property
    def advisories(self) -> tuple[Grade, ...]:
        return tuple(g for g in self.grades if g.advisory)


def _target(name: str, score: float, sample_size: int, *, lower_is_better: bool = False) -> Grade:
    threshold = TARGETS[name]
    met = score <= threshold if lower_is_better else score >= threshold
    enforced = sample_size >= MIN_SAMPLES_FOR_TARGETS
    comparator = "<=" if lower_is_better else ">="
    detail = (
        f"{score:.3f} {comparator} {threshold:.2f}"
        if met
        else (f"{score:.3f} misses the {comparator} {threshold:.2f} target")
    )
    if not enforced:
        detail += f" (advisory: {sample_size} cases, targets enforce at {MIN_SAMPLES_FOR_TARGETS})"
    return Grade(
        name=name,
        level=EvalLevel.COMPONENT,
        passed=met,
        detail=detail,
        score=score,
        threshold=threshold,
        blocking=enforced,
    )


# --------------------------------------------------------------------------- #
# §18.1 Extraction
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ExtractedClaim:
    """What the system produced, reduced to what a grader can judge."""

    text: str
    quote: str
    attributed_to: str | None = None
    span_verified: bool = True


def grade_extraction(
    cases: Sequence[tuple[ExtractionCase, Sequence[ExtractedClaim]]],
) -> GradeSet:
    """Extraction precision, recall, span accuracy, attribution, hallucination."""
    tp = fp = fn = 0
    ungrounded: list[str] = []
    attribution_hits = attribution_total = 0

    for case, produced in cases:
        gold_quotes = {c.quote for c in case.claims}
        produced_quotes = {c.quote for c in produced}

        # Span accuracy is checked against the document, not against the label.
        # A quote the labeller missed is a recall gap; a quote no document
        # contains is a fabrication, and they are not the same failure.
        for claim in produced:
            if claim.quote not in case.document_text or not claim.span_verified:
                ungrounded.append(claim.text)

        counts = compare_sets(produced_quotes, gold_quotes)
        tp += counts.true_positives
        fp += counts.false_positives
        fn += counts.false_negatives

        by_quote = {c.quote: c for c in case.claims}
        for claim in produced:
            expected = by_quote.get(claim.quote)
            if expected is None or expected.attributed_to is None:
                continue
            attribution_total += 1
            attribution_hits += int(claim.attributed_to == expected.attributed_to)

    overall = ClassificationMetrics(true_positives=tp, false_positives=fp, false_negatives=fn)
    n = len(cases)
    grades = [
        # Blocking regardless of sample size: this is not a quality level, it is
        # the guarantee that a citation means something. One fabricated span is
        # one too many (agent doc §2.3, §2.4).
        Grade(
            name="extraction.hallucination_rate",
            level=EvalLevel.COMPONENT,
            passed=not ungrounded,
            detail=(
                "every produced quote is present in its document"
                if not ungrounded
                else f"{len(ungrounded)} claim(s) cite text no document contains: {ungrounded[:3]}"
            ),
            score=0.0 if not ungrounded else 1.0,
            metrics={"ungrounded": ungrounded},
        ),
        _target("extraction.precision", overall.precision, n),
        _target("extraction.recall", overall.recall, n),
    ]
    if attribution_total:
        grades.append(
            _target(
                "extraction.attribution_accuracy",
                attribution_hits / attribution_total,
                n,
            )
        )
    grades[1] = _replace_metrics(grades[1], overall.as_dict())
    return GradeSet(section="extraction", grades=tuple(grades), cases_graded=n)


# --------------------------------------------------------------------------- #
# §18.2 Events and Processes
# --------------------------------------------------------------------------- #


def grade_clustering(
    cases: Sequence[tuple[EventCase, Clustering]],
) -> GradeSet:
    """Cluster precision/recall, false merge and false split (agent doc §5.1)."""
    f1s: list[float] = []
    merges: list[float] = []
    splits: list[float] = []
    for case, predicted in cases:
        gold: Clustering = {
            f"cluster-{i}": list(cluster) for i, cluster in enumerate(case.clusters)
        }
        metrics = evaluate_clustering(predicted, gold)
        f1s.append(metrics.f1)
        merges.append(metrics.false_merge_rate)
        splits.append(metrics.false_split_rate)

    n = len(cases)
    if not n:
        return GradeSet(section="events", grades=(), cases_graded=0)

    return GradeSet(
        section="events",
        grades=(
            _target("events.cluster_f1", sum(f1s) / n, n),
            # A false merge destroys evidence — two Events become one and the
            # second's independent sources are absorbed. A false split is
            # recoverable by later resolution, so the two are graded apart.
            _target("events.false_merge_rate", sum(merges) / n, n, lower_is_better=True),
            Grade(
                name="events.false_split_rate",
                level=EvalLevel.COMPONENT,
                passed=True,
                detail=f"{sum(splits) / n:.3f} (reported; recoverable by later resolution)",
                score=sum(splits) / n,
                blocking=False,
            ),
        ),
        cases_graded=n,
    )


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    archetype: ProcessArchetype | None
    state: ProcessStateLabel | None
    state_confidence: float | None = None


def grade_processes(cases: Sequence[tuple[ProcessCase, ProcessOutcome]]) -> GradeSet:
    """Archetype and State classification (agent doc §6.3, §6.4)."""
    if not cases:
        return GradeSet(section="processes", grades=(), cases_graded=0)

    archetype_hits = 0
    state_hits = near = 0
    confusion: dict[tuple[str, str], int] = {}
    calibration_input: list[tuple[float, bool]] = []
    off_machine: list[str] = []

    for case, outcome in cases:
        archetype_hits += int(outcome.archetype == case.archetype)
        correct = outcome.state == case.expected_state
        state_hits += int(correct)
        if not correct and outcome.state in case.adjacent_states:
            near += 1
        if outcome.state is not None:
            key = (case.expected_state.value, outcome.state.value)
            confusion[key] = confusion.get(key, 0) + 1
            # A State that is not on the predicted archetype's machine is a
            # structural error, not a near miss — the State layer is supposed to
            # make that unrepresentable (issue #9).
            if outcome.archetype is not None and outcome.state not in _machine(outcome.archetype):
                off_machine.append(
                    f"{case.case_id}: {outcome.state.value} not on {outcome.archetype.value}"
                )
        if outcome.state_confidence is not None:
            calibration_input.append((outcome.state_confidence, correct))

    n = len(cases)
    accuracy = AccuracyMetrics(correct=state_hits, near_misses=near, total=n, confusion=confusion)
    grades = [
        Grade(
            name="process.state_on_archetype_machine",
            level=EvalLevel.STRUCTURAL,
            passed=not off_machine,
            detail=(
                "every State belongs to its Process's archetype"
                if not off_machine
                else f"{len(off_machine)} State(s) off-machine: {off_machine[:3]}"
            ),
            metrics={"violations": off_machine},
        ),
        _target("process.archetype_accuracy", archetype_hits / n, n),
        _replace_metrics(
            _target("process.state_accuracy", accuracy.accuracy, n), accuracy.as_dict()
        ),
        _target("process.state_tolerant_accuracy", accuracy.tolerant_accuracy, n),
    ]
    if calibration_input:
        from econiq_eval.metrics import calibration

        measured = calibration(calibration_input)
        grades.append(
            Grade(
                name="process.state_calibration",
                level=EvalLevel.COMPONENT,
                # Reported, never enforced. Ontology §35: these confidences are
                # model belief, not probabilities, until a calibration framework
                # validates them — and this measurement is the input to that
                # work, not a substitute for it.
                passed=True,
                detail=(
                    f"Brier {measured.brier:.3f} over {measured.sample_size} samples; "
                    f"largest confidence/outcome gap {measured.max_deviation:.3f}. "
                    "Measured, not asserted (ontology §35)."
                ),
                score=measured.brier,
                blocking=False,
                metrics=measured.as_dict(),
            )
        )
    return GradeSet(section="processes", grades=tuple(grades), cases_graded=n)


def _machine(archetype: ProcessArchetype) -> frozenset[ProcessStateLabel]:
    return frozenset(states_for(archetype))


# --------------------------------------------------------------------------- #
# §18.3 Capabilities and §18.4 Assets
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CapabilityOutcome:
    bottleneck_kind: str | None
    operator: LogicOperator | None
    capabilities: tuple[str, ...]


def grade_capabilities(cases: Sequence[tuple[CapabilityCase, CapabilityOutcome]]) -> GradeSet:
    if not cases:
        return GradeSet(section="capabilities", grades=(), cases_graded=0)

    tp = fp = fn = 0
    operator_hits = 0
    distractors_admitted: list[str] = []

    for case, outcome in cases:
        gold = {c.casefold() for c in case.requirement.capabilities}
        produced = {c.casefold() for c in outcome.capabilities}
        counts = compare_sets(produced, gold)
        tp += counts.true_positives
        fp += counts.false_positives
        fn += counts.false_negatives
        operator_hits += int(outcome.operator == case.requirement.operator)
        # AND versus OR over the same Capabilities describes different worlds
        # (ontology §12), so the operator is graded separately from membership.
        for distractor in case.distractor_capabilities:
            if distractor.casefold() in produced:
                distractors_admitted.append(f"{case.case_id}: {distractor}")

    n = len(cases)
    overall = ClassificationMetrics(true_positives=tp, false_positives=fp, false_negatives=fn)
    return GradeSet(
        section="capabilities",
        grades=(
            _replace_metrics(
                _target("capability.requirement_f1", overall.f1, n), overall.as_dict()
            ),
            Grade(
                name="capability.operator_accuracy",
                level=EvalLevel.STRUCTURAL,
                passed=True,
                detail=(
                    f"{operator_hits}/{n} requirement trees used the labelled operator "
                    "(AND and OR imply different participant sets)"
                ),
                score=operator_hits / n,
                blocking=False,
            ),
            Grade(
                name="capability.distractors_rejected",
                level=EvalLevel.COMPONENT,
                passed=not distractors_admitted,
                detail=(
                    "no labelled distractor Capability was admitted"
                    if not distractors_admitted
                    else f"admitted {len(distractors_admitted)}: {distractors_admitted[:3]}"
                ),
                blocking=False,
                metrics={"admitted": distractors_admitted},
            ),
        ),
        cases_graded=n,
    )


def grade_assets(cases: Sequence[tuple[AssetCase, Sequence[str]]]) -> GradeSet:
    """Asset discovery precision and recall, judged against real distractors."""
    if not cases:
        return GradeSet(section="assets", grades=(), cases_graded=0)

    tp = fp = fn = 0
    distractors_returned: list[str] = []
    for case, produced in cases:
        gold = {e.identifier.casefold() for e in case.expected}
        got = {p.casefold() for p in produced}
        counts = compare_sets(got, gold)
        tp += counts.true_positives
        fp += counts.false_positives
        fn += counts.false_negatives
        for distractor in case.distractors:
            if distractor.casefold() in got:
                distractors_returned.append(f"{case.case_id}: {distractor}")

    n = len(cases)
    overall = ClassificationMetrics(true_positives=tp, false_positives=fp, false_negatives=fn)
    return GradeSet(
        section="assets",
        grades=(
            _replace_metrics(_target("asset.recall", overall.recall, n), overall.as_dict()),
            _target("asset.precision", overall.precision, n),
            Grade(
                name="asset.thematic_distractors",
                level=EvalLevel.STRUCTURAL,
                passed=not distractors_returned,
                detail=(
                    "returned no instrument a naive thematic screen would have"
                    if not distractors_returned
                    else (
                        f"{len(distractors_returned)} thematic distractor(s) returned: "
                        f"{distractors_returned[:3]} — this is the comparison PRD §28 "
                        "asks the system to win"
                    )
                ),
                blocking=False,
                metrics={"returned": distractors_returned},
            ),
        ),
        cases_graded=n,
    )


def _replace_metrics(grade: Grade, metrics: Mapping[str, object]) -> Grade:
    return Grade(
        name=grade.name,
        level=grade.level,
        passed=grade.passed,
        detail=grade.detail,
        score=grade.score,
        threshold=grade.threshold,
        blocking=grade.blocking,
        metrics=dict(metrics),
    )
