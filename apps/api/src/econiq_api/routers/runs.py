"""Agent runs, scorecards and pipeline state — the observability surface.

This is where provenance stops being a database property and becomes something a
person can look at. Every derived row in the ontology cites an agent run; this
router is how you read the run, what it cost, what it was evaluated on, and
whether it was accepted or rejected.

It also exposes the pipeline: which stages exist, which have handlers, which
have reconcilers, and how deep the queue is. A stage that is declared but
unwired should be visible rather than silently inert.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from econiq_data_models import AgentRun, Scorecard, ScoreDimension
from econiq_ontology import ScoreFamily
from econiq_orchestration import PIPELINE, WorkQueue
from fastapi import APIRouter, Query
from sqlalchemy import Select, select

from econiq_api.deps import AsOfDep, GraphDep, PageDep, SessionDep, SessionFactoryDep
from econiq_api.errors import not_found
from econiq_api.schemas import (
    AgentRunOut,
    NodeRef,
    PipelineStageOut,
    QueueDepthOut,
    ScorecardOut,
    ScoreDimensionOut,
)
from econiq_api.temporal import recorded_by

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/runs", response_model=list[AgentRunOut])
async def list_runs(
    session: SessionDep,
    page: PageDep,
    agent_name: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    failed_evaluation: Annotated[
        bool | None,
        Query(description="Only runs whose output was refused by a deterministic check."),
    ] = None,
) -> list[AgentRunOut]:
    query: Select[tuple[AgentRun]] = select(AgentRun)
    if agent_name:
        query = query.where(AgentRun.agent_name.in_(agent_name))
    if status:
        query = query.where(AgentRun.status.in_(status))
    if failed_evaluation:
        query = query.where(AgentRun.status == "rejected")

    rows = (
        (
            await session.execute(
                query.order_by(AgentRun.started_at.desc()).limit(page.limit).offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return [_run_out(row) for row in rows]


@router.get("/runs/{run_id}", response_model=AgentRunOut)
async def get_run(run_id: uuid.UUID, session: SessionDep) -> AgentRunOut:
    row = await session.get(AgentRun, run_id)
    if row is None:
        raise not_found("agent run", run_id)
    return _run_out(row)


@router.get("/scores/{subject_id}", response_model=list[ScorecardOut])
async def scores(
    subject_id: uuid.UUID,
    session: SessionDep,
    graph: GraphDep,
    as_of: AsOfDep,
    family: Annotated[list[ScoreFamily] | None, Query()] = None,
) -> list[ScorecardOut]:
    """Scorecards for a subject, one family per card.

    There is deliberately no endpoint that blends families: Thesis quality,
    Asset quality and Trade quality are separate by construction (ontology §17),
    and offering a combined number here would undo that at the last step.
    """
    query: Select[tuple[Scorecard]] = select(Scorecard).where(Scorecard.subject_id == subject_id)
    if family:
        query = query.where(Scorecard.family.in_(family))
    cards = (
        (
            await session.execute(
                recorded_by(query, Scorecard, as_of).order_by(Scorecard.observed_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if not cards:
        return []

    dimensions = (
        (
            await session.execute(
                select(ScoreDimension).where(
                    ScoreDimension.scorecard_id.in_([c.scorecard_id for c in cards])
                )
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[ScoreDimension]] = {}
    for dimension in dimensions:
        grouped.setdefault(dimension.scorecard_id, []).append(dimension)

    subject = await graph.node(subject_id)
    return [
        ScorecardOut(
            id=card.scorecard_id,
            subject=(
                NodeRef(
                    id=subject.node_id,
                    type=subject.node_type,
                    label=subject.label,
                    slug=subject.slug,
                )
                if subject
                else NodeRef(id=subject_id, type=card.subject_type, label="(unknown)")
            ),
            family=card.family,
            observed_at=card.observed_at,
            composite=card.composite,
            composite_method=card.composite_method,
            dimensions=[
                ScoreDimensionOut(
                    dimension=d.dimension,
                    value=d.value,
                    confidence=d.confidence,
                    method=d.method,
                    inputs=dict(d.inputs),
                    rationale=d.rationale,
                )
                for d in grouped.get(card.scorecard_id, [])
            ],
        )
        for card in cards
    ]


@router.get("/pipeline", response_model=list[PipelineStageOut])
async def pipeline() -> list[PipelineStageOut]:
    """The declared pipeline (issue #14).

    ``has_handler`` and ``has_reconciler`` are reported rather than assumed: a
    stage with no handler never runs, and one with no reconciler has no backstop
    if its triggering event is lost.
    """
    from econiq_api.state import runtime_registry

    registry, reconciler_stages = runtime_registry()
    return [
        PipelineStageOut(
            name=stage.name,
            priority=stage.priority,
            concurrency=stage.concurrency,
            triggered_by=[event.value for event in stage.triggered_by],
            emits=[event.value for event in stage.emits],
            description=stage.description,
            has_handler=stage.name in registry,
            has_reconciler=stage.name in reconciler_stages,
        )
        for stage in PIPELINE
    ]


@router.get("/pipeline/queue", response_model=list[QueueDepthOut])
async def queue_depth(
    factory: SessionFactoryDep,
    stage: Annotated[str | None, Query()] = None,
) -> list[QueueDepthOut]:
    queue = WorkQueue(factory)
    stages = [stage] if stage else [definition.name for definition in PIPELINE]
    out: list[QueueDepthOut] = []
    for name in stages:
        depth = await queue.depth(name)
        out.append(
            QueueDepthOut(
                stage=name,
                pending=depth.pending,
                running=depth.running,
                failed=depth.failed,
                dead=depth.dead,
            )
        )
    return out


def _run_out(row: AgentRun) -> AgentRunOut:
    return AgentRunOut(
        id=row.agent_run_id,
        agent_name=row.agent_name,
        agent_version=row.agent_version,
        ontology_layer=row.ontology_layer,
        status=row.status.value,
        as_of=row.as_of,
        started_at=row.started_at,
        finished_at=row.finished_at,
        attempts=row.attempts,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        latency_ms=row.latency_ms,
        evaluation=row.evaluation,
        trigger_event_id=row.trigger_event_id,
    )
