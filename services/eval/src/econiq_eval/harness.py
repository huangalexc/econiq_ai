"""The harness: grade, audit, inject, report.

One object answers the question issue #16 exists to answer — *is this build
better or worse than the last one, and did it cheat?* — and one renderer turns
it into something a human reads in a pull request.

Three parts, deliberately unequal in authority:

* **Audits** are facts. A finding is a defect and fails the run.
* **Fault injection** is a fact about the audits. A missed fault fails the run,
  because an integrity check that never fires is indistinguishable from one that
  is broken.
* **Benchmarks** are measurements. They fail the run only where a check is a
  deterministic invariant (an ungrounded quote) rather than a quality target
  chosen by this repository against a small dataset.

Levels 3 and 4 of agent doc §17 are not reported as passing. They are reported
as unavailable, with the reason, because a phase gate that silently omits two of
its four levels is how a system ends up optimising for Level 4 before Levels 1–3
are validated — which §17 explicitly warns against.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from econiq_agents.clustering_metrics import Clustering
from econiq_ontology import utcnow
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_eval.audit import AuditReport, full_audit
from econiq_eval.datasets import (
    AssetCase,
    Benchmark,
    CapabilityCase,
    EventCase,
    ExtractionCase,
    ProcessCase,
)
from econiq_eval.faults import FaultInjectionReport, run_fault_injection
from econiq_eval.graders import (
    CapabilityOutcome,
    ExtractedClaim,
    GradeSet,
    ProcessOutcome,
    grade_assets,
    grade_capabilities,
    grade_clustering,
    grade_extraction,
    grade_processes,
)

#: Agent doc §17 levels this phase cannot evaluate, and why. Reported, not hidden.
UNAVAILABLE_LEVELS = (
    (
        "Level 3 — Predictive utility",
        "Needs out-of-sample forecasts to score against. Arrives with the "
        "historical engine (Phase 2, #35-#46).",
    ),
    (
        "Level 4 — Investment outcome",
        "Needs realised returns. Agent doc §17 is explicit that Level 4 must "
        "not be optimised for before Levels 1-3 are validated.",
    ),
)


@dataclass(frozen=True, slots=True)
class SystemOutputs:
    """What the system actually produced, paired with the case that asked for it.

    Supplied by the caller rather than produced here: the harness grades, it
    does not run the pipeline. That keeps one grader usable by a unit test with
    scripted responses and by the end-to-end corpus run (#17) without either
    reaching into the other.
    """

    extraction: Sequence[tuple[ExtractionCase, Sequence[ExtractedClaim]]] = ()
    events: Sequence[tuple[EventCase, Clustering]] = ()
    processes: Sequence[tuple[ProcessCase, ProcessOutcome]] = ()
    capabilities: Sequence[tuple[CapabilityCase, CapabilityOutcome]] = ()
    assets: Sequence[tuple[AssetCase, Sequence[str]]] = ()


@dataclass(frozen=True, slots=True)
class HarnessReport:
    grade_sets: tuple[GradeSet, ...] = ()
    audit: AuditReport = field(default_factory=AuditReport)
    faults: FaultInjectionReport | None = None
    ran_at: datetime = field(default_factory=utcnow)

    @property
    def passed(self) -> bool:
        """Facts must hold; measurements are allowed to be low and say so."""
        return (
            self.audit.clean
            and (self.faults is None or self.faults.clean)
            and all(gs.passed for gs in self.grade_sets)
        )

    @property
    def blocking_failures(self) -> tuple[str, ...]:
        reasons: list[str] = []
        reasons += [f"audit: {finding}" for finding in self.audit.findings]
        if self.faults is not None:
            reasons += [
                f"undetected fault: {result.fault} ({result.detail})"
                for result in self.faults.missed
            ]
        reasons += [
            f"{gs.section}: {grade.name} — {grade.detail}"
            for gs in self.grade_sets
            for grade in gs.failures
        ]
        return tuple(reasons)

    @property
    def advisories(self) -> tuple[str, ...]:
        return tuple(
            f"{gs.section}: {grade.name} — {grade.detail}"
            for gs in self.grade_sets
            for grade in gs.advisories
        )


def grade(benchmark: Benchmark, outputs: SystemOutputs) -> tuple[GradeSet, ...]:
    """Grade every section that has both cases and outputs."""
    sets = [
        grade_extraction(outputs.extraction),
        grade_clustering(outputs.events),
        grade_processes(outputs.processes),
        grade_capabilities(outputs.capabilities),
        grade_assets(outputs.assets),
    ]
    # A section with no outputs produced no grades; dropping it keeps the report
    # honest about what was measured rather than showing five sections of zeros.
    return tuple(gs for gs in sets if gs.grades)


async def run_harness(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    benchmark: Benchmark | None = None,
    outputs: SystemOutputs | None = None,
    inject_faults: bool = True,
    as_of: datetime | None = None,
) -> HarnessReport:
    """Everything, in the order that fails fastest on the cheapest evidence."""
    grade_sets = grade(benchmark, outputs) if benchmark is not None and outputs is not None else ()
    audit = await full_audit(session_factory, as_of=as_of)
    faults = await run_fault_injection(session_factory) if inject_faults else None
    return HarnessReport(grade_sets=grade_sets, audit=audit, faults=faults)


def render_markdown(report: HarnessReport) -> str:
    """A report someone will actually read, with the verdict first."""
    verdict = "PASS" if report.passed else "FAIL"
    lines = [
        "# Evaluation report",
        "",
        f"**{verdict}** — {report.ran_at.isoformat(timespec='seconds')}",
        "",
    ]

    if report.blocking_failures:
        lines += ["## Blocking failures", ""]
        lines += [f"- {reason}" for reason in report.blocking_failures]
        lines.append("")

    lines += ["## Integrity audit", ""]
    if report.audit.clean:
        lines.append(
            f"{len(report.audit.checks_run)} checks, no findings: "
            f"{', '.join(report.audit.checks_run)}."
        )
    else:
        for check, findings in sorted(report.audit.by_check().items()):
            lines.append(f"- **{check}** — {len(findings)} finding(s)")
            lines += [f"  - {f.detail}" for f in findings[:5]]
    if report.audit.deferred:
        lines += ["", "Deferred checks:"]
        lines += [f"- {item}" for item in report.audit.deferred]
    lines.append("")

    if report.faults is not None:
        lines += [
            "## Fault injection (agent doc §19)",
            "",
            f"Faults stopped: **{report.faults.detection_rate:.0%}** "
            f"({sum(1 for r in report.faults.results if r.detected)}"
            f"/{len(report.faults.results)}).",
            "",
            "| Fault | Stopped | Defence | Check |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {r.fault} | {'yes' if r.detected else '**no**'} | {r.defence.value} "
            f"| {r.expected_check} |"
            for r in report.faults.results
        ]
        if report.faults.deferred:
            lines += ["", "Not injectable in Phase 0:"]
            lines += [f"- {item}" for item in report.faults.deferred]
        lines.append("")

    if report.grade_sets:
        lines += ["## Benchmarks (agent doc §17 levels 1-2)", ""]
        for grade_set in report.grade_sets:
            lines += [
                f"### {grade_set.section} ({grade_set.cases_graded} cases)",
                "",
                "| Check | Result | Score | Target |",
                "|---|---|---|---|",
            ]
            for item in grade_set.grades:
                mark = "pass" if item.passed else ("advisory" if not item.blocking else "**FAIL**")
                score = f"{item.score:.3f}" if item.score is not None else "—"
                target = f"{item.threshold:.2f}" if item.threshold is not None else "—"
                lines.append(f"| {item.name} | {mark} | {score} | {target} |")
            lines.append("")
            for item in grade_set.grades:
                if not item.passed:
                    lines.append(f"- {item.name}: {item.detail}")
            lines.append("")

    lines += ["## Not evaluated", ""]
    lines += [f"- **{name}** — {reason}" for name, reason in UNAVAILABLE_LEVELS]
    lines.append("")
    return "\n".join(lines)
