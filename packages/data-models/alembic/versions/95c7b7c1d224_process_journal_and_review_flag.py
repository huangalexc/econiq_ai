"""Process journal and human-review flag (issue #8).

The revision tables record what the system believes; the journal records why it
changed its mind, in the form a human reads (PRD §21). `requires_review` is the
hook of agent doc §23 — a false Process contaminates the whole graph, so newly
discovered ones are flagged rather than silently trusted.

Revision ID: 95c7b7c1d224
Revises: 07f982dcedd0
Create Date: 2026-08-06 18:36:32.930734+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = '95c7b7c1d224'
down_revision: str | None = '07f982dcedd0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('journal_entries',
    sa.Column('journal_entry_id', sa.UUID(), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    # `entity_type` already exists from the initial migration; create_type=False
    # stops Alembic emitting a second CREATE TYPE for it.
    sa.Column(
        'subject_type',
        postgresql.ENUM(name='entity_type', create_type=False),
        nullable=False,
    ),
    sa.Column('kind', sa.Enum('created', 'evidence_added', 'belief_change', 'state_change', 'review_requested', 'invalidated', name='journal_entry_kind'), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('confidence_before', sa.Float(), nullable=True),
    sa.Column('confidence_after', sa.Float(), nullable=True),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='Signed changes: [{direction, statement, rationale}, …].'),
    sa.Column('triggering_event_id', sa.UUID(), nullable=True),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_journal_entries_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subject_id'], ['nodes.node_id'], name=op.f('fk_journal_entries_subject_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['triggering_event_id'], ['nodes.node_id'], name=op.f('fk_journal_entries_triggering_event_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('journal_entry_id', name=op.f('pk_journal_entries'))
    )
    op.create_index(op.f('ix_journal_entries_agent_run_id'), 'journal_entries', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_journal_entries_kind'), 'journal_entries', ['kind'], unique=False)
    op.create_index(op.f('ix_journal_entries_subject_id'), 'journal_entries', ['subject_id'], unique=False)
    op.create_index('ix_journal_entries_subject_time', 'journal_entries', ['subject_id', 'observed_at'], unique=False)
    op.create_index(op.f('ix_journal_entries_triggering_event_id'), 'journal_entries', ['triggering_event_id'], unique=False)
    op.add_column('processes', sa.Column('requires_review', sa.Boolean(), nullable=False, comment='Human review hook (agent doc §23). A false Process contaminates the whole graph, so newly discovered ones are flagged.'))
    op.create_index(op.f('ix_processes_requires_review'), 'processes', ['requires_review'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_processes_requires_review'), table_name='processes')
    op.drop_column('processes', 'requires_review')
    op.drop_index(op.f('ix_journal_entries_triggering_event_id'), table_name='journal_entries')
    op.drop_index('ix_journal_entries_subject_time', table_name='journal_entries')
    op.drop_index(op.f('ix_journal_entries_subject_id'), table_name='journal_entries')
    op.drop_index(op.f('ix_journal_entries_kind'), table_name='journal_entries')
    op.drop_index(op.f('ix_journal_entries_agent_run_id'), table_name='journal_entries')
    op.drop_table('journal_entries')
    op.execute("DROP TYPE IF EXISTS journal_entry_kind")
