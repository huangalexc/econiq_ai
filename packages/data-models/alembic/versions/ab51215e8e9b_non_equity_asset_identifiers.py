"""Non-equity asset identifiers (issue #12).

A Commodity Supply Cycle is often expressed most cleanly by the commodity
itself, and a policy-driven Process by a currency. An assets table that only
knew about tickers would quietly force every thesis into the equity market.

Revision ID: ab51215e8e9b
Revises: 9a938614e543
Create Date: 2026-08-07 01:43:43.728875+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'ab51215e8e9b'
down_revision: str | None = '9a938614e543'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('asset_candidates', sa.Column('proposed_symbol', sa.String(length=32), nullable=True, comment='Commodity code or currency pair, for non-equity expressions.'))
    op.add_column('assets', sa.Column('commodity_code', sa.String(length=16), nullable=True))
    op.add_column('assets', sa.Column('contract_code', sa.String(length=32), nullable=True))
    op.add_column('assets', sa.Column('benchmark', sa.String(length=128), nullable=True))
    op.add_column('assets', sa.Column('currency_pair', sa.String(length=6), nullable=True))
    op.add_column('assets', sa.Column('currency_code', sa.String(length=3), nullable=True))
    op.create_index(op.f('ix_assets_commodity_code'), 'assets', ['commodity_code'], unique=False)
    op.create_index(op.f('ix_assets_currency_pair'), 'assets', ['currency_pair'], unique=False)
    op.create_check_constraint(op.f('ck_assets_commodities_need_a_code'), 'assets', "asset_class <> 'commodity' OR commodity_code IS NOT NULL OR contract_code IS NOT NULL OR benchmark IS NOT NULL")
    op.create_check_constraint(op.f('ck_assets_currencies_need_a_pair_or_code'), 'assets', "asset_class <> 'currency' OR currency_pair IS NOT NULL OR currency_code IS NOT NULL")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_assets_currencies_need_a_pair_or_code'), 'assets', type_='check')
    op.drop_constraint(op.f('ck_assets_commodities_need_a_code'), 'assets', type_='check')
    op.drop_index(op.f('ix_assets_currency_pair'), table_name='assets')
    op.drop_index(op.f('ix_assets_commodity_code'), table_name='assets')
    op.drop_column('assets', 'currency_code')
    op.drop_column('assets', 'currency_pair')
    op.drop_column('assets', 'benchmark')
    op.drop_column('assets', 'contract_code')
    op.drop_column('assets', 'commodity_code')
    op.drop_column('asset_candidates', 'proposed_symbol')
