"""Declarative base, naming conventions and the temporal mixins.

Two rules shape this schema and are enforced by the mixins below:

**Nothing is destroyed.** Objects an agent can revise (Processes, Events,
Bottlenecks, Capabilities, Assets, Relationships) live in append-only tables
keyed by ``(id, revision)``. A revision is superseded by writing ``valid_to`` on
the old row and inserting a new one; a partial unique index guarantees exactly
one current revision per identity. Observations (States, exposures, scores,
quantitative data) are append-only by nature — a newer observation supersedes an
older one by being more recent (PRD §21, §30; ontology §33).

**Everything derived has provenance.** Every row an agent produced carries the
``agent_run_id`` that produced it, so any conclusion can be traced back to a
prompt version, a model, and the evidence it saw (agent doc §21).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Deterministic constraint names, so Alembic migrations are stable and
#: reviewable rather than full of generated identifiers.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """When the system learned this, as distinct from when it happened."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RevisionMixin(TimestampMixin):
    """Append-only revisions of a mutable entity.

    ``valid_to IS NULL`` marks the current revision. Subclasses must declare the
    identity column and call :func:`current_revision_index` in their
    ``__table_args__`` to enforce single-currency.
    """

    revision: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="NULL means this is the current revision.",
    )


class ObservationMixin(TimestampMixin):
    """A measurement or estimate about a point in time.

    ``observed_at`` is the as-of date the observation describes; ``recorded_at``
    is when the system wrote it. Point-in-time queries filter on both, which is
    what makes historical replay honest — a snapshot may only use rows whose
    ``recorded_at`` precedes the replay date (ontology §33; issue #39).
    """

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentProvenanceMixin:
    """Which agent run produced this row. Non-null for anything an agent wrote."""

    @staticmethod
    def agent_run_column(*, nullable: bool = True) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("agent_runs.agent_run_id", ondelete="RESTRICT"),
            nullable=nullable,
            index=True,
        )


def current_revision_index(table_name: str, identity_column: str) -> Index:
    """At most one current revision per identity."""
    return Index(
        f"uq_{table_name}_current",
        text(identity_column),
        unique=True,
        postgresql_where=text("valid_to IS NULL"),
    )


#: Dimension of the embedding column. One dimension across the system keeps a
#: single HNSW index usable; the model that produced each vector is recorded
#: alongside it so a re-embedding is detectable rather than silent (tech rec §7).
EMBEDDING_DIM = 1536
