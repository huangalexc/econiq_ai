"""Initial ontology schema (issue #2).

The canonical Document -> Claim -> Event -> Process -> State -> Bottleneck ->
Capability -> Asset chain, plus provenance, scores, quantitative observations
and embeddings.

Revision ID: 02909720020c
Revises: 
Create Date: 2026-08-06 17:17:03.636416+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '02909720020c'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: SQLAlchemy creates these enum types implicitly with the first table that uses
#: them, but does not drop them on downgrade — leaving them behind makes the
#: migration non-idempotent (a re-upgrade fails with "type already exists").
ENUM_TYPES = (
    "agent_run_status",
    "asset_class",
    "bottleneck_kind",
    "causal_role",
    "claim_type",
    "document_type",
    "embedding_kind",
    "entity_type",
    "epistemic_status",
    "event_type",
    "exposure_kind",
    "extraction_status",
    "logic_operator",
    "necessity",
    "process_archetype",
    "process_state_label",
    "process_status",
    "relationship_type",
    "requirement_node_kind",
    "score_family",
    "value_basis",
)


def upgrade() -> None:
    # Event deduplication, analog retrieval and semantic search all need it
    # (tech rec §7). Creating it here keeps a fresh database self-sufficient.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('model_versions',
    sa.Column('model_version_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='effort, max_tokens, etc.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('model_version_id', name=op.f('pk_model_versions')),
    sa.UniqueConstraint('provider', 'model', 'parameters', name=op.f('uq_model_versions_provider_model_parameters'))
    )
    op.create_table('nodes',
    sa.Column('node_id', sa.UUID(), nullable=False),
    sa.Column('node_type', sa.Enum('document', 'claim', 'event', 'process', 'bottleneck', 'capability', 'asset', name='entity_type'), nullable=False),
    sa.Column('slug', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('node_id', name=op.f('pk_nodes')),
    sa.UniqueConstraint('node_type', 'slug', name=op.f('uq_nodes_node_type_slug'))
    )
    op.create_index(op.f('ix_nodes_node_type'), 'nodes', ['node_type'], unique=False)
    op.create_table('prompt_versions',
    sa.Column('prompt_version_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('template', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('prompt_version_id', name=op.f('pk_prompt_versions')),
    sa.UniqueConstraint('name', 'version', 'content_hash', name=op.f('uq_prompt_versions_name_version_content_hash'))
    )
    op.create_table('agent_runs',
    sa.Column('agent_run_id', sa.UUID(), nullable=False),
    sa.Column('agent_name', sa.String(length=128), nullable=False),
    sa.Column('agent_version', sa.String(length=32), nullable=False),
    sa.Column('ontology_layer', sa.String(length=128), nullable=False),
    sa.Column('prompt_version_id', sa.UUID(), nullable=True),
    sa.Column('model_version_id', sa.UUID(), nullable=True),
    sa.Column('input_schema_version', sa.String(length=16), nullable=False),
    sa.Column('output_schema_version', sa.String(length=16), nullable=True),
    sa.Column('as_of', sa.DateTime(timezone=True), nullable=False, comment='Point-in-time cut-off the agent was given (ontology §33).'),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Enum('running', 'succeeded', 'abstained', 'failed', 'rejected', name='agent_run_status'), nullable=False),
    sa.Column('input_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('output_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('evaluation', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Deterministic check results for this run.'),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=True),
    sa.Column('latency_ms', sa.Float(), nullable=True),
    sa.Column('trigger_event_id', sa.UUID(), nullable=True, comment='Event that triggered this run, for staged propagation (ontology §46).'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.model_version_id'], name=op.f('fk_agent_runs_model_version_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.prompt_version_id'], name=op.f('fk_agent_runs_prompt_version_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('agent_run_id', name=op.f('pk_agent_runs'))
    )
    op.create_index(op.f('ix_agent_runs_agent_name'), 'agent_runs', ['agent_name'], unique=False)
    op.create_index(op.f('ix_agent_runs_trigger_event_id'), 'agent_runs', ['trigger_event_id'], unique=False)
    op.create_table('asset_states',
    sa.Column('asset_state_id', sa.UUID(), nullable=False),
    sa.Column('asset_id', sa.UUID(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('fundamental', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('valuation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('market_structure', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('technical', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source', sa.String(length=128), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['nodes.node_id'], name=op.f('fk_asset_states_asset_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('asset_state_id', name=op.f('pk_asset_states'))
    )
    op.create_index(op.f('ix_asset_states_asset_id'), 'asset_states', ['asset_id'], unique=False)
    op.create_index('ix_asset_states_asset_observed', 'asset_states', ['asset_id', 'observed_at'], unique=False)
    op.create_table('documents',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=128), nullable=False),
    sa.Column('publisher', sa.String(length=256), nullable=True),
    sa.Column('author', sa.String(length=256), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('document_type', sa.Enum('news_article', 'government_announcement', 'legislation', 'regulatory_filing', 'earnings_release', 'earnings_transcript', 'investor_presentation', 'company_filing', 'industry_report', 'statistical_release', 'quantitative_dataset', 'other', name='document_type'), nullable=False),
    sa.Column('publication_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('language', sa.String(length=8), nullable=False),
    sa.Column('storage_uri', sa.Text(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('extraction_status', sa.Enum('pending', 'parsing', 'parsed', 'extracted', 'failed', 'skipped', name='extraction_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('retrieved_at >= publication_time', name=op.f('ck_documents_retrieved_after_published')),
    sa.ForeignKeyConstraint(['document_id'], ['nodes.node_id'], name=op.f('fk_documents_document_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('document_id', name=op.f('pk_documents')),
    sa.UniqueConstraint('content_hash', name=op.f('uq_documents_content_hash')),
    comment='Immutable source documents. Never updated in place.'
    )
    op.create_index(op.f('ix_documents_extraction_status'), 'documents', ['extraction_status'], unique=False)
    op.create_index(op.f('ix_documents_publication_time'), 'documents', ['publication_time'], unique=False)
    op.create_index(op.f('ix_documents_publisher'), 'documents', ['publisher'], unique=False)
    op.create_index(op.f('ix_documents_source'), 'documents', ['source'], unique=False)
    op.create_table('embeddings',
    sa.Column('embedding_id', sa.UUID(), nullable=False),
    sa.Column('node_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Enum('document_body', 'claim_text', 'event_description', 'process_description', 'capability_description', name='embedding_kind'), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('dimensions', sa.Integer(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
    sa.Column('source_hash', sa.String(length=64), nullable=False, comment='Hash of the embedded text; detects staleness.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.node_id'], name=op.f('fk_embeddings_node_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('embedding_id', name=op.f('pk_embeddings')),
    sa.UniqueConstraint('node_id', 'kind', 'model', name=op.f('uq_embeddings_node_id_kind_model'))
    )
    op.create_index(op.f('ix_embeddings_node_id'), 'embeddings', ['node_id'], unique=False)
    op.create_index('ix_embeddings_vector', 'embeddings', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('asset_candidates',
    sa.Column('asset_candidate_id', sa.UUID(), nullable=False),
    sa.Column('proposed_name', sa.String(length=256), nullable=False),
    sa.Column('proposed_ticker', sa.String(length=32), nullable=True),
    sa.Column('proposed_exchange', sa.String(length=32), nullable=True),
    sa.Column('asset_class', sa.Enum('common_stock', 'etf', 'commodity', 'currency', 'bond', 'index', name='asset_class'), nullable=False),
    sa.Column('capability_id', sa.UUID(), nullable=True),
    sa.Column('process_id', sa.UUID(), nullable=True),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('resolved_asset_id', sa.UUID(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_asset_candidates_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['capability_id'], ['nodes.node_id'], name=op.f('fk_asset_candidates_capability_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['process_id'], ['nodes.node_id'], name=op.f('fk_asset_candidates_process_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['resolved_asset_id'], ['nodes.node_id'], name=op.f('fk_asset_candidates_resolved_asset_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('asset_candidate_id', name=op.f('pk_asset_candidates'))
    )
    op.create_index(op.f('ix_asset_candidates_agent_run_id'), 'asset_candidates', ['agent_run_id'], unique=False)
    op.create_table('asset_exposures',
    sa.Column('asset_exposure_id', sa.UUID(), nullable=False),
    sa.Column('asset_id', sa.UUID(), nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=False),
    sa.Column('target_type', sa.Enum('document', 'claim', 'event', 'process', 'bottleneck', 'capability', 'asset', name='entity_type'), nullable=False),
    sa.Column('exposure_kind', sa.Enum('revenue', 'incremental_earnings', 'capacity', 'market_share', 'production_capability', 'strategic_positioning', 'geographic', name='exposure_kind'), nullable=False),
    sa.Column('directness', sa.String(length=16), nullable=False),
    sa.Column('magnitude', sa.Float(), nullable=False),
    sa.Column('revenue_share', sa.Float(), nullable=True),
    sa.Column('quantitative_basis', sa.Text(), nullable=True),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("target_type IN ('process', 'capability')", name=op.f('ck_asset_exposures_exposure_target_type')),
    sa.CheckConstraint('magnitude >= 0 AND magnitude <= 10', name=op.f('ck_asset_exposures_magnitude_range')),
    sa.CheckConstraint('revenue_share IS NULL OR quantitative_basis IS NOT NULL', name=op.f('ck_asset_exposures_revenue_share_needs_basis')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_asset_exposures_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['asset_id'], ['nodes.node_id'], name=op.f('fk_asset_exposures_asset_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['target_id'], ['nodes.node_id'], name=op.f('fk_asset_exposures_target_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('asset_exposure_id', name=op.f('pk_asset_exposures'))
    )
    op.create_index(op.f('ix_asset_exposures_agent_run_id'), 'asset_exposures', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_asset_exposures_asset_id'), 'asset_exposures', ['asset_id'], unique=False)
    op.create_index('ix_asset_exposures_asset_target', 'asset_exposures', ['asset_id', 'target_id', 'observed_at'], unique=False)
    op.create_index(op.f('ix_asset_exposures_target_id'), 'asset_exposures', ['target_id'], unique=False)
    op.create_table('assets',
    sa.Column('asset_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('asset_class', sa.Enum('common_stock', 'etf', 'commodity', 'currency', 'bond', 'index', name='asset_class'), nullable=False),
    sa.Column('ticker', sa.String(length=32), nullable=True),
    sa.Column('exchange', sa.String(length=32), nullable=True),
    sa.Column('isin', sa.String(length=12), nullable=True),
    sa.Column('figi', sa.String(length=12), nullable=True),
    sa.Column('cik', sa.String(length=16), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('sector', sa.String(length=128), nullable=True),
    sa.Column('industry', sa.String(length=128), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True, comment='NULL means this is the current revision.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("asset_class NOT IN ('common_stock', 'etf') OR ticker IS NOT NULL", name=op.f('ck_assets_listed_assets_need_ticker')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_assets_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['asset_id'], ['nodes.node_id'], name=op.f('fk_assets_asset_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('asset_id', 'revision', name=op.f('pk_assets'))
    )
    op.create_index(op.f('ix_assets_agent_run_id'), 'assets', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_assets_asset_class'), 'assets', ['asset_class'], unique=False)
    op.create_index(op.f('ix_assets_ticker'), 'assets', ['ticker'], unique=False)
    op.create_index('uq_assets_current', 'assets', [sa.literal_column('asset_id')], unique=True, postgresql_where=sa.text('valid_to IS NULL'))
    op.create_table('bottlenecks',
    sa.Column('bottleneck_id', sa.UUID(), nullable=False),
    sa.Column('process_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('kind', sa.Enum('physical_capacity', 'input_supply', 'processing_capacity', 'infrastructure', 'regulatory_permitting', 'capital', 'labor_skills', 'technology', 'logistics', 'other', name='bottleneck_kind'), nullable=False),
    sa.Column('currently_binding', sa.Boolean(), nullable=False),
    sa.Column('demand_pressure', sa.Float(), nullable=True),
    sa.Column('supply_elasticity', sa.Float(), nullable=True),
    sa.Column('time_to_expand', sa.Float(), nullable=True),
    sa.Column('current_constraint', sa.Float(), nullable=True),
    sa.Column('relief_indicators', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True, comment='NULL means this is the current revision.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_bottlenecks_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['bottleneck_id'], ['nodes.node_id'], name=op.f('fk_bottlenecks_bottleneck_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['process_id'], ['nodes.node_id'], name=op.f('fk_bottlenecks_process_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('bottleneck_id', 'revision', name=op.f('pk_bottlenecks'))
    )
    op.create_index(op.f('ix_bottlenecks_agent_run_id'), 'bottlenecks', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_bottlenecks_currently_binding'), 'bottlenecks', ['currently_binding'], unique=False)
    op.create_index(op.f('ix_bottlenecks_kind'), 'bottlenecks', ['kind'], unique=False)
    op.create_index(op.f('ix_bottlenecks_process_id'), 'bottlenecks', ['process_id'], unique=False)
    op.create_index('uq_bottlenecks_current', 'bottlenecks', [sa.literal_column('bottleneck_id')], unique=True, postgresql_where=sa.text('valid_to IS NULL'))
    op.create_table('capabilities',
    sa.Column('capability_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('slug', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('aliases', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True, comment='NULL means this is the current revision.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_capabilities_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['capability_id'], ['nodes.node_id'], name=op.f('fk_capabilities_capability_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('capability_id', 'revision', name=op.f('pk_capabilities'))
    )
    op.create_index(op.f('ix_capabilities_agent_run_id'), 'capabilities', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_capabilities_slug'), 'capabilities', ['slug'], unique=False)
    op.create_index('uq_capabilities_current', 'capabilities', [sa.literal_column('capability_id')], unique=True, postgresql_where=sa.text('valid_to IS NULL'))
    op.create_table('capability_requirements',
    sa.Column('requirement_id', sa.UUID(), nullable=False),
    sa.Column('bottleneck_id', sa.UUID(), nullable=True),
    sa.Column('process_id', sa.UUID(), nullable=True),
    sa.Column('root_node_id', sa.UUID(), nullable=False),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True, comment='NULL means this is the current revision.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('bottleneck_id IS NOT NULL OR process_id IS NOT NULL', name=op.f('ck_capability_requirements_requirement_anchored')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_capability_requirements_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['bottleneck_id'], ['nodes.node_id'], name=op.f('fk_capability_requirements_bottleneck_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['process_id'], ['nodes.node_id'], name=op.f('fk_capability_requirements_process_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('requirement_id', 'revision', name=op.f('pk_capability_requirements'))
    )
    op.create_index(op.f('ix_capability_requirements_agent_run_id'), 'capability_requirements', ['agent_run_id'], unique=False)
    op.create_index('uq_capability_requirements_current', 'capability_requirements', [sa.literal_column('requirement_id')], unique=True, postgresql_where=sa.text('valid_to IS NULL'))
    op.create_table('claims',
    sa.Column('claim_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('claim_type', sa.Enum('reported_claim', 'derived_fact', 'inference', 'hypothesis', name='claim_type'), nullable=False),
    sa.Column('assertion_source', sa.String(length=32), nullable=True, comment='Finer-grained attribution: company_forecast, analyst_opinion, …'),
    sa.Column('attributed_to', sa.String(length=256), nullable=True),
    sa.Column('source_location', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('extraction_confidence', sa.Float(), nullable=False),
    sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('stated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_claims_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['claim_id'], ['nodes.node_id'], name=op.f('fk_claims_claim_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.document_id'], name=op.f('fk_claims_document_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('claim_id', name=op.f('pk_claims'))
    )
    op.create_index(op.f('ix_claims_agent_run_id'), 'claims', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_claims_claim_type'), 'claims', ['claim_type'], unique=False)
    op.create_index(op.f('ix_claims_document_id'), 'claims', ['document_id'], unique=False)
    op.create_table('events',
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('event_type', sa.Enum('policy_announcement', 'policy_enactment', 'regulatory_action', 'government_funding', 'corporate_action', 'guidance_change', 'capex_announcement', 'capacity_change', 'supply_disruption', 'demand_shift', 'price_move', 'technology_milestone', 'macro_policy', 'data_release', 'other', name='event_type'), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('independent_source_count', sa.Integer(), nullable=False),
    sa.Column('novelty', sa.Float(), nullable=False),
    sa.Column('materiality', sa.Float(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('epistemic_status', sa.Enum('observed', 'inferred', 'hypothesized', 'contradicted', 'unknown', name='epistemic_status'), nullable=False),
    sa.Column('contradictions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('propagated_at', sa.DateTime(timezone=True), nullable=True, comment='When this Event was propagated downstream; NULL means pending.'),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True, comment='NULL means this is the current revision.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=op.f('ck_events_confidence_range')),
    sa.CheckConstraint('independent_source_count >= 1', name=op.f('ck_events_sources_positive')),
    sa.CheckConstraint('materiality >= 0 AND materiality <= 10', name=op.f('ck_events_materiality_range')),
    sa.CheckConstraint('novelty >= 0 AND novelty <= 10', name=op.f('ck_events_novelty_range')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_events_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['event_id'], ['nodes.node_id'], name=op.f('fk_events_event_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('event_id', 'revision', name=op.f('pk_events'))
    )
    op.create_index(op.f('ix_events_agent_run_id'), 'events', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_events_event_type'), 'events', ['event_type'], unique=False)
    op.create_index(op.f('ix_events_occurred_at'), 'events', ['occurred_at'], unique=False)
    op.create_index('uq_events_current', 'events', [sa.literal_column('event_id')], unique=True, postgresql_where=sa.text('valid_to IS NULL'))
    op.create_table('evidence_links',
    sa.Column('evidence_link_id', sa.UUID(), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column('evidence_id', sa.UUID(), nullable=False),
    sa.Column('supports', sa.Boolean(), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('retracted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_evidence_links_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['evidence_id'], ['nodes.node_id'], name=op.f('fk_evidence_links_evidence_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subject_id'], ['nodes.node_id'], name=op.f('fk_evidence_links_subject_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('evidence_link_id', name=op.f('pk_evidence_links'))
    )
    op.create_index(op.f('ix_evidence_links_agent_run_id'), 'evidence_links', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_evidence_links_evidence_id'), 'evidence_links', ['evidence_id'], unique=False)
    op.create_index('ix_evidence_links_subject', 'evidence_links', ['subject_id', 'supports'], unique=False)
    op.create_index(op.f('ix_evidence_links_subject_id'), 'evidence_links', ['subject_id'], unique=False)
    op.create_table('process_states',
    sa.Column('process_state_id', sa.UUID(), nullable=False),
    sa.Column('process_id', sa.UUID(), nullable=False),
    sa.Column('archetype', sa.Enum('infrastructure_s_curve', 'commodity_supply_cycle', 'industrial_bottleneck', 'regulatory_implementation', 'business_model_disruption', name='process_archetype'), nullable=False),
    sa.Column('categorical_state', sa.Enum('discovery', 'early_adoption', 'acceleration', 'infrastructure_expansion', 'saturation', 'maturity', 'weak_demand', 'demand_recovery', 'inventory_draw', 'supply_tightness', 'price_acceleration', 'supply_response', 'oversupply', 'downcycle', 'constraint_emerging', 'constraint_binding', 'response_mobilization', 'buildout', 'capacity_delivery', 'constraint_relieved', 'announced', 'enacted', 'rulemaking', 'implementation', 'compliance_buildout', 'enforcement', 'normalization', 'trigger', 'experimentation', 'behavior_shift', 'substitution', 'incumbent_response', 'reallocation', 'new_equilibrium', name='process_state_label'), nullable=False),
    sa.Column('state_confidence', sa.Float(), nullable=False),
    sa.Column('transition_beliefs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('transition_indicators', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reversal_indicators', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('previous_state_id', sa.UUID(), nullable=True),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('recorded_at >= observed_at', name=op.f('ck_process_states_recorded_after_observed')),
    sa.CheckConstraint('state_confidence >= 0 AND state_confidence <= 1', name=op.f('ck_process_states_state_confidence_range')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_process_states_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['previous_state_id'], ['process_states.process_state_id'], name=op.f('fk_process_states_previous_state_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['process_id'], ['nodes.node_id'], name=op.f('fk_process_states_process_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('process_state_id', name=op.f('pk_process_states'))
    )
    op.create_index(op.f('ix_process_states_agent_run_id'), 'process_states', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_process_states_categorical_state'), 'process_states', ['categorical_state'], unique=False)
    op.create_index(op.f('ix_process_states_process_id'), 'process_states', ['process_id'], unique=False)
    op.create_index('ix_process_states_process_observed', 'process_states', ['process_id', 'observed_at'], unique=False)
    op.create_table('processes',
    sa.Column('process_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('slug', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('archetype', sa.Enum('infrastructure_s_curve', 'commodity_supply_cycle', 'industrial_bottleneck', 'regulatory_implementation', 'business_model_disruption', name='process_archetype'), nullable=True),
    sa.Column('archetype_confidence', sa.Float(), nullable=True),
    sa.Column('status', sa.Enum('candidate', 'active', 'dormant', 'invalidated', 'merged', 'concluded', name='process_status'), nullable=False),
    sa.Column('merged_into', sa.UUID(), nullable=True),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True, comment='NULL means this is the current revision.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'merged' OR merged_into IS NOT NULL", name=op.f('ck_processes_merged_needs_target')),
    sa.CheckConstraint('archetype_confidence IS NULL OR archetype IS NOT NULL', name=op.f('ck_processes_confidence_requires_archetype')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_processes_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['merged_into'], ['nodes.node_id'], name=op.f('fk_processes_merged_into'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['process_id'], ['nodes.node_id'], name=op.f('fk_processes_process_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('process_id', 'revision', name=op.f('pk_processes'))
    )
    op.create_index(op.f('ix_processes_agent_run_id'), 'processes', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_processes_archetype'), 'processes', ['archetype'], unique=False)
    op.create_index(op.f('ix_processes_slug'), 'processes', ['slug'], unique=False)
    op.create_index(op.f('ix_processes_status'), 'processes', ['status'], unique=False)
    op.create_index('uq_processes_current', 'processes', [sa.literal_column('process_id')], unique=True, postgresql_where=sa.text('valid_to IS NULL'))
    op.create_table('quantitative_observations',
    sa.Column('observation_id', sa.UUID(), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column('metric', sa.String(length=128), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('unit', sa.String(length=32), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=True),
    sa.Column('period_type', sa.String(length=16), nullable=True),
    sa.Column('reported_vs_derived', sa.String(length=16), nullable=False),
    sa.Column('restated', sa.Boolean(), nullable=False),
    sa.Column('restates_observation_id', sa.UUID(), nullable=True),
    sa.Column('source_document_id', sa.UUID(), nullable=True),
    sa.Column('source_location', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("reported_vs_derived IN ('reported', 'derived')", name=op.f('ck_quantitative_observations_reported_or_derived')),
    sa.CheckConstraint('period_end IS NULL OR period_start IS NULL OR period_end >= period_start', name=op.f('ck_quantitative_observations_period_ordered')),
    sa.ForeignKeyConstraint(['restates_observation_id'], ['quantitative_observations.observation_id'], name=op.f('fk_quantitative_observations_restates_observation_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_document_id'], ['documents.document_id'], name=op.f('fk_quantitative_observations_source_document_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subject_id'], ['nodes.node_id'], name=op.f('fk_quantitative_observations_subject_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('observation_id', name=op.f('pk_quantitative_observations'))
    )
    op.create_index('ix_quant_obs_subject_metric', 'quantitative_observations', ['subject_id', 'metric', 'period_end'], unique=False)
    op.create_index(op.f('ix_quantitative_observations_metric'), 'quantitative_observations', ['metric'], unique=False)
    op.create_index(op.f('ix_quantitative_observations_subject_id'), 'quantitative_observations', ['subject_id'], unique=False)
    op.create_table('relationships',
    sa.Column('relationship_id', sa.UUID(), nullable=False),
    sa.Column('source_id', sa.UUID(), nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=False),
    sa.Column('relationship_type', sa.Enum('influences', 'creates', 'requires', 'expressed_by', 'affects', 'supports', 'contradicts', 'supersedes', 'derived_from', name='relationship_type'), nullable=False),
    sa.Column('causal_role', sa.Enum('driver', 'mechanism', name='causal_role'), nullable=True),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True, comment='NULL means this is the current revision.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("causal_role IS NULL OR relationship_type = 'influences'", name=op.f('ck_relationships_causal_role_only_on_influences')),
    sa.CheckConstraint('source_id <> target_id', name=op.f('ck_relationships_no_self_edges')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_relationships_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_id'], ['nodes.node_id'], name=op.f('fk_relationships_source_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['target_id'], ['nodes.node_id'], name=op.f('fk_relationships_target_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('relationship_id', 'revision', name=op.f('pk_relationships'))
    )
    op.create_index(op.f('ix_relationships_agent_run_id'), 'relationships', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_relationships_relationship_type'), 'relationships', ['relationship_type'], unique=False)
    op.create_index(op.f('ix_relationships_source_id'), 'relationships', ['source_id'], unique=False)
    op.create_index('ix_relationships_source_type', 'relationships', ['source_id', 'relationship_type'], unique=False)
    op.create_index(op.f('ix_relationships_target_id'), 'relationships', ['target_id'], unique=False)
    op.create_index('ix_relationships_target_type', 'relationships', ['target_id', 'relationship_type'], unique=False)
    op.create_index('uq_relationships_current', 'relationships', [sa.literal_column('relationship_id')], unique=True, postgresql_where=sa.text('valid_to IS NULL'))
    op.create_table('event_claims',
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('claim_id', sa.UUID(), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_event_claims_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.claim_id'], name=op.f('fk_event_claims_claim_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['event_id'], ['nodes.node_id'], name=op.f('fk_event_claims_event_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('event_id', 'claim_id', name=op.f('pk_event_claims'))
    )
    op.create_index(op.f('ix_event_claims_agent_run_id'), 'event_claims', ['agent_run_id'], unique=False)
    op.create_table('process_state_features',
    sa.Column('process_state_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('basis', sa.Enum('measured', 'estimated', name='value_basis'), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.CheckConstraint('value >= 0 AND value <= 10', name=op.f('ck_process_state_features_feature_range')),
    sa.ForeignKeyConstraint(['process_state_id'], ['process_states.process_state_id'], name=op.f('fk_process_state_features_process_state_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('process_state_id', 'name', name=op.f('pk_process_state_features'))
    )
    op.create_table('requirement_nodes',
    sa.Column('requirement_node_id', sa.UUID(), nullable=False),
    sa.Column('requirement_id', sa.UUID(), nullable=False),
    sa.Column('requirement_revision', sa.Integer(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('group', 'capability', name='requirement_node_kind'), nullable=False),
    sa.Column('operator', sa.Enum('and', 'or', name='logic_operator'), nullable=True),
    sa.Column('label', sa.String(length=256), nullable=True),
    sa.Column('capability_id', sa.UUID(), nullable=True),
    sa.Column('necessity', sa.Enum('required', 'optional', name='necessity'), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.CheckConstraint("(kind = 'group' AND operator IS NOT NULL AND capability_id IS NULL) OR (kind = 'capability' AND capability_id IS NOT NULL AND operator IS NULL)", name=op.f('ck_requirement_nodes_node_shape')),
    sa.CheckConstraint('weight >= 0 AND weight <= 1', name=op.f('ck_requirement_nodes_weight_range')),
    sa.ForeignKeyConstraint(['capability_id'], ['nodes.node_id'], name=op.f('fk_requirement_nodes_capability_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['parent_id'], ['requirement_nodes.requirement_node_id'], name=op.f('fk_requirement_nodes_parent_id'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requirement_id', 'requirement_revision'], ['capability_requirements.requirement_id', 'capability_requirements.revision'], name=op.f('fk_requirement_nodes_requirement_id_requirement_revision'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('requirement_node_id', name=op.f('pk_requirement_nodes'))
    )
    op.create_index('ix_requirement_nodes_requirement', 'requirement_nodes', ['requirement_id', 'requirement_revision'], unique=False)
    op.create_table('scorecards',
    sa.Column('scorecard_id', sa.UUID(), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column('subject_type', sa.Enum('document', 'claim', 'event', 'process', 'bottleneck', 'capability', 'asset', name='entity_type'), nullable=False),
    sa.Column('family', sa.Enum('thesis_quality', 'asset_quality', 'trade_quality', name='score_family'), nullable=False),
    sa.Column('composite', sa.Float(), nullable=True),
    sa.Column('composite_method', sa.String(length=64), nullable=True),
    sa.Column('process_state_id', sa.UUID(), nullable=True, comment='State the subject was in when scored — scores are state-conditioned.'),
    sa.Column('agent_run_id', sa.UUID(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("family <> 'trade_quality'", name=op.f('ck_scorecards_trade_quality_is_v2')),
    sa.CheckConstraint('composite IS NULL OR composite_method IS NOT NULL', name=op.f('ck_scorecards_composite_needs_method')),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.agent_run_id'], name=op.f('fk_scorecards_agent_run_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['process_state_id'], ['process_states.process_state_id'], name=op.f('fk_scorecards_process_state_id'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subject_id'], ['nodes.node_id'], name=op.f('fk_scorecards_subject_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('scorecard_id', name=op.f('pk_scorecards'))
    )
    op.create_index(op.f('ix_scorecards_agent_run_id'), 'scorecards', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_scorecards_family'), 'scorecards', ['family'], unique=False)
    op.create_index('ix_scorecards_subject_family', 'scorecards', ['subject_id', 'family', 'observed_at'], unique=False)
    op.create_index(op.f('ix_scorecards_subject_id'), 'scorecards', ['subject_id'], unique=False)
    op.create_table('score_dimensions',
    sa.Column('scorecard_id', sa.UUID(), nullable=False),
    sa.Column('dimension', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('method', sa.String(length=32), nullable=False),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.CheckConstraint('value >= 0 AND value <= 10', name=op.f('ck_score_dimensions_score_range')),
    sa.ForeignKeyConstraint(['scorecard_id'], ['scorecards.scorecard_id'], name=op.f('fk_score_dimensions_scorecard_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('scorecard_id', 'dimension', name=op.f('pk_score_dimensions'))
    )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('score_dimensions')
    op.drop_index(op.f('ix_scorecards_subject_id'), table_name='scorecards')
    op.drop_index('ix_scorecards_subject_family', table_name='scorecards')
    op.drop_index(op.f('ix_scorecards_family'), table_name='scorecards')
    op.drop_index(op.f('ix_scorecards_agent_run_id'), table_name='scorecards')
    op.drop_table('scorecards')
    op.drop_index('ix_requirement_nodes_requirement', table_name='requirement_nodes')
    op.drop_table('requirement_nodes')
    op.drop_table('process_state_features')
    op.drop_index(op.f('ix_event_claims_agent_run_id'), table_name='event_claims')
    op.drop_table('event_claims')
    op.drop_index('uq_relationships_current', table_name='relationships', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index('ix_relationships_target_type', table_name='relationships')
    op.drop_index(op.f('ix_relationships_target_id'), table_name='relationships')
    op.drop_index('ix_relationships_source_type', table_name='relationships')
    op.drop_index(op.f('ix_relationships_source_id'), table_name='relationships')
    op.drop_index(op.f('ix_relationships_relationship_type'), table_name='relationships')
    op.drop_index(op.f('ix_relationships_agent_run_id'), table_name='relationships')
    op.drop_table('relationships')
    op.drop_index(op.f('ix_quantitative_observations_subject_id'), table_name='quantitative_observations')
    op.drop_index(op.f('ix_quantitative_observations_metric'), table_name='quantitative_observations')
    op.drop_index('ix_quant_obs_subject_metric', table_name='quantitative_observations')
    op.drop_table('quantitative_observations')
    op.drop_index('uq_processes_current', table_name='processes', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index(op.f('ix_processes_status'), table_name='processes')
    op.drop_index(op.f('ix_processes_slug'), table_name='processes')
    op.drop_index(op.f('ix_processes_archetype'), table_name='processes')
    op.drop_index(op.f('ix_processes_agent_run_id'), table_name='processes')
    op.drop_table('processes')
    op.drop_index('ix_process_states_process_observed', table_name='process_states')
    op.drop_index(op.f('ix_process_states_process_id'), table_name='process_states')
    op.drop_index(op.f('ix_process_states_categorical_state'), table_name='process_states')
    op.drop_index(op.f('ix_process_states_agent_run_id'), table_name='process_states')
    op.drop_table('process_states')
    op.drop_index(op.f('ix_evidence_links_subject_id'), table_name='evidence_links')
    op.drop_index('ix_evidence_links_subject', table_name='evidence_links')
    op.drop_index(op.f('ix_evidence_links_evidence_id'), table_name='evidence_links')
    op.drop_index(op.f('ix_evidence_links_agent_run_id'), table_name='evidence_links')
    op.drop_table('evidence_links')
    op.drop_index('uq_events_current', table_name='events', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index(op.f('ix_events_occurred_at'), table_name='events')
    op.drop_index(op.f('ix_events_event_type'), table_name='events')
    op.drop_index(op.f('ix_events_agent_run_id'), table_name='events')
    op.drop_table('events')
    op.drop_index(op.f('ix_claims_document_id'), table_name='claims')
    op.drop_index(op.f('ix_claims_claim_type'), table_name='claims')
    op.drop_index(op.f('ix_claims_agent_run_id'), table_name='claims')
    op.drop_table('claims')
    op.drop_index('uq_capability_requirements_current', table_name='capability_requirements', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index(op.f('ix_capability_requirements_agent_run_id'), table_name='capability_requirements')
    op.drop_table('capability_requirements')
    op.drop_index('uq_capabilities_current', table_name='capabilities', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index(op.f('ix_capabilities_slug'), table_name='capabilities')
    op.drop_index(op.f('ix_capabilities_agent_run_id'), table_name='capabilities')
    op.drop_table('capabilities')
    op.drop_index('uq_bottlenecks_current', table_name='bottlenecks', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index(op.f('ix_bottlenecks_process_id'), table_name='bottlenecks')
    op.drop_index(op.f('ix_bottlenecks_kind'), table_name='bottlenecks')
    op.drop_index(op.f('ix_bottlenecks_currently_binding'), table_name='bottlenecks')
    op.drop_index(op.f('ix_bottlenecks_agent_run_id'), table_name='bottlenecks')
    op.drop_table('bottlenecks')
    op.drop_index('uq_assets_current', table_name='assets', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index(op.f('ix_assets_ticker'), table_name='assets')
    op.drop_index(op.f('ix_assets_asset_class'), table_name='assets')
    op.drop_index(op.f('ix_assets_agent_run_id'), table_name='assets')
    op.drop_table('assets')
    op.drop_index(op.f('ix_asset_exposures_target_id'), table_name='asset_exposures')
    op.drop_index('ix_asset_exposures_asset_target', table_name='asset_exposures')
    op.drop_index(op.f('ix_asset_exposures_asset_id'), table_name='asset_exposures')
    op.drop_index(op.f('ix_asset_exposures_agent_run_id'), table_name='asset_exposures')
    op.drop_table('asset_exposures')
    op.drop_index(op.f('ix_asset_candidates_agent_run_id'), table_name='asset_candidates')
    op.drop_table('asset_candidates')
    op.drop_index('ix_embeddings_vector', table_name='embeddings', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_embeddings_node_id'), table_name='embeddings')
    op.drop_table('embeddings')
    op.drop_index(op.f('ix_documents_source'), table_name='documents')
    op.drop_index(op.f('ix_documents_publisher'), table_name='documents')
    op.drop_index(op.f('ix_documents_publication_time'), table_name='documents')
    op.drop_index(op.f('ix_documents_extraction_status'), table_name='documents')
    op.drop_table('documents')
    op.drop_index('ix_asset_states_asset_observed', table_name='asset_states')
    op.drop_index(op.f('ix_asset_states_asset_id'), table_name='asset_states')
    op.drop_table('asset_states')
    op.drop_index(op.f('ix_agent_runs_trigger_event_id'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_agent_name'), table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_table('prompt_versions')
    op.drop_index(op.f('ix_nodes_node_type'), table_name='nodes')
    op.drop_table('nodes')
    op.drop_table('model_versions')
    for enum_name in ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
