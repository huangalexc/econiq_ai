"""Asset comparison and the disconfirming panel (issues #29, #30).

Two reads the Asset screens need that no existing endpoint covers: several
Assets' scorecards side by side, and the alternative worlds a thesis has to
survive.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from econiq_agents.asset_metrics import UNAVAILABLE as QUANT_UNAVAILABLE
from econiq_agents.asset_quality_agent import UNAVAILABLE_AXES
from econiq_data_models import (
    Asset,
    AssetExposure,
    Capability,
    Counterfactual,
    Scorecard,
    ScoreDimension,
)
from econiq_ontology import AssetQualityDimension, EntityType, ScoreFamily
from fastapi import APIRouter, Query
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from econiq_api import provenance
from econiq_api.deps import AsOfDep, SessionDep
from econiq_api.errors import not_found
from econiq_api.schemas import (
    AssetComparisonOut,
    ComparisonCellOut,
    ComparisonColumnOut,
    CounterfactualOut,
    NodeRef,
    UnavailableInputOut,
)
from econiq_api.temporal import current_revision, recorded_by

router = APIRouter(prefix="/api", tags=["underwriting"])

#: Why each unscored axis is unscored. Rendered in the empty cell, because "no
#: value" and "no source" look identical otherwise.
UNAVAILABLE_REASONS: dict[str, str] = {
    **{name: reason for name, reason in QUANT_UNAVAILABLE},
    **{
        axis.value: "Needs a fundamentals or holdings source (#77 covers prices only)."
        for axis in UNAVAILABLE_AXES
    },
}


# Not `/assets/compare`: that collides with `/assets/{asset_id}`, and resolving
# it by router registration order is a trap for whoever reorders the includes.
@router.get("/comparison", response_model=AssetComparisonOut)
async def compare(
    session: SessionDep,
    as_of: AsOfDep,
    capability_id: Annotated[uuid.UUID, Query()],
) -> AssetComparisonOut:
    """§13's matrix for the Assets expressing one Capability.

    Deliberately no overall score. §13 asks that users change ranking weights
    "without changing the underlying scores", which puts the weighting on the
    reader's side of the line — a server-computed overall would freeze one
    weighting into the data and every client would end up arguing with it.
    """
    capability = (
        await session.execute(
            current_revision(
                select(Capability).where(Capability.capability_id == capability_id),
                Capability,
                as_of,
            )
        )
    ).scalar_one_or_none()
    if capability is None:
        raise not_found("capability", capability_id)

    exposures = (
        (
            await session.execute(
                recorded_by(
                    select(AssetExposure).where(
                        AssetExposure.target_id == capability_id,
                        AssetExposure.target_type == EntityType.CAPABILITY,
                    ),
                    AssetExposure,
                    as_of,
                )
            )
        )
        .scalars()
        .all()
    )
    magnitudes: dict[uuid.UUID, float] = {}
    for exposure in exposures:
        magnitudes.setdefault(exposure.asset_id, exposure.magnitude)

    reference = NodeRef(
        id=capability.capability_id,
        type=EntityType.CAPABILITY,
        label=capability.name,
        slug=capability.slug,
    )
    if not magnitudes:
        return AssetComparisonOut(
            capability=reference,
            dimensions=[axis.value for axis in AssetQualityDimension],
            columns=[],
            unavailable=_unavailable(),
        )

    assets = (
        (
            await session.execute(
                current_revision(select(Asset).where(Asset.asset_id.in_(magnitudes)), Asset, as_of)
            )
        )
        .scalars()
        .all()
    )
    scored = await _latest_scores(session, [a.asset_id for a in assets], as_of)
    attribution = await provenance.load(session, (card.agent_run_id for card, _ in scored.values()))

    columns: list[ComparisonColumnOut] = []
    for asset in assets:
        found = scored.get(asset.asset_id)
        by_dimension = {d.dimension: d for d in (found[1] if found else [])}
        columns.append(
            ComparisonColumnOut(
                asset=NodeRef(id=asset.asset_id, type=EntityType.ASSET, label=asset.name),
                ticker=asset.ticker,
                asset_class=asset.asset_class,
                exposure_magnitude=magnitudes.get(asset.asset_id),
                cells=[
                    _cell(axis.value, by_dimension.get(axis.value))
                    for axis in AssetQualityDimension
                ],
                provenance=(
                    attribution.get(found[0].agent_run_id)
                    if found and found[0].agent_run_id
                    else None
                ),
            )
        )

    # Strongest expression first. A tie falls back to name so the order is
    # stable between reads rather than dependent on row order.
    columns.sort(key=lambda column: (-(column.exposure_magnitude or 0.0), column.asset.label))
    return AssetComparisonOut(
        capability=reference,
        dimensions=[axis.value for axis in AssetQualityDimension],
        columns=columns,
        unavailable=_unavailable(),
    )


def _cell(dimension: str, row: ScoreDimension | None) -> ComparisonCellOut:
    if row is None:
        return ComparisonCellOut(
            dimension=dimension,
            unavailable_reason=UNAVAILABLE_REASONS.get(dimension, "Not scored for this Asset yet."),
        )
    return ComparisonCellOut(
        dimension=dimension,
        value=row.value,
        confidence=row.confidence,
        method=row.method,
        inputs=dict(row.inputs),
        rationale=row.rationale,
    )


def _unavailable() -> list[UnavailableInputOut]:
    return [
        UnavailableInputOut(name=name, reason=reason)
        for name, reason in sorted(UNAVAILABLE_REASONS.items())
    ]


async def _latest_scores(
    session: AsyncSession, asset_ids: list[uuid.UUID], as_of: object
) -> dict[uuid.UUID, tuple[Scorecard, list[ScoreDimension]]]:
    if not asset_ids:
        return {}
    query: Select[tuple[Scorecard]] = select(Scorecard).where(
        Scorecard.subject_id.in_(asset_ids),
        Scorecard.family == ScoreFamily.ASSET_QUALITY,
    )
    cards = (
        (
            await session.execute(
                recorded_by(query, Scorecard, as_of).order_by(  # type: ignore[arg-type]
                    Scorecard.observed_at.desc(), Scorecard.recorded_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[uuid.UUID, Scorecard] = {}
    for card in cards:
        latest.setdefault(card.subject_id, card)
    if not latest:
        return {}

    dimensions = (
        (
            await session.execute(
                select(ScoreDimension).where(
                    ScoreDimension.scorecard_id.in_([c.scorecard_id for c in latest.values()])
                )
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[ScoreDimension]] = {}
    for dimension in dimensions:
        grouped.setdefault(dimension.scorecard_id, []).append(dimension)
    return {
        subject_id: (card, grouped.get(card.scorecard_id, []))
        for subject_id, card in latest.items()
    }


@router.get("/processes/{process_id}/counterfactuals", response_model=list[CounterfactualOut])
async def counterfactuals(
    process_id: uuid.UUID, session: SessionDep, as_of: AsOfDep
) -> list[CounterfactualOut]:
    """The "Why not?" panel (#30, ui_concept §14.3).

    §14.3 requires the underwriting screen to surface disconfirming evidence
    explicitly, and its example is a list of alternative worlds. These are that
    list, produced by an agent whose output schema has no field in which to
    conclude the thesis is safe (#66) — so the panel cannot quietly become a
    section that reassures.

    Superseded sets are excluded: a world the thesis has already outlived is
    part of the record but not part of the current case.
    """
    query: Select[tuple[Counterfactual]] = select(Counterfactual).where(
        Counterfactual.process_id == process_id,
        Counterfactual.superseded_at.is_(None),
    )
    rows = (await session.execute(recorded_by(query, Counterfactual, as_of))).scalars().all()
    attribution = await provenance.load(session, (row.agent_run_id for row in rows))
    found = [
        CounterfactualOut(
            id=row.counterfactual_id,
            process_id=row.process_id,
            challenged_assumption=row.challenged_assumption,
            alternative_world=row.alternative_world,
            affected_links=list(row.affected_links),
            assets_harmed=list(row.assets_harmed),
            observable_indicators=list(row.observable_indicators),
            plausibility=row.plausibility,
            severity_if_true=row.severity_if_true,
            is_most_dangerous=row.is_most_dangerous,
            observed_at=row.observed_at,
            provenance=attribution.get(row.agent_run_id) if row.agent_run_id else None,
        )
        for row in rows
    ]
    # Most dangerous first: plausibility times severity, which is the ordering
    # the robustness score is computed from.
    found.sort(key=lambda row: row.threat, reverse=True)
    return found
