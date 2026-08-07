"""Orchestration: transactional outbox and work queue (issue #14).

Postgres is the queue. The outbox makes a domain event part of the same commit
as the state change that produced it, so there is no window in which one
happened and the other did not. Work items are claimed with FOR UPDATE SKIP
LOCKED; see docs/orchestration.md for why this rather than a broker.

Revision ID: 0a323353553e
Revises: ab51215e8e9b
Create Date: 2026-08-07 12:24:57.509527+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = '0a323353553e'
down_revision: str | None = 'ab51215e8e9b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('outbox_events',
    sa.Column('outbox_event_id', sa.UUID(), nullable=False),
    sa.Column('event_name', sa.String(length=64), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=True),
    sa.Column(
        'subject_type',
        postgresql.ENUM(name='entity_type', create_type=False),
        nullable=True,
    ),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, comment='When the state change happened, not when it was dispatched.'),
    sa.Column('status', sa.Enum('pending', 'dispatched', name='outbox_status'), nullable=False),
    sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('outbox_event_id', name=op.f('pk_outbox_events'))
    )
    op.create_index(op.f('ix_outbox_events_event_name'), 'outbox_events', ['event_name'], unique=False)
    op.create_index(op.f('ix_outbox_events_status'), 'outbox_events', ['status'], unique=False)
    op.create_index(op.f('ix_outbox_events_subject_id'), 'outbox_events', ['subject_id'], unique=False)
    op.create_index('ix_outbox_pending', 'outbox_events', ['status', 'occurred_at'], unique=False)
    op.create_table('work_items',
    sa.Column('work_item_id', sa.UUID(), nullable=False),
    sa.Column('stage', sa.String(length=64), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=200), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Enum('pending', 'running', 'succeeded', 'failed', 'dead', 'superseded', name='work_status'), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False, comment='Lower runs first. Live material events outrank backfill.'),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='Backoff and time-based triggers both express themselves here.'),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('claimed_by', sa.String(length=128), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('trigger', sa.String(length=32), nullable=False, comment='event | reconciler | schedule | manual — how this was enqueued.'),
    sa.Column('source_event_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('attempts >= 0', name=op.f('ck_work_items_attempts_non_negative')),
    sa.CheckConstraint('max_attempts >= 1', name=op.f('ck_work_items_max_attempts_positive')),
    sa.ForeignKeyConstraint(['source_event_id'], ['outbox_events.outbox_event_id'], name=op.f('fk_work_items_source_event_id'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('work_item_id', name=op.f('pk_work_items'))
    )
    op.create_index('ix_work_items_claimable', 'work_items', ['status', 'priority', 'run_after'], unique=False)
    op.create_index(op.f('ix_work_items_stage'), 'work_items', ['stage'], unique=False)
    op.create_index(op.f('ix_work_items_status'), 'work_items', ['status'], unique=False)
    op.create_index(op.f('ix_work_items_subject_id'), 'work_items', ['subject_id'], unique=False)
    op.create_index('uq_work_items_open_key', 'work_items', ['idempotency_key'], unique=True, postgresql_where=sa.text("status IN ('pending', 'running')"))


def downgrade() -> None:
    op.drop_index('uq_work_items_open_key', table_name='work_items', postgresql_where=sa.text("status IN ('pending', 'running')"))
    op.drop_index(op.f('ix_work_items_subject_id'), table_name='work_items')
    op.drop_index(op.f('ix_work_items_status'), table_name='work_items')
    op.drop_index(op.f('ix_work_items_stage'), table_name='work_items')
    op.drop_index('ix_work_items_claimable', table_name='work_items')
    op.drop_table('work_items')
    op.drop_index('ix_outbox_pending', table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_subject_id'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_status'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_event_name'), table_name='outbox_events')
    op.drop_table('outbox_events')
    op.execute("DROP TYPE IF EXISTS work_status")
    op.execute("DROP TYPE IF EXISTS outbox_status")
