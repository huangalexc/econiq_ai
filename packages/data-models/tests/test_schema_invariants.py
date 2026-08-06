"""Structural invariants of the system of record.

These run offline against the SQLAlchemy metadata, so a schema change that
breaks a non-negotiable constraint fails in CI rather than in review.
"""

import pytest
from econiq_data_models import Base
from econiq_ontology import EntityType

#: Tables an agent writes to. Every one must carry the run that produced it,
#: because provenance is not optional (agent doc §21).
AGENT_WRITTEN = {
    "claims",
    "events",
    "event_claims",
    "processes",
    "process_states",
    "bottlenecks",
    "capabilities",
    "capability_requirements",
    "assets",
    "asset_candidates",
    "asset_exposures",
    "relationships",
    "evidence_links",
    "scorecards",
}

#: Revisable entities. Each needs the partial unique index that guarantees a
#: single current revision.
REVISIONED = {
    "events",
    "processes",
    "bottlenecks",
    "capabilities",
    "capability_requirements",
    "assets",
    "relationships",
}

#: Append-only observations. Each carries both an as-of and a recorded-at date,
#: which is what makes leakage detectable (ontology §33).
OBSERVATIONS = {
    "process_states",
    "asset_exposures",
    "asset_states",
    "scorecards",
    "quantitative_observations",
}


@pytest.mark.parametrize("table_name", sorted(AGENT_WRITTEN))
def test_agent_written_tables_record_their_provenance(table_name):
    assert "agent_run_id" in Base.metadata.tables[table_name].columns


@pytest.mark.parametrize("table_name", sorted(REVISIONED))
def test_revisioned_tables_have_exactly_one_current_revision(table_name):
    table = Base.metadata.tables[table_name]
    assert "revision" in table.columns
    assert "valid_from" in table.columns
    assert "valid_to" in table.columns
    partial = [
        index
        for index in table.indexes
        if index.unique and index.dialect_options["postgresql"].get("where") is not None
    ]
    assert partial, f"{table_name} has no single-current-revision index"


@pytest.mark.parametrize("table_name", sorted(OBSERVATIONS))
def test_observations_are_bitemporal(table_name):
    columns = Base.metadata.tables[table_name].columns
    assert "observed_at" in columns
    assert "recorded_at" in columns


def test_no_table_cascades_deletes_of_ontology_nodes():
    """Nothing is destroyed: a node deletion must be blocked, never propagated."""
    offenders = [
        f"{table.name}.{fk.parent.name}"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "nodes" and fk.ondelete != "RESTRICT"
    ]
    assert offenders == []


def test_the_graph_is_anchored_to_the_node_registry():
    relationships = Base.metadata.tables["relationships"]
    targets = {fk.parent.name: fk.column.table.name for fk in relationships.foreign_keys}
    assert targets["source_id"] == "nodes"
    assert targets["target_id"] == "nodes"


def test_entity_tables_exist_for_every_node_type():
    expected = {
        EntityType.DOCUMENT: "documents",
        EntityType.CLAIM: "claims",
        EntityType.EVENT: "events",
        EntityType.PROCESS: "processes",
        EntityType.BOTTLENECK: "bottlenecks",
        EntityType.CAPABILITY: "capabilities",
        EntityType.ASSET: "assets",
    }
    assert set(expected) == set(EntityType)
    for table_name in expected.values():
        assert table_name in Base.metadata.tables


def test_trade_quality_cannot_be_written_in_v1():
    checks = {c.name for c in Base.metadata.tables["scorecards"].constraints if c.name}
    assert any("trade_quality_is_v2" in name for name in checks)
