"""Point-in-time filtering, applied uniformly.

Every read in this API can be asked "as of when?", and the answer has to mean
the same thing everywhere. Two different notions of time are involved and
conflating them is the classic way a replay leaks:

* **Revisable entities** carry a validity window. As of a past instant, the
  correct revision is the one whose window contained it.
* **Observations** carry ``recorded_at``. As of a past instant, the correct set
  is those recorded at or before it — *not* those whose ``observed_at`` precedes
  it, because a State observation about July can be recorded in August and
  including it would leak knowledge the system did not have.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, func


def current_revision(query: Select[Any], model: Any, as_of: datetime | None) -> Select[Any]:
    """Restrict to the revision current at ``as_of`` (or now).

    The window predicate is applied even for a current read, rather than taking
    the ``valid_to IS NULL`` shortcut. Those two agree only while no revision is
    ever post-dated, and a scheduled correction is exactly the case where the
    shortcut would show a revision before it took effect. One definition of
    "current" that holds in both branches is worth the extra comparison.
    """
    cut = func.now() if as_of is None else as_of
    return query.where(
        model.valid_from <= cut,
        (model.valid_to.is_(None)) | (model.valid_to > cut),
    )


def recorded_by(query: Select[Any], model: Any, as_of: datetime | None) -> Select[Any]:
    """Restrict observations to those the system had recorded by ``as_of``."""
    if as_of is None:
        return query
    return query.where(model.recorded_at <= as_of)


def created_by(query: Select[Any], model: Any, as_of: datetime | None) -> Select[Any]:
    """Restrict immutable rows to those created by ``as_of``."""
    if as_of is None:
        return query
    return query.where(model.created_at <= as_of)
