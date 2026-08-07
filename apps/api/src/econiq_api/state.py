"""What the API knows about the running pipeline.

Kept apart from the routers because the API is a *reader*: it does not construct
an LLM service or own an orchestrator, so it reports the pipeline's declared
shape and whichever handlers this deployment happens to have wired. Phase 0 runs
the orchestrator as a separate process, so from the API's side both are usually
empty — and saying so honestly is better than implying the pipeline is idle.
"""

from __future__ import annotations

_registry: set[str] = set()
_reconcilers: set[str] = set()


def set_runtime_registry(handlers: set[str], reconcilers: set[str]) -> None:
    """Record what an in-process orchestrator wired, if one exists."""
    _registry.clear()
    _registry.update(handlers)
    _reconcilers.clear()
    _reconcilers.update(reconcilers)


def runtime_registry() -> tuple[set[str], set[str]]:
    return set(_registry), set(_reconcilers)
