"""Shared dependencies: the session, the as-of clock, and paging.

The one that matters is ``AsOf``. Every read in this API accepts a point-in-time
cut-off, threaded down into the queries. Reconstructing what the system believed
on a past date is a requirement (ui_concept §32), and an API that grows that
capability later never quite gets it — the discipline has to be present from the
first endpoint, so it is a dependency rather than an option.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from econiq_data_models import DatabaseSettings, create_engine, create_session_factory
from econiq_graph import GraphQueries
from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@dataclass(slots=True)
class AppState:
    """Long-lived resources, created once at startup."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    def create(cls, settings: DatabaseSettings | None = None) -> AppState:
        engine = create_engine(settings or DatabaseSettings())
        return cls(engine=engine, session_factory=create_session_factory(engine))

    async def close(self) -> None:
        await self.engine.dispose()


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.econiq
    return state


def get_session_factory(
    state: Annotated[AppState, Depends(get_state)],
) -> async_sessionmaker[AsyncSession]:
    return state.session_factory


async def get_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


def get_graph(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> GraphQueries:
    return GraphQueries(factory)


def as_of_param(
    as_of: Annotated[
        datetime | None,
        Query(
            description=(
                "Reconstruct the graph as it was at this instant. Omit for the "
                "current state. Revisions and observations recorded later are "
                "excluded, so a replay describes what was believed then."
            )
        ),
    ] = None,
) -> datetime | None:
    return as_of


@dataclass(frozen=True, slots=True)
class Page:
    """Offset paging.

    Honest about its limits: offset paging degrades on deep pages, and the
    screens this serves show ranked top-N rather than deep scroll. If a caller
    ever needs page 500, that is the signal to move to keyset paging, not to
    raise the cap.
    """

    limit: int
    offset: int


def page_param(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page:
    return Page(limit=limit, offset=offset)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
GraphDep = Annotated[GraphQueries, Depends(get_graph)]
AsOfDep = Annotated[datetime | None, Depends(as_of_param)]
PageDep = Annotated[Page, Depends(page_param)]
