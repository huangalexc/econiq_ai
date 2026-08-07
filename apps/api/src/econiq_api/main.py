"""The FastAPI application (issue #15).

Organised around **domain services**, not agents (tech rec §4). A caller asks
about Processes, Events, Capabilities and Assets — the ontology's own
vocabulary. Which agent produced a given field is answerable through
``/api/runs``, but it is never the shape of a route, because the agents are an
implementation detail of how the graph came to say what it says.

Two constraints this API is built to preserve:

**It is read-mostly.** The graph is written by agents through the orchestrator,
and everything they write carries an agent run, a prompt version and an
evaluation. A REST endpoint that created a Process directly would produce a row
with no provenance — indistinguishable from an evidenced one afterwards. So
there is no such endpoint, and the only writes here are operational.

**Every read accepts an as-of date.** Reconstructing what the system believed on
a past date is a requirement (ui_concept §32), not a feature to add later.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from econiq_data_models import DatabaseSettings
from fastapi import FastAPI

from econiq_api.deps import AppState
from econiq_api.routers import (
    assets,
    capabilities,
    events,
    evidence,
    graph,
    health,
    processes,
    runs,
)

DESCRIPTION = """\
Evidence-backed, Process-first investment research.

The chain every response can be walked back along:

    Documents → Claims → Events → Processes → States
    → Bottlenecks → Capabilities → Assets

Reads accept `as_of` to reconstruct the graph as it was at a past instant.
Scores are returned per family with their inputs attached — Thesis quality,
Asset quality and Trade quality are never combined.
"""


def create_app(settings: DatabaseSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state = AppState.create(settings)
        app.state.econiq = state
        try:
            yield
        finally:
            await state.close()

    app = FastAPI(
        title="econiq domain API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    for router in (
        health.router,
        processes.router,
        events.router,
        evidence.router,
        capabilities.router,
        assets.router,
        graph.router,
        runs.router,
    ):
        app.include_router(router)
    return app


app = create_app()
