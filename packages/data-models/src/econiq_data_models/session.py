"""Engine and session factories.

Async by default: the ingestion pipeline and agent orchestration are I/O-bound,
and a sync session in that path would serialize the whole stage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseSettings(BaseSettings):
    """Connection configuration (``ECONIQ_DB_*``)."""

    model_config = SettingsConfigDict(env_prefix="ECONIQ_DB_", env_file=".env", extra="ignore")

    url: str = "postgresql+psycopg://econiq:econiq@localhost:5432/econiq"
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 10

    @property
    def sync_url(self) -> str:
        """Alembic runs migrations synchronously."""
        return self.url.replace("+psycopg_async", "+psycopg")


def create_engine(settings: DatabaseSettings | None = None) -> AsyncEngine:
    settings = settings or DatabaseSettings()
    return create_async_engine(
        settings.url,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A transaction that commits on success and rolls back on any exception."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
