"""Asset Quant metrics and Asset Quality scoring (issues #75, #76)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from econiq_agents import asset_metrics
from econiq_agents.asset_metrics import Bar
from econiq_agents.asset_quality_agent import (
    COMPUTED_AXES,
    JUDGED_AXES,
    UNAVAILABLE_AXES,
    AssetQualityAgent,
    AxisCoverageEvaluator,
    CounterargumentEvaluator,
    SeparationEvaluator,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import AssetQualityDimension as Axis
from econiq_schemas import AssetQualityInput, AssetQualityOutput

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _series(values: list[float], *, start: date = date(2025, 1, 1)) -> list[Bar]:
    return [
        Bar(trade_date=start + timedelta(days=index), close=value, adj_close=value, volume=1000.0)
        for index, value in enumerate(values)
    ]


# --------------------------------------------------------------------------- #
# #75 — the agent never calculates
# --------------------------------------------------------------------------- #


def test_the_analyses_no_source_supports_are_named_not_estimated():
    """A valuation inferred from a price chart is not a valuation, and the
    comparison matrix cannot tell a measured multiple from a guessed one."""
    metrics = asset_metrics.compute(_series([100.0] * 300))

    assert "valuation" in metrics.missing
    assert "growth" in metrics.missing
    assert "balance_sheet" in metrics.missing
    names = {name for name, _ in asset_metrics.UNAVAILABLE}
    assert "valuation" in names


def test_a_window_with_too_little_history_is_not_computed():
    """A 12-month return from thirty bars is a different statistic wearing the
    same label, and the matrix would rank it against real ones."""
    metrics = asset_metrics.compute(_series([100.0 + i for i in range(30)]))

    assert metrics.get("return_12m") is None
    assert "return_12m" in metrics.missing


def test_returns_use_the_adjusted_close():
    """A return series from raw closes reports a two-for-one split as a fifty
    percent loss."""
    raw = [
        Bar(trade_date=date(2026, 1, 1) + timedelta(days=i), close=200.0, adj_close=100.0)
        for i in range(30)
    ]

    metrics = asset_metrics.compute(raw)

    # Flat on the adjusted series, whatever the raw prices say.
    assert metrics.get("return_1m") == pytest.approx(0.0)


def test_max_drawdown_is_the_worst_peak_to_trough():
    metrics = asset_metrics.compute(_series([100.0, 120.0, 60.0, 90.0]))

    assert metrics.get("max_drawdown") == pytest.approx(-0.5)


def test_volatility_is_annualised_so_assets_are_comparable():
    steady = asset_metrics.compute(_series([100.0 + i * 0.1 for i in range(60)]))
    jumpy = asset_metrics.compute(_series([100.0 + (10.0 if i % 2 else -10.0) for i in range(60)]))

    assert steady.get("volatility_annualised") is not None
    assert jumpy.get("volatility_annualised") > steady.get("volatility_annualised")


def test_relative_strength_is_a_percentile_within_the_peer_set():
    """§8.3 compares Assets expressing one Capability; there is no index for
    'companies exposed to heavy rare-earth separation'."""
    winner = asset_metrics.compute(_series([100.0 + i for i in range(200)]))
    peers = [
        asset_metrics.compute(_series([100.0] * 200)),
        asset_metrics.compute(_series([100.0 - i * 0.1 for i in range(200)])),
    ]

    strength = asset_metrics.relative_strength(winner, peers)

    assert strength is not None
    assert strength.value == 1.0
    assert strength.unit == "percentile"


def test_a_percentile_against_one_peer_is_not_a_percentile():
    subject = asset_metrics.compute(_series([100.0 + i for i in range(200)]))
    assert (
        asset_metrics.relative_strength(subject, [asset_metrics.compute(_series([100.0] * 200))])
        is None
    )


def test_technical_confirmation_is_computed_with_its_inputs_attached():
    metrics = asset_metrics.compute(_series([100.0 + i * 0.5 for i in range(250)]))

    result = asset_metrics.technical_confirmation(metrics)

    assert result is not None
    value, parts = result
    assert 0.0 <= value <= 10.0
    # Decomposable (#25): a measured axis arriving as a bare float is no more
    # inspectable than a judged one.
    assert "price_to_200d" in parts
    assert "return_6m" in parts


def test_every_metric_records_how_many_bars_it_saw():
    """§8.3 asks for data timestamps and missing data. Eleven bars is not the
    same claim as two hundred."""
    metrics = asset_metrics.compute(_series([100.0 + i for i in range(200)]))

    for metric in metrics.metrics.values():
        assert metric.bars > 0
    assert metrics.first_date == date(2025, 1, 1)


# --------------------------------------------------------------------------- #
# #76 — the qualitative half
# --------------------------------------------------------------------------- #


def test_the_axes_split_between_measured_judged_and_unsourceable():
    assert Axis.TECHNICAL_CONFIRMATION in COMPUTED_AXES
    assert Axis.VALUATION in UNAVAILABLE_AXES
    assert Axis.CAPABILITY_FIT in JUDGED_AXES
    assert set(JUDGED_AXES) | COMPUTED_AXES | UNAVAILABLE_AXES == set(Axis)


def _axis(dimension: Axis, **overrides) -> dict:
    return {
        "dimension": dimension.value,
        "value": 7.0,
        "why_not_higher": "Separation share is unverified outside the filing.",
        "facts": ["Operates the only non-Chinese separation train at scale."],
        "inferences": [],
        "counterarguments": ["A competitor commissions in 2028."],
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
        **overrides,
    }


def _quality(*axes: dict) -> str:
    return json.dumps(
        {
            "axes": list(axes),
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _payload() -> AssetQualityInput:
    return AssetQualityInput(
        as_of=NOW,
        asset_name="MP Materials",
        asset_class="common_stock",
        ticker="MP",
        capability_name="Heavy rare-earth separation",
        capability_description="Separating heavy rare-earth oxides at scale.",
        process_name="Domestic strategic-mineral security",
    )


def test_scoring_an_axis_no_source_supports_is_rejected():
    """A valuation with nothing behind it is worse than a gap."""
    output = AssetQualityOutput.model_validate_json(
        _quality(*[_axis(a) for a in JUDGED_AXES], _axis(Axis.VALUATION))
    )

    checks = {c.name: c for c in AxisCoverageEvaluator().evaluate(_payload(), output)}

    assert checks["no_unsourced_axis_scored"].passed is False


def test_valuation_language_anywhere_in_the_reasoning_is_rejected():
    """Ontology §17 makes the separation structural. An axis reasoning about
    cheapness has contaminated Asset Quality with something the family excludes,
    and no reader downstream could tell."""
    axes = [_axis(a) for a in JUDGED_AXES]
    axes[0]["inferences"] = ["The shares look cheap against replacement cost."]
    output = AssetQualityOutput.model_validate_json(_quality(*axes))

    checks = SeparationEvaluator().evaluate(_payload(), output)

    assert checks[0].passed is False
    assert checks[0].blocking is True


def test_a_missing_counterargument_is_advisory_not_blocking():
    """A genuinely uncontested characteristic exists; blocking would push the
    agent into inventing counterpoints, which is worse than the silence."""
    axes = [_axis(a) for a in JUDGED_AXES]
    axes[0]["counterarguments"] = []
    output = AssetQualityOutput.model_validate_json(_quality(*axes))

    checks = CounterargumentEvaluator().evaluate(_payload(), output)

    assert checks[0].passed is False
    assert checks[0].blocking is False


def test_the_agent_is_told_which_axes_were_measured():
    agent = AssetQualityAgent(LLMService(ScriptedProvider([]), observers=[]))
    payload = AssetQualityInput(
        as_of=NOW,
        asset_name="MP Materials",
        asset_class="common_stock",
        capability_name="Separation",
        capability_description="…",
        process_name="…",
        computed_axes={"technical_confirmation": 6.4},
    )

    content = agent.build_user_content(payload)

    assert "do not score these" in content.lower()
    assert "technical_confirmation: 6.4" in content
    assert "As an expression of" in content


def test_the_output_cannot_carry_a_composite():
    assert "composite" not in AssetQualityOutput.model_fields
    assert "overall" not in AssetQualityOutput.model_fields


# --------------------------------------------------------------------------- #
# The stage
# --------------------------------------------------------------------------- #


@pytest.mark.integration
class TestAssetScoringStage:
    @staticmethod
    async def _seed(session_factory, *, assets: int = 2) -> tuple[uuid.UUID, list[uuid.UUID]]:
        from econiq_data_models import (
            Asset,
            AssetExposure,
            AssetState,
            Capability,
            Node,
        )
        from econiq_ontology import AssetClass, EntityType, ExposureKind

        capability_id = uuid.uuid4()
        asset_ids: list[uuid.UUID] = []
        async with session_factory() as session:
            session.add(Node(node_id=capability_id, node_type=EntityType.CAPABILITY, slug="sep"))
            await session.flush()
            session.add(
                Capability(
                    capability_id=capability_id,
                    revision=1,
                    name="Heavy rare-earth separation",
                    slug="sep",
                    description="Separating heavy rare-earth oxides at scale.",
                    aliases=[],
                )
            )
            await session.flush()

            for index in range(assets):
                asset_id = uuid.uuid4()
                asset_ids.append(asset_id)
                session.add(Node(node_id=asset_id, node_type=EntityType.ASSET))
                await session.flush()
                session.add(
                    Asset(
                        asset_id=asset_id,
                        revision=1,
                        name=f"Asset {index}",
                        asset_class=AssetClass.COMMON_STOCK,
                        ticker=f"A{index}",
                        currency="USD",
                    )
                )
                await session.flush()
                session.add(
                    AssetExposure(
                        asset_exposure_id=uuid.uuid4(),
                        asset_id=asset_id,
                        target_id=capability_id,
                        target_type=EntityType.CAPABILITY,
                        exposure_kind=ExposureKind.PRODUCTION_CAPABILITY,
                        directness="direct",
                        magnitude=8.0,
                        rationale="Core of the operation.",
                        confidence=0.85,
                        observed_at=NOW - timedelta(days=1),
                    )
                )
                # 250 daily bars, the first Asset trending up harder.
                for day in range(250):
                    price = 100.0 + day * (0.5 if index == 0 else 0.1)
                    session.add(
                        AssetState(
                            asset_state_id=uuid.uuid4(),
                            asset_id=asset_id,
                            currency="USD",
                            observed_at=NOW - timedelta(days=250 - day),
                            recorded_at=NOW - timedelta(days=250 - day),
                            technical={
                                "close": price,
                                "adj_close": price,
                                "volume": 1000.0,
                            },
                            market_structure={},
                            fundamental={},
                            valuation={},
                            source="test",
                        )
                    )
            await session.commit()
        return capability_id, asset_ids

    @staticmethod
    def _stage(session_factory, *responses: str):
        from econiq_agents import AssetScoringStage

        return AssetScoringStage(
            LLMService(ScriptedProvider(responses), observers=[]), session_factory
        )

    async def test_a_scorecard_carries_measured_and_judged_axes(self, session_factory):
        capability_id, _ = await self._seed(session_factory)
        stage = self._stage(
            session_factory,
            _quality(*[_axis(a) for a in JUDGED_AXES]),
            _quality(*[_axis(a) for a in JUDGED_AXES]),
        )

        outcome = await stage.run(capability_id, as_of=NOW)

        assert len(outcome.scores) == 2
        for score in outcome.scores:
            assert score.scorecard_id is not None
            assert score.judged_axes == len(JUDGED_AXES)
            assert Axis.TECHNICAL_CONFIRMATION.value in score.computed_axes

    async def test_the_family_is_asset_quality_never_thesis(self, session_factory):
        """Ontology §17: the families are separate by construction."""
        from econiq_data_models import Scorecard
        from econiq_ontology import ScoreFamily
        from sqlalchemy import select

        capability_id, _ = await self._seed(session_factory, assets=1)
        await self._stage(session_factory, _quality(*[_axis(a) for a in JUDGED_AXES])).run(
            capability_id, as_of=NOW
        )

        async with session_factory() as session:
            cards = (await session.execute(select(Scorecard))).scalars().all()

        assert cards
        assert all(card.family is ScoreFamily.ASSET_QUALITY for card in cards)
        assert all(card.composite is None for card in cards)

    async def test_relative_strength_ranks_the_stronger_asset_higher(self, session_factory):
        """The peer set is the benchmark — §8.3 compares expressions of one
        Capability against each other."""
        capability_id, _ = await self._seed(session_factory)
        outcome = await self._stage(
            session_factory,
            _quality(*[_axis(a) for a in JUDGED_AXES]),
            _quality(*[_axis(a) for a in JUDGED_AXES]),
        ).run(capability_id, as_of=NOW)

        by_name = {score.name: score for score in outcome.scores}
        assert (
            by_name["Asset 0"].computed_axes["technical_confirmation"]
            >= by_name["Asset 1"].computed_axes["technical_confirmation"]
        )

    async def test_unsourceable_analyses_travel_with_the_outcome(self, session_factory):
        """So the comparison matrix renders a gap rather than an empty cell that
        reads as a zero."""
        capability_id, _ = await self._seed(session_factory, assets=1)

        outcome = await self._stage(
            session_factory, _quality(*[_axis(a) for a in JUDGED_AXES])
        ).run(capability_id, as_of=NOW)

        names = {name for name, _ in outcome.unavailable}
        assert {"valuation", "growth", "balance_sheet"} <= names

    async def test_rejected_quality_output_still_leaves_the_measured_axis(self, session_factory):
        """The technical score was never the agent's to get wrong."""
        capability_id, _ = await self._seed(session_factory, assets=1)
        # Valuation language: blocked by SeparationEvaluator.
        axes = [_axis(a) for a in JUDGED_AXES]
        axes[0]["inferences"] = ["The shares look cheap."]

        outcome = await self._stage(session_factory, _quality(*axes)).run(capability_id, as_of=NOW)

        score = outcome.scores[0]
        assert score.judged_axes == 0
        assert Axis.TECHNICAL_CONFIRMATION.value in score.computed_axes
        assert score.scorecard_id is not None

    async def test_every_dimension_records_its_reasoning(self, session_factory):
        from econiq_data_models import ScoreDimension
        from sqlalchemy import select

        capability_id, _ = await self._seed(session_factory, assets=1)
        await self._stage(session_factory, _quality(*[_axis(a) for a in JUDGED_AXES])).run(
            capability_id, as_of=NOW
        )

        async with session_factory() as session:
            rows = (await session.execute(select(ScoreDimension))).scalars().all()

        assert rows
        for row in rows:
            assert row.rationale, f"{row.dimension} has no reasoning"
