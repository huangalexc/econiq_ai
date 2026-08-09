"""Asset Quality scoring (issues #75, #76).

Both halves in one stage because they write one scorecard. The Quant half
computes what price data supports; the Quality half judges what it does not; and
the agent is told which axes were already measured so no dimension has two
producers.

Peer-relative by construction. §8.3's comparison is *between Assets expressing
one Capability*, so the stage scores a Capability's Assets together — relative
strength is a percentile within that set, and there is no index for "companies
exposed to heavy rare-earth separation" to measure against instead.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from econiq_data_models import Asset, AssetExposure, AssetState, Capability, ScoreDimension
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import (
    AssetQualityDimension as Axis,
)
from econiq_ontology import (
    EntityType,
    ScoreFamily,
)
from econiq_schemas import AssetQualityInput
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents import asset_metrics
from econiq_agents.asset_metrics import Bar, MetricSet
from econiq_agents.asset_quality_agent import JUDGED_AXES, AssetQualityAgent
from econiq_agents.persistence import AgentRunRecorder
from econiq_agents.prompts import ASSET_QUALITY_V1
from econiq_agents.scoring import ScorecardWriter

logger = logging.getLogger("econiq.agents.asset_scoring")


@dataclass(frozen=True, slots=True)
class AssetScore:
    asset_id: uuid.UUID
    name: str
    scorecard_id: uuid.UUID | None = None
    metrics: MetricSet | None = None
    computed_axes: dict[str, float] = field(default_factory=dict)
    judged_axes: int = 0
    run_id: uuid.UUID | None = None
    skipped_reason: str | None = None

    @property
    def priced(self) -> bool:
        return self.metrics is not None and self.metrics.bars > 1


@dataclass(frozen=True, slots=True)
class AssetScoringOutcome:
    capability_id: uuid.UUID
    scores: list[AssetScore] = field(default_factory=list)
    #: Analyses no source supports. Reported so the comparison matrix can render
    #: a gap rather than an empty cell that reads as a zero.
    unavailable: tuple[tuple[str, str], ...] = asset_metrics.UNAVAILABLE

    @property
    def priced(self) -> int:
        return sum(1 for score in self.scores if score.priced)


class AssetScoringStage:
    """Scores every Asset expressing one Capability, against each other."""

    def __init__(
        self, service: LLMService, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.agent = AssetQualityAgent(service)
        self.scores = ScorecardWriter(session_factory)
        self.runs = AgentRunRecorder(session_factory)

    async def run(
        self, capability_id: uuid.UUID, *, as_of: datetime | None = None
    ) -> AssetScoringOutcome:
        moment = as_of or datetime.now(UTC)

        async with self.session_factory() as session:
            capability = (
                await session.execute(
                    select(Capability).where(
                        Capability.capability_id == capability_id,
                        Capability.valid_to.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if capability is None:
                return AssetScoringOutcome(capability_id=capability_id)

            assets = await self._assets(session, capability_id)
            histories = {
                asset.asset_id: await self._history(session, asset.asset_id, moment)
                for asset in assets
            }
            exposures = await self._exposures(session, capability_id)

        metrics = {asset_id: asset_metrics.compute(bars) for asset_id, bars in histories.items()}

        scores: list[AssetScore] = []
        for asset in assets:
            scores.append(
                await self._one(
                    asset,
                    capability,
                    metrics[asset.asset_id],
                    [m for aid, m in metrics.items() if aid != asset.asset_id],
                    exposures.get(asset.asset_id, []),
                    moment,
                )
            )
        return AssetScoringOutcome(capability_id=capability_id, scores=scores)

    # ------------------------------------------------------------------ #

    async def _one(
        self,
        asset: Asset,
        capability: Capability,
        metrics: MetricSet,
        peers: Sequence[MetricSet],
        exposures: Sequence[str],
        moment: datetime,
    ) -> AssetScore:
        computed: dict[str, float] = {}
        dimensions: list[tuple[Axis, float, dict[str, float]]] = []
        rationales: dict[str, str] = {}

        technical = asset_metrics.technical_confirmation(metrics)
        if technical is not None:
            value, parts = technical
            computed[Axis.TECHNICAL_CONFIRMATION.value] = value
            strength = asset_metrics.relative_strength(metrics, peers)
            if strength is not None:
                parts["relative_strength"] = round(strength.value, 4)
            dimensions.append((Axis.TECHNICAL_CONFIRMATION, value, parts))
            rationales[Axis.TECHNICAL_CONFIRMATION.value] = (
                f"Computed from {metrics.bars} bars"
                + (f" ({metrics.first_date} to {metrics.last_date})" if metrics.first_date else "")
                + ". Trend, momentum and drawdown only — technical confirmation asks "
                "whether the market is behaving consistently with the thesis, not "
                "whether the chart predicts anything."
            )

        payload = AssetQualityInput(
            as_of=moment,
            asset_name=asset.name,
            asset_class=asset.asset_class.value,
            ticker=asset.ticker,
            capability_name=capability.name,
            capability_description=capability.description,
            process_name=capability.name,
            exposure_summaries=list(exposures),
            computed_axes=computed,
        )

        run_id: uuid.UUID | None = None
        judged = 0
        try:
            result = await self.agent.run(payload)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("asset quality failed for %s: %s", asset.name, exc)
        else:
            run_id = await self.runs.record(
                result,
                payload=payload,
                prompt=ASSET_QUALITY_V1,
                ontology_layer="Asset",
                provider=self.service.provider.name,
            )
            if result.evaluation.passed:
                judged = len(result.output.axes)
                for axis in result.output.axes:
                    dimensions.append((axis.dimension, axis.value, {}))
                    against = "; ".join(axis.counterarguments) or "none stated"
                    rationales[axis.dimension.value] = (
                        f"Not higher because: {axis.why_not_higher} "
                        f"Facts: {'; '.join(axis.facts) or 'none cited'}. "
                        f"Against: {against}."
                    )
            else:
                logger.warning(
                    "asset quality rejected for %s: %s",
                    asset.name,
                    [c.name for c in result.evaluation.failures],
                )

        if not dimensions:
            return AssetScore(
                asset_id=asset.asset_id,
                name=asset.name,
                metrics=metrics,
                run_id=run_id,
                skipped_reason="nothing computable and nothing judged",
            )

        scorecard_id = await self.scores.record(
            subject_id=asset.asset_id,
            subject_type=EntityType.ASSET,
            family=ScoreFamily.ASSET_QUALITY,
            observed_at=moment,
            agent_run_id=run_id,
            dimensions=dimensions,
        )
        await self._annotate(scorecard_id, rationales)

        return AssetScore(
            asset_id=asset.asset_id,
            name=asset.name,
            scorecard_id=scorecard_id,
            metrics=metrics,
            computed_axes=computed,
            judged_axes=judged,
            run_id=run_id,
        )

    async def _annotate(self, scorecard_id: uuid.UUID, rationales: dict[str, str]) -> None:
        async with self.session_factory() as session:
            for dimension, rationale in rationales.items():
                await session.execute(
                    update(ScoreDimension)
                    .where(
                        ScoreDimension.scorecard_id == scorecard_id,
                        ScoreDimension.dimension == dimension,
                    )
                    .values(rationale=rationale)
                )
            await session.commit()

    async def _assets(self, session: AsyncSession, capability_id: uuid.UUID) -> list[Asset]:
        asset_ids = (
            (
                await session.execute(
                    select(AssetExposure.asset_id).where(
                        AssetExposure.target_id == capability_id,
                        AssetExposure.target_type == EntityType.CAPABILITY,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not asset_ids:
            return []
        return list(
            (
                await session.execute(
                    select(Asset).where(
                        Asset.asset_id.in_(set(asset_ids)), Asset.valid_to.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _history(
        self, session: AsyncSession, asset_id: uuid.UUID, moment: datetime
    ) -> list[Bar]:
        """Price rows as they were understood at the cut-off.

        Both clocks are applied: `observed_at` bounds which trading days count,
        and `recorded_at` bounds which *version* of each day is used. Using the
        newest version of an old day would score the Asset on an adjustment
        factor nobody had at the time (#77).
        """
        rows = (
            (
                await session.execute(
                    select(AssetState)
                    .where(
                        AssetState.asset_id == asset_id,
                        AssetState.observed_at <= moment,
                        AssetState.recorded_at <= moment,
                    )
                    .order_by(AssetState.observed_at, AssetState.recorded_at.desc())
                )
            )
            .scalars()
            .all()
        )
        seen: set[datetime] = set()
        bars: list[Bar] = []
        for row in rows:
            if row.observed_at in seen:
                continue
            seen.add(row.observed_at)
            technical = row.technical or {}
            close = technical.get("close")
            if close is None:
                continue
            bars.append(
                Bar(
                    trade_date=row.observed_at.date(),
                    close=float(close),
                    adj_close=(
                        float(technical["adj_close"])
                        if technical.get("adj_close") is not None
                        else None
                    ),
                    volume=(
                        float(technical["volume"]) if technical.get("volume") is not None else None
                    ),
                )
            )
        return bars

    async def _exposures(
        self, session: AsyncSession, capability_id: uuid.UUID
    ) -> dict[uuid.UUID, list[str]]:
        rows = (
            (
                await session.execute(
                    select(AssetExposure).where(
                        AssetExposure.target_id == capability_id,
                        AssetExposure.target_type == EntityType.CAPABILITY,
                    )
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[uuid.UUID, list[str]] = {}
        for row in rows:
            grouped.setdefault(row.asset_id, []).append(
                f"{row.exposure_kind.value} ({row.directness}), magnitude "
                f"{row.magnitude:.1f}: {row.rationale}"
            )
        return grouped


__all__ = ["JUDGED_AXES", "AssetScore", "AssetScoringOutcome", "AssetScoringStage"]
