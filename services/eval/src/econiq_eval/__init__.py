"""Evaluation harness (issue #16).

Agent run logging and prompt/model versioning already exist — every agent writes
through ``AgentRunRecorder`` (issue #4, #6), so the provenance chain is uniform
by construction. What this package adds is the part that makes that record
useful: benchmarks that grade the output, audits that check the system did not
cheat to produce it, fault injection that checks the audits actually fire, and a
ledger that compares one prompt version against another.

The organising principle is agent doc §26 — the question is never "does the
output sound intelligent?" but "does this improve the downstream system?" Every
grader here is a pure function over data, so the answer is attributable to the
change rather than to the harness.
"""

from econiq_eval.audit import (
    AuditFinding,
    AuditReport,
    DuplicationAudit,
    PointInTimeAudit,
    ProvenanceAudit,
    full_audit,
    summarise,
)
from econiq_eval.datasets import (
    AssetCase,
    Benchmark,
    CapabilityCase,
    EventCase,
    ExtractionCase,
    ForecastBenchmarkUnavailableError,
    LabelledClaim,
    LabelledExposure,
    LabelledRequirement,
    ProcessCase,
    load_benchmark,
    load_forecast_benchmark,
)
from econiq_eval.faults import (
    FAULTS,
    Defence,
    Fault,
    FaultInjectionReport,
    FaultResult,
    run_fault_injection,
)
from econiq_eval.graders import (
    TARGETS,
    CapabilityOutcome,
    EvalLevel,
    ExtractedClaim,
    Grade,
    GradeSet,
    ProcessOutcome,
    grade_assets,
    grade_capabilities,
    grade_clustering,
    grade_extraction,
    grade_processes,
)
from econiq_eval.harness import (
    HarnessReport,
    SystemOutputs,
    grade,
    render_markdown,
    run_harness,
)
from econiq_eval.historical_faults import (
    LeakFault,
    LeakResult,
)
from econiq_eval.historical_faults import missed as leaks_missed
from econiq_eval.historical_faults import run as run_leak_injection
from econiq_eval.metrics import (
    AccuracyMetrics,
    CalibrationMetrics,
    ClassificationMetrics,
    calibration,
    compare_sets,
)
from econiq_eval.runs import PromptComparison, RunLedger, RunStats

__all__ = [
    "FAULTS",
    "TARGETS",
    "AccuracyMetrics",
    "AssetCase",
    "AuditFinding",
    "AuditReport",
    "Benchmark",
    "CalibrationMetrics",
    "CapabilityCase",
    "CapabilityOutcome",
    "ClassificationMetrics",
    "Defence",
    "DuplicationAudit",
    "EvalLevel",
    "EventCase",
    "ExtractedClaim",
    "ExtractionCase",
    "Fault",
    "FaultInjectionReport",
    "FaultResult",
    "ForecastBenchmarkUnavailableError",
    "Grade",
    "GradeSet",
    "HarnessReport",
    "LabelledClaim",
    "LabelledExposure",
    "LabelledRequirement",
    "LeakFault",
    "LeakResult",
    "PointInTimeAudit",
    "ProcessCase",
    "ProcessOutcome",
    "PromptComparison",
    "ProvenanceAudit",
    "RunLedger",
    "RunStats",
    "SystemOutputs",
    "calibration",
    "compare_sets",
    "full_audit",
    "grade",
    "grade_assets",
    "grade_capabilities",
    "grade_clustering",
    "grade_extraction",
    "grade_processes",
    "leaks_missed",
    "load_benchmark",
    "load_forecast_benchmark",
    "render_markdown",
    "run_fault_injection",
    "run_harness",
    "run_leak_injection",
    "summarise",
]
