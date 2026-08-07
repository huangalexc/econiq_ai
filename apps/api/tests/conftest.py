"""Fixtures: a truncated database and an ASGI client bound to it."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from econiq_api import create_app
from econiq_api.deps import AppState
from econiq_data_models import Base, DatabaseSettings, create_engine, create_session_factory
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


@pytest_asyncio.fixture
async def session_factory():
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


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncIterator[AsyncClient]:
    """An in-process client sharing the test's session factory.

    The app's own lifespan is bypassed so the client and the fixtures see the
    same truncated database rather than two independent engines.
    """
    app = create_app()
    app.state.econiq = AppState(engine=session_factory.kw["bind"], session_factory=session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
