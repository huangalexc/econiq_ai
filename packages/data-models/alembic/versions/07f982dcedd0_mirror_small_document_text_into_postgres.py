"""Mirror small document text into Postgres.

Phase 0 agents read a document's text on nearly every run. Below a size
threshold the ingestion pipeline mirrors the normalized text here so that read
is a column, not an object-store round trip. The copy in S3 remains
authoritative (tech rec §8).

Revision ID: 07f982dcedd0
Revises: 02909720020c
Create Date: 2026-08-06 17:23:10.526416+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '07f982dcedd0'
down_revision: str | None = '02909720020c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('raw_content', sa.Text(), nullable=True, comment='Normalized text, mirrored here when small enough that agents should not pay an object-store round trip. The S3 copy stays authoritative.'))


def downgrade() -> None:
    op.drop_column('documents', 'raw_content')
