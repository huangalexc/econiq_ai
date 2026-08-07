"""Typed edges and the Thesis/Asset/Trade quality separation."""

import uuid

import pytest
from econiq_ontology import (
    AssetQualityDimension,
    CausalRole,
    DimensionScore,
    EntityRef,
    EntityType,
    Relationship,
    RelationshipType,
    Scorecard,
    ScoreFamily,
    ThesisQualityDimension,
    edge_is_legal,
)
from econiq_ontology.base import utcnow
from pydantic import ValidationError


def _ref(kind):
    return EntityRef(entity_type=kind, entity_id=uuid.uuid4())


def test_canonical_chain_is_legal():
    assert edge_is_legal(EntityType.PROCESS, RelationshipType.INFLUENCES, EntityType.PROCESS)
    assert edge_is_legal(EntityType.PROCESS, RelationshipType.CREATES, EntityType.BOTTLENECK)
    assert edge_is_legal(EntityType.BOTTLENECK, RelationshipType.REQUIRES, EntityType.CAPABILITY)
    assert edge_is_legal(EntityType.CAPABILITY, RelationshipType.EXPRESSED_BY, EntityType.ASSET)


def test_bottleneck_may_not_reach_an_asset_directly():
    """Skipping the Capability layer is the shortcut the ontology exists to
    prevent."""
    with pytest.raises(ValidationError, match="illegal edge"):
        Relationship(
            source=_ref(EntityType.BOTTLENECK),
            target=_ref(EntityType.ASSET),
            relationship_type=RelationshipType.EXPRESSED_BY,
            confidence=0.9,
        )


def test_events_may_affect_assets_directly():
    """Ontology §15: a direct Event -> Asset relationship coexists with
    Process-mediated exposure."""
    Relationship(
        source=_ref(EntityType.EVENT),
        target=_ref(EntityType.ASSET),
        relationship_type=RelationshipType.AFFECTS,
        confidence=0.7,
    )


def test_causal_role_belongs_only_to_influence_edges():
    Relationship(
        source=_ref(EntityType.PROCESS),
        target=_ref(EntityType.PROCESS),
        relationship_type=RelationshipType.INFLUENCES,
        causal_role=CausalRole.DRIVER,
        confidence=0.6,
    )
    with pytest.raises(ValidationError, match="causal_role"):
        Relationship(
            source=_ref(EntityType.PROCESS),
            target=_ref(EntityType.BOTTLENECK),
            relationship_type=RelationshipType.CREATES,
            causal_role=CausalRole.DRIVER,
            confidence=0.6,
        )


def _dimension(name):
    return DimensionScore(dimension=name, value=7.0, confidence=0.8, method="deterministic")


def test_a_scorecard_cannot_mix_families():
    with pytest.raises(ValidationError, match="not in family"):
        Scorecard(
            observed_at=utcnow(),
            subject=_ref(EntityType.PROCESS),
            family=ScoreFamily.THESIS_QUALITY,
            dimensions=[_dimension(AssetQualityDimension.VALUATION.value)],
        )


def test_thesis_quality_may_not_score_an_asset():
    with pytest.raises(ValidationError, match="may not score"):
        Scorecard(
            observed_at=utcnow(),
            subject=_ref(EntityType.ASSET),
            family=ScoreFamily.THESIS_QUALITY,
            dimensions=[_dimension(ThesisQualityDimension.LOGICAL_COHERENCE.value)],
        )


def test_trade_quality_is_v2_and_has_no_dimensions():
    with pytest.raises(ValidationError, match="no dimensions in V1"):
        Scorecard(
            observed_at=utcnow(),
            subject=_ref(EntityType.ASSET),
            family=ScoreFamily.TRADE_QUALITY,
            dimensions=[_dimension("entry_timing")],
        )


def test_a_composite_must_say_how_it_was_derived():
    with pytest.raises(ValidationError, match="how it was derived"):
        Scorecard(
            observed_at=utcnow(),
            subject=_ref(EntityType.PROCESS),
            family=ScoreFamily.THESIS_QUALITY,
            dimensions=[_dimension(ThesisQualityDimension.CONTRADICTION.value)],
            composite=6.5,
        )
