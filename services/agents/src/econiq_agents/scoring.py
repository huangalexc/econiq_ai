"""Writing scorecards.

Scores are append-only observations of one family about one subject, and the
family separation of ontology §17 is enforced by the ontology model before
anything reaches the database. Every dimension carries the inputs it was
computed from, because the UI's universal [Explain] primitive (issue #25) has to
decompose any score it shows — a score that cannot be taken apart is an
assertion, not a measurement.

Phase 0 writes single-dimension scorecards from the agents that produce them.
The Thesis Scoring agent (issue #65) composes the full multidimensional
scorecard; nothing here computes a composite.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from econiq_data_models import Scorecard, ScoreDimension
from econiq_ontology import EntityType, ScoreFamily
from econiq_ontology.quality import FAMILY_DIMENSIONS, FAMILY_SUBJECTS
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ScoringError(ValueError):
    """A scorecard that would violate the family separation of ontology §17."""


class ScorecardWriter:
    """Appends scorecards, refusing any that mixes families."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def record(
        self,
        *,
        subject_id: uuid.UUID,
        subject_type: EntityType,
        family: ScoreFamily,
        observed_at: datetime,
        dimensions: Sequence[tuple[StrEnum, float, dict[str, float]]],
        agent_run_id: uuid.UUID | None = None,
        process_state_id: uuid.UUID | None = None,
        method: str = "llm_judgement",
    ) -> uuid.UUID:
        if subject_type not in FAMILY_SUBJECTS[family]:
            raise ScoringError(f"{family.value} may not score a {subject_type.value}")
        allowed = FAMILY_DIMENSIONS[family]
        unknown = {dimension.value for dimension, _, _ in dimensions} - allowed
        if unknown:
            raise ScoringError(f"dimensions not in family {family.value}: {sorted(unknown)}")

        scorecard_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                Scorecard(
                    scorecard_id=scorecard_id,
                    subject_id=subject_id,
                    subject_type=subject_type,
                    family=family,
                    observed_at=observed_at,
                    # No composite: a single-dimension contribution is not a
                    # summary of the family, and inventing one here would put a
                    # number on screen that nothing stands behind.
                    composite=None,
                    process_state_id=process_state_id,
                    agent_run_id=agent_run_id,
                )
            )
            await session.flush()
            for dimension, value, inputs in dimensions:
                session.add(
                    ScoreDimension(
                        scorecard_id=scorecard_id,
                        dimension=dimension.value,
                        value=value,
                        confidence=inputs.get("confidence", 0.7),
                        method=method,
                        inputs=inputs,
                    )
                )
            await session.commit()
        return scorecard_id

    async def latest(self, subject_id: uuid.UUID, family: ScoreFamily) -> Scorecard | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Scorecard)
                .where(Scorecard.subject_id == subject_id, Scorecard.family == family)
                .order_by(Scorecard.observed_at.desc(), Scorecard.recorded_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
