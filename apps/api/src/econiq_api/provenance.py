"""The provenance envelope (issues #24, #25; ui_concept §23, §29).

§23 makes [Explain] a universal primitive and lists what every explanation must
carry: conclusion, supporting factors, contradictory factors, source evidence,
**model version, timestamp, confidence**. The last three are the same three
every time, whatever is being explained — a score, a State assignment, a Claim,
a ranking — so they are one shape here rather than three near-identical ones
bolted onto three response models.

The chain already exists in the database: every derived row carries an
``agent_run_id``, every run carries a prompt version and a model version. What
was missing was a way to *read* it in one hop. Before this, answering "which
model wrote this Claim?" took three round trips, which is enough friction that a
UI quietly stops asking — and an explanation nobody can afford to fetch is not
an explanation.

Loaded in batches. A timeline of forty evidence items resolving provenance one
row at a time is forty queries, and the screen that most needs provenance is the
one with the most rows on it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from econiq_data_models import AgentRun, ModelVersion, PromptVersion
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from econiq_api.schemas import ProvenanceOut


async def load(
    session: AsyncSession, run_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, ProvenanceOut]:
    """Resolve agent runs to their model and prompt versions, in one query."""
    wanted = {run_id for run_id in run_ids if run_id is not None}
    if not wanted:
        return {}

    rows = await session.execute(
        select(AgentRun, PromptVersion, ModelVersion)
        .outerjoin(PromptVersion, PromptVersion.prompt_version_id == AgentRun.prompt_version_id)
        .outerjoin(ModelVersion, ModelVersion.model_version_id == AgentRun.model_version_id)
        .where(AgentRun.agent_run_id.in_(wanted))
    )

    resolved: dict[uuid.UUID, ProvenanceOut] = {}
    for run, prompt, model in rows.all():
        evaluation = run.evaluation or {}
        resolved[run.agent_run_id] = ProvenanceOut(
            agent_run_id=run.agent_run_id,
            agent_name=run.agent_name,
            agent_version=run.agent_version,
            model=model.model if model is not None else None,
            provider=model.provider if model is not None else None,
            prompt_name=prompt.name if prompt is not None else None,
            prompt_version=prompt.version if prompt is not None else None,
            # Truncated for display. The full hash is in `prompt_versions`; what
            # a reader needs on screen is whether two rows came from the same
            # prompt text, and twelve characters answers that.
            prompt_content_hash=prompt.content_hash[:12] if prompt is not None else None,
            as_of=run.as_of,
            recorded_at=run.finished_at or run.started_at,
            status=run.status.value,
            evaluation_passed=(bool(evaluation.get("passed")) if "passed" in evaluation else None),
            advisories=list(evaluation.get("advisories", [])),
        )
    return resolved


def attach[T](
    rows: Sequence[T],
    provenance: dict[uuid.UUID, ProvenanceOut],
    *,
    run_id: str = "agent_run_id",
) -> list[ProvenanceOut | None]:
    """Line provenance up with the rows it belongs to, positionally.

    Returns ``None`` where a row has no run rather than omitting it. A missing
    explanation is itself worth showing: a row nobody can attribute is either a
    seed or a defect, and both are things the reader should see rather than a
    blank space where an explanation would be.
    """
    return [provenance.get(getattr(row, run_id)) if getattr(row, run_id) else None for row in rows]
