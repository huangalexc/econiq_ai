"""Benchmark datasets (agent doc §18).

Four benchmarks are expressible today; the fifth is not, and says so rather than
shipping a stub that would quietly grade nothing:

* §18.1 **Extraction** — labelled Claims with their verbatim spans.
* §18.2 **Process** — Events mapped to Processes, archetypes, State transitions.
* §18.3 **Capability** — Bottlenecks and the AND/OR requirement structure.
* §18.4 **Asset** — Processes mapped to the Assets that actually express them.
* §18.5 **Forecast** — State-conditioned episodes with subsequent outcomes.
  Requires the historical outcome engine (Phase 2, #35–#46). Attempting to load
  it raises, because a forecast benchmark scored against no outcomes would
  report a number, and that number would be worse than nothing.

Every case carries an ``as_of``. A benchmark case without one cannot be graded
honestly: the agent's answer depends on what was knowable at the time, and a
grader that ignores that would reward hindsight (agent doc §20).

Datasets live as JSON under ``services/eval/datasets/`` so they can be reviewed
in a diff. They are data, not code — a labelled span is a factual assertion
about a document, and it belongs somewhere a human can check it.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Self

from econiq_ontology import (
    BottleneckKind,
    EventType,
    ExposureKind,
    LogicOperator,
    Necessity,
    ProcessArchetype,
    ProcessStateLabel,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

DATASET_ROOT = Path(__file__).resolve().parents[3] / "datasets"


class BenchmarkModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LabelledClaim(BenchmarkModel):
    """One Claim a human found in a document, with the words it came from."""

    text: str
    claim_type: str
    quote: str = Field(description="Verbatim span. The grader checks it is really in the document.")
    attributed_to: str | None = None
    entities: tuple[str, ...] = ()


class ExtractionCase(BenchmarkModel):
    """§18.1 — a document and every Claim that should come out of it."""

    case_id: str
    document_title: str
    document_text: str
    document_type: str
    published_at: datetime
    expected_classification: str
    claims: tuple[LabelledClaim, ...]

    @model_validator(mode="after")
    def _quotes_are_present_in_the_document(self) -> Self:
        # A labelling error here would silently become an agent failure, and the
        # agent would be blamed for it. Cheaper to catch when the file loads.
        missing = [c.quote for c in self.claims if c.quote not in self.document_text]
        if missing:
            raise ValueError(f"{self.case_id}: labelled quotes absent from the document: {missing}")
        return self


class LabelledTransition(BenchmarkModel):
    from_state: ProcessStateLabel
    to_state: ProcessStateLabel
    observed_at: datetime


class ProcessCase(BenchmarkModel):
    """§18.2 — Events that should resolve to one Process, and its trajectory."""

    case_id: str
    process_name: str
    as_of: datetime
    archetype: ProcessArchetype
    event_titles: tuple[str, ...]
    expected_state: ProcessStateLabel
    adjacent_states: tuple[ProcessStateLabel, ...] = Field(
        default=(),
        description=(
            "States a grader should count as a near miss rather than a failure. "
            "One step early on the right machine is a different error from the "
            "wrong machine entirely."
        ),
    )
    transitions: tuple[LabelledTransition, ...] = ()


class LabelledRequirement(BenchmarkModel):
    """The AND/OR shape a Bottleneck's relief actually takes (§18.3)."""

    operator: LogicOperator
    capabilities: tuple[str, ...]
    necessity: Necessity = Necessity.REQUIRED


class CapabilityCase(BenchmarkModel):
    """§18.3 — the constraint and what would relieve it."""

    case_id: str
    process_name: str
    as_of: datetime
    bottleneck_name: str
    bottleneck_kind: BottleneckKind
    currently_binding: bool
    requirement: LabelledRequirement
    distractor_capabilities: tuple[str, ...] = Field(
        default=(),
        description="Plausible but wrong Capabilities. Precision is only measurable against these.",
    )


class LabelledExposure(BenchmarkModel):
    identifier: str
    exposure_kind: ExposureKind
    directness: str


class AssetCase(BenchmarkModel):
    """§18.4 — the instruments that genuinely expressed a Process."""

    case_id: str
    process_name: str
    as_of: datetime
    capability_name: str
    expected: tuple[LabelledExposure, ...]
    distractors: tuple[str, ...] = Field(
        default=(),
        description=(
            "Instruments a naive thematic screen would return. The system's "
            "value is discriminating against these, so they are part of the label."
        ),
    )


class EventCase(BenchmarkModel):
    """Clustering labels: which reports describe the same real-world Event."""

    case_id: str
    as_of: datetime
    event_type: EventType
    reports: tuple[tuple[str, str], ...] = Field(description="(report_id, headline) pairs.")
    clusters: tuple[tuple[str, ...], ...] = Field(
        description="Gold grouping of report_ids. Singletons included explicitly."
    )
    syndicated: tuple[str, ...] = Field(
        default=(),
        description=(
            "Report ids that are re-publications of another report here. "
            "Independent source counting must not count these twice (§47)."
        ),
    )

    @model_validator(mode="after")
    def _every_report_is_clustered_exactly_once(self) -> Self:
        clustered = [rid for cluster in self.clusters for rid in cluster]
        declared = [rid for rid, _ in self.reports]
        if sorted(clustered) != sorted(declared):
            raise ValueError(f"{self.case_id}: clusters must partition the reports exactly once")
        return self


class Benchmark(BenchmarkModel):
    """Everything loaded from disk, in one object the harness can walk."""

    extraction: tuple[ExtractionCase, ...] = ()
    events: tuple[EventCase, ...] = ()
    processes: tuple[ProcessCase, ...] = ()
    capabilities: tuple[CapabilityCase, ...] = ()
    assets: tuple[AssetCase, ...] = ()

    @property
    def case_count(self) -> int:
        return sum(
            len(group)
            for group in (
                self.extraction,
                self.events,
                self.processes,
                self.capabilities,
                self.assets,
            )
        )


class ForecastBenchmarkUnavailableError(RuntimeError):
    """§18.5 needs realised outcomes, which arrive with the Phase 2 engine."""


def load_forecast_benchmark() -> None:
    raise ForecastBenchmarkUnavailableError(
        "The forecast benchmark (agent doc §18.5) requires State-conditioned "
        "episodes with realised outcomes, delivered by the historical outcome "
        "engine in Phase 2 (#35-#46). Level 3 and Level 4 evaluation are not "
        "available before then and the harness reports them as such."
    )


def load_benchmark(root: Path | None = None) -> Benchmark:
    """Load every dataset file present. Absent files mean an empty section."""
    base = root or DATASET_ROOT
    return Benchmark(
        extraction=tuple(_load(base / "extraction.json", ExtractionCase)),
        events=tuple(_load(base / "events.json", EventCase)),
        processes=tuple(_load(base / "processes.json", ProcessCase)),
        capabilities=tuple(_load(base / "capabilities.json", CapabilityCase)),
        assets=tuple(_load(base / "assets.json", AssetCase)),
    )


def _load[T: BenchmarkModel](path: Path, model: type[T]) -> list[T]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of cases")
    return [model.model_validate(item) for item in raw]
