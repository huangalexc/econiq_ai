"""Fixtures for the database-backed ingestion tests."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from econiq_data_models import Base, DatabaseSettings, create_engine, create_session_factory
from sqlalchemy import text


@pytest_asyncio.fixture
async def session_factory():
    """A session factory against a truncated database.

    Truncating rather than recreating keeps the suite fast while guaranteeing
    each test starts from an empty graph.
    """
    if not os.getenv("ECONIQ_DB_URL"):
        pytest.skip("ECONIQ_DB_URL is not set; start the compose stack first")

    engine = create_engine(DatabaseSettings())
    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
