"""Operational statistics over recorded agent runs (agent doc §21, §26).

Versioning every prompt is only worth the trouble if someone compares the
versions. This module is that comparison: it reads ``agent_runs`` — which every
agent already writes through ``AgentRunRecorder`` — and reports how a prompt
version behaved, so a prompt change can be argued about with numbers instead of
with a reading of the diff.

The statistics are deliberately the unglamorous ones: rejection rate, advisory
frequency, attempts per run, cost, latency. None of them say whether the output
was *good* — that is what the benchmarks are for. What they say is whether a
change made the system cheaper, more reliable, or more argumentative with its
own evaluators, and those are the failures that show up first and are usually
the reason a benchmark moved.

Agent doc §26's question — does this agent improve the downstream system? —
cannot be answered by a single number, and this module does not pretend to. It
narrows where to look.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from econiq_data_models import AgentRun, AgentRunStatus, ModelVersion, PromptVersion
from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class RunStats:
    """How one (agent, prompt version, model) combination behaved."""

    agent_name: str
    prompt_name: str | None
    prompt_version: str | None
    prompt_content_hash: str | None
    model: str | None
    runs: int
    rejected: int
    failed: int
    total_attempts: int
    total_cost_usd: float
    mean_latency_ms: float

    @property
    def rejection_rate(self) -> float:
        """Runs whose output a deterministic check refused.

        The most informative single number here. A prompt change that raises it
        is producing output the system will not accept, whatever it reads like.
        """
        return self.rejected / self.runs if self.runs else 0.0

    @property
    def failure_rate(self) -> float:
        return self.failed / self.runs if self.runs else 0.0

    @property
    def attempts_per_run(self) -> float:
        """Above 1.0 means the repair loop is being used — the schema is being missed."""
        return self.total_attempts / self.runs if self.runs else 0.0

    @property
    def cost_per_run(self) -> float:
        return self.total_cost_usd / self.runs if self.runs else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "agent_name": self.agent_name,
            "prompt": f"{self.prompt_name}@{self.prompt_version}",
            "prompt_content_hash": (
                self.prompt_content_hash[:12] if self.prompt_content_hash else None
            ),
            "model": self.model,
            "runs": self.runs,
            "rejection_rate": round(self.rejection_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "attempts_per_run": round(self.attempts_per_run, 3),
            "cost_per_run": round(self.cost_per_run, 6),
            "mean_latency_ms": round(self.mean_latency_ms, 1),
        }


@dataclass(frozen=True, slots=True)
class PromptComparison:
    """Two versions of one prompt, side by side."""

    agent_name: str
    baseline: RunStats
    candidate: RunStats

    @property
    def rejection_delta(self) -> float:
        return self.candidate.rejection_rate - self.baseline.rejection_rate

    @property
    def cost_delta(self) -> float:
        return self.candidate.cost_per_run - self.baseline.cost_per_run

    @property
    def regressed(self) -> bool:
        """A rise in refused output is a regression regardless of anything else."""
        return self.rejection_delta > 0

    def summary(self) -> str:
        direction = "worse" if self.regressed else "no worse"
        return (
            f"{self.agent_name}: {self.baseline.prompt_version} → "
            f"{self.candidate.prompt_version} is {direction} — rejection "
            f"{self.baseline.rejection_rate:.1%} → {self.candidate.rejection_rate:.1%}, "
            f"cost/run ${self.baseline.cost_per_run:.4f} → ${self.candidate.cost_per_run:.4f}, "
            f"over {self.baseline.runs} and {self.candidate.runs} runs"
        )


class RunLedger:
    """Reads the provenance table as an operational record."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def stats(
        self,
        *,
        agent_name: str | None = None,
        since: datetime | None = None,
    ) -> list[RunStats]:
        async with self.session_factory() as session:
            return await self._stats(session, agent_name=agent_name, since=since)

    async def _stats(
        self,
        session: AsyncSession,
        *,
        agent_name: str | None,
        since: datetime | None,
    ) -> list[RunStats]:
        rejected = func.sum(case((AgentRun.status == AgentRunStatus.REJECTED, 1), else_=0))
        failed = func.sum(case((AgentRun.status == AgentRunStatus.FAILED, 1), else_=0))

        query = (
            select(
                AgentRun.agent_name,
                PromptVersion.name,
                PromptVersion.version,
                PromptVersion.content_hash,
                ModelVersion.model,
                func.count().label("runs"),
                rejected.label("rejected"),
                failed.label("failed"),
                func.sum(AgentRun.attempts).label("attempts"),
                func.coalesce(func.sum(cast(AgentRun.cost_usd, Float)), 0.0).label("cost"),
                func.coalesce(func.avg(AgentRun.latency_ms), 0.0).label("latency"),
            )
            .select_from(AgentRun)
            .outerjoin(
                PromptVersion,
                PromptVersion.prompt_version_id == AgentRun.prompt_version_id,
            )
            .outerjoin(ModelVersion, ModelVersion.model_version_id == AgentRun.model_version_id)
            .group_by(
                AgentRun.agent_name,
                PromptVersion.name,
                PromptVersion.version,
                PromptVersion.content_hash,
                ModelVersion.model,
            )
            .order_by(AgentRun.agent_name, PromptVersion.version)
        )
        if agent_name is not None:
            query = query.where(AgentRun.agent_name == agent_name)
        if since is not None:
            query = query.where(AgentRun.started_at >= since)

        return [
            RunStats(
                agent_name=row[0],
                prompt_name=row[1],
                prompt_version=row[2],
                prompt_content_hash=row[3],
                model=row[4],
                runs=row[5],
                rejected=int(row[6] or 0),
                failed=int(row[7] or 0),
                total_attempts=int(row[8] or 0),
                total_cost_usd=float(row[9] or 0.0),
                mean_latency_ms=float(row[10] or 0.0),
            )
            for row in (await session.execute(query)).all()
        ]

    async def compare(
        self, agent_name: str, *, baseline: str, candidate: str
    ) -> PromptComparison | None:
        """Compare two prompt versions of one agent.

        Returns ``None`` when either version has no runs — a comparison against
        nothing is not a comparison, and returning a zeroed row would let a
        prompt ship on the strength of a statistic nobody computed.
        """
        rows = {s.prompt_version: s for s in await self.stats(agent_name=agent_name)}
        before, after = rows.get(baseline), rows.get(candidate)
        if before is None or after is None:
            return None
        return PromptComparison(agent_name=agent_name, baseline=before, candidate=after)

    async def unversioned_runs(self) -> list[uuid.UUID]:
        """Runs that cannot be attributed to a prompt version at all (§21)."""
        async with self.session_factory() as session:
            return list(
                (
                    await session.execute(
                        select(AgentRun.agent_run_id).where(AgentRun.prompt_version_id.is_(None))
                    )
                )
                .scalars()
                .all()
            )
