"""FastAPI domain API over the ontology (issue #15).

Read-mostly and organised around domain services rather than agents (tech rec
§4). Every read accepts an ``as_of`` cut-off, and every derived number is
returned with the means to explain it.
"""

from econiq_api.deps import AppState
from econiq_api.main import create_app

__all__ = ["AppState", "create_app"]
