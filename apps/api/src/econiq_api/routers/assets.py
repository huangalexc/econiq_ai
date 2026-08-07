"""Asset endpoints.

The detail response leads with the discovery chain, because the question an
Asset page has to answer first is not "what is this" but "why is this here"
(issue #28). An Asset with no chain is an Asset nobody should act on, and the
shape of the response makes that visible rather than requiring a second call.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from econiq_data_models import Asset, AssetExposure
from econiq_ontology import AssetClass
from fastapi import APIRouter, Query
from sqlalchemy import Select, select

from econiq_api.deps import AsOfDep, GraphDep, PageDep, SessionDep
from econiq_api.errors import not_found
from econiq_api.schemas import (
    AssetDetailOut,
    AssetIdentifiersOut,
    AssetOut,
    DiscoveryPathOut,
    ExposureOut,
    NodeRef,
    PathStepOut,
)
from econiq_api.temporal import current_revision, recorded_by

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("", response_model=list[AssetOut])
async def list_assets(
    session: SessionDep,
    page: PageDep,
    as_of: AsOfDep,
    asset_class: Annotated[list[AssetClass] | None, Query()] = None,
) -> list[AssetOut]:
    query: Select[tuple[Asset]] = select(Asset)
    query = current_revision(query, Asset, as_of)
    if asset_class:
        query = query.where(Asset.asset_class.in_(asset_class))
    rows = (
        (await session.execute(query.order_by(Asset.name).limit(page.limit).offset(page.offset)))
        .scalars()
        .all()
    )
    return [_asset_out(row) for row in rows]


@router.get("/{asset_id}", response_model=AssetDetailOut)
async def get_asset(
    asset_id: uuid.UUID,
    session: SessionDep,
    graph: GraphDep,
    as_of: AsOfDep,
    max_hops: Annotated[int, Query(ge=1, le=8)] = 4,
) -> AssetDetailOut:
    query: Select[tuple[Asset]] = select(Asset).where(Asset.asset_id == asset_id)
    asset = (await session.execute(current_revision(query, Asset, as_of))).scalar_one_or_none()
    if asset is None:
        raise not_found("asset", asset_id)

    chain = await graph.discovery_chain(asset_id, max_hops=max_hops, as_of=as_of)

    exposure_query: Select[tuple[AssetExposure]] = select(AssetExposure).where(
        AssetExposure.asset_id == asset_id
    )
    exposures = (
        (
            await session.execute(
                recorded_by(exposure_query, AssetExposure, as_of).order_by(
                    AssetExposure.observed_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    targets = await graph.nodes([row.target_id for row in exposures])

    return AssetDetailOut(
        **_asset_out(asset).model_dump(),
        discovery_chain=[_path_out(path) for path in chain],
        exposures=[
            ExposureOut(
                id=row.asset_exposure_id,
                target=(
                    NodeRef(id=node.node_id, type=node.node_type, label=node.label, slug=node.slug)
                    if (node := targets.get(row.target_id))
                    else NodeRef(id=row.target_id, type=row.target_type, label="(unknown)")
                ),
                exposure_kind=row.exposure_kind,
                directness=row.directness,
                magnitude=row.magnitude,
                revenue_share=row.revenue_share,
                quantitative_basis=row.quantitative_basis,
                rationale=row.rationale,
                confidence=row.confidence,
                observed_at=row.observed_at,
            )
            for row in exposures
        ],
    )


@router.get("/{asset_id}/discovery-chain", response_model=list[DiscoveryPathOut])
async def discovery_chain(
    asset_id: uuid.UUID,
    graph: GraphDep,
    as_of: AsOfDep,
    max_hops: Annotated[int, Query(ge=1, le=8)] = 4,
) -> list[DiscoveryPathOut]:
    """Every route from a Process down to this Asset, shortest first."""
    return [
        _path_out(path)
        for path in await graph.discovery_chain(asset_id, max_hops=max_hops, as_of=as_of)
    ]


def _asset_out(asset: Asset) -> AssetOut:
    return AssetOut(
        id=asset.asset_id,
        name=asset.name,
        asset_class=asset.asset_class,
        identifiers=AssetIdentifiersOut(
            ticker=asset.ticker,
            exchange=asset.exchange,
            isin=asset.isin,
            commodity_code=asset.commodity_code,
            contract_code=asset.contract_code,
            benchmark=asset.benchmark,
            currency_pair=asset.currency_pair,
            currency_code=asset.currency_code,
        ),
        country=asset.country,
        currency=asset.currency,
        sector=asset.sector,
        industry=asset.industry,
        is_active=asset.is_active,
    )


def _path_out(path: object) -> DiscoveryPathOut:
    from econiq_graph import Path

    assert isinstance(path, Path)
    return DiscoveryPathOut(
        start=NodeRef(
            id=path.start.node_id,
            type=path.start.node_type,
            label=path.start.label,
            slug=path.start.slug,
        ),
        steps=[
            PathStepOut(
                relationship_type=edge.relationship_type,
                rationale=edge.rationale,
                to=NodeRef(id=node.node_id, type=node.node_type, label=node.label, slug=node.slug),
            )
            for edge, node in zip(path.edges, path.nodes[1:], strict=True)
        ],
        depth=path.depth,
        weight=path.weight,
    )
