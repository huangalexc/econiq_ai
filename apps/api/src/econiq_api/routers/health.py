"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from econiq_api.deps import SessionDep
from econiq_api.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(session: SessionDep) -> HealthOut:
    """Readiness, including the migration the database is actually on.

    The schema version matters: an API serving a database one migration behind
    will fail in ways that look like data problems rather than deployment ones.
    """
    database = True
    version: str | None = None
    try:
        version = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
    except Exception:
        database = False
    return HealthOut(
        status="ok" if database else "degraded", database=database, schema_version=version
    )
