"""Migration round-trip against a real Postgres.

Marked ``integration``: it needs the docker-compose stack. Run with
``make test-integration`` or ``pytest -m integration``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from econiq_data_models import Base, DatabaseSettings
from sqlalchemy import create_engine, inspect

pytestmark = pytest.mark.integration

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_config() -> Config:
    if not os.getenv("ECONIQ_DB_URL"):
        pytest.skip("ECONIQ_DB_URL is not set; start the compose stack first")
    config = Config(str(PACKAGE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PACKAGE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", DatabaseSettings().sync_url)
    return config


def test_upgrade_creates_every_table_and_downgrade_removes_them(alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_engine(DatabaseSettings().sync_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert set(Base.metadata.tables) <= tables

        command.downgrade(alembic_config, "base")
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert remaining == set()

        # Re-applying must succeed: enum types are dropped on downgrade too.
        command.upgrade(alembic_config, "head")
        assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
