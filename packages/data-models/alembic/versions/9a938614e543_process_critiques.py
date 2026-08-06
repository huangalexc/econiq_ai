"""Process critiques (issue #10).

Adversarial findings against a Process, kept append-only. A thesis that survived
attack is stronger than one that was never attacked, and that is only visible if
the attacks stay on the record.

Revision ID: 9a938614e543
Revises: 95c7b7c1d224
Create Date: 2026-08-06 19:52:34.816553+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = '9a938614e543'
down_revision: str | None = '95c7b7c1d224'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('critiques',
    sa.Column('critique_id', sa.UUID(), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column(
        'subject_type',
        postgresql.ENUM(name='entity_type', create_type=False),
        nullable=False,
    ),
    sa.Column('kind', sa.Enum('unsupported_assumption', 'missing_causal_link', 'contradictory_evidence', 'alternative_explanation', 'historical_counterexample', 'falsifying_indicator', 'spurious_correlation', name='critique_kind'), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('severity', sa.Float(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('testable_with', sa.Text(), nullable=True),
    sa.Column('is_most_damaging', sa.Boolean(), nullable=False),
    sa.Column('status', sa.Enum('open', 'addressed', 'dismissed', 'confirmed', name='critique_status'), nullable=False),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('supporting_claim_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('severity >= 0 AND severity <= 10', name=op.f('ck_critiques_severity_range')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_critiques_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subject_id'], ['nodes.node_id'], name=op.f('fk_critiques_subject_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('critique_id', name=op.f('pk_critiques'))
    )
    op.create_index(op.f('ix_critiques_agent_run_id'), 'critiques', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_critiques_kind'), 'critiques', ['kind'], unique=False)
    op.create_index(op.f('ix_critiques_status'), 'critiques', ['status'], unique=False)
    op.create_index(op.f('ix_critiques_subject_id'), 'critiques', ['subject_id'], unique=False)
    op.create_index('ix_critiques_subject_status', 'critiques', ['subject_id', 'status', 'observed_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_critiques_subject_status', table_name='critiques')
    op.drop_index(op.f('ix_critiques_subject_id'), table_name='critiques')
    op.drop_index(op.f('ix_critiques_status'), table_name='critiques')
    op.drop_index(op.f('ix_critiques_kind'), table_name='critiques')
    op.drop_index(op.f('ix_critiques_agent_run_id'), table_name='critiques')
    op.drop_table('critiques')
    op.execute("DROP TYPE IF EXISTS critique_kind")
    op.execute("DROP TYPE IF EXISTS critique_status")
