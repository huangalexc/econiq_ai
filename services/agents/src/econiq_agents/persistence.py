"""Writing agent output into the system of record.

Two responsibilities, kept apart on purpose:

``AgentRunRecorder`` persists the run itself — prompt version, model version,
tokens, cost, evaluation results. Every agent uses it, so the provenance chain
is uniform and issue #16's harness has one table to read.

``ClaimWriter`` persists Claims, but only after code has located each quote in
the document. A Claim whose span cannot be found is dropped and counted: the LLM
proposes, deterministic code verifies (agent doc §2.3), and the verification is
the whole reason a citation means anything.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from econiq_data_models import AgentRun, AgentRunStatus, Claim, ModelVersion, Node, PromptVersion
from econiq_ingestion import ParsedDocument
from econiq_llm import AgentRunResult, PromptTemplate
from econiq_ontology import EntityType, utcnow
from econiq_schemas import AgentInput, AgentOutput, ClaimExtractionOutput, ProposedClaim
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.document_agents import resolve_span


class AgentRunRecorder:
    """Persists an ``AgentRunResult`` as the provenance row everything cites."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def record[TOut: AgentOutput](
        self,
        result: AgentRunResult[TOut],
        *,
        payload: AgentInput,
        prompt: PromptTemplate,
        ontology_layer: str,
        provider: str,
        trigger_event_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        attribution = result.attribution
        model = attribution.model.split(":", 1)[-1]
        usage = result.usage

        async with self.session_factory() as session:
            prompt_version_id = await self._prompt_version(session, prompt)
            model_version_id = await self._model_version(session, provider, model)
            await session.flush()

            agent_run_id = uuid.uuid4()
            session.add(
                AgentRun(
                    agent_run_id=agent_run_id,
                    agent_name=attribution.agent_name,
                    agent_version=attribution.agent_version,
                    ontology_layer=ontology_layer,
                    prompt_version_id=prompt_version_id,
                    model_version_id=model_version_id,
                    input_schema_version=payload.schema_version,
                    output_schema_version=attribution.output_schema_version,
                    as_of=payload.as_of,
                    finished_at=utcnow(),
                    # A run whose output failed a deterministic check is
                    # `rejected`, not `succeeded`: it produced a valid object
                    # that the system does not accept.
                    status=(
                        AgentRunStatus.SUCCEEDED
                        if result.evaluation.passed
                        else AgentRunStatus.REJECTED
                    ),
                    input_payload=payload.model_dump(mode="json"),
                    output_payload=result.output.model_dump(mode="json"),
                    evaluation={
                        "passed": result.evaluation.passed,
                        "checks": [
                            {"name": c.name, "passed": c.passed, "detail": c.detail}
                            for c in result.evaluation.checks
                        ],
                    },
                    attempts=len(result.calls),
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_usd=result.cost_usd,
                    latency_ms=sum(call.latency_ms for call in result.calls),
                    trigger_event_id=trigger_event_id,
                )
            )
            await session.commit()
        return agent_run_id

    async def _prompt_version(self, session: AsyncSession, prompt: PromptTemplate) -> uuid.UUID:
        existing = await session.execute(
            select(PromptVersion.prompt_version_id).where(
                PromptVersion.name == prompt.name,
                PromptVersion.version == prompt.version,
                PromptVersion.content_hash == prompt.content_hash,
            )
        )
        found = existing.scalar_one_or_none()
        if found is not None:
            return found
        prompt_version_id = uuid.uuid4()
        session.add(
            PromptVersion(
                prompt_version_id=prompt_version_id,
                name=prompt.name,
                version=prompt.version,
                content_hash=prompt.content_hash,
                template=prompt.template,
            )
        )
        return prompt_version_id

    async def _model_version(self, session: AsyncSession, provider: str, model: str) -> uuid.UUID:
        existing = await session.execute(
            select(ModelVersion.model_version_id).where(
                ModelVersion.provider == provider, ModelVersion.model == model
            )
        )
        found = existing.scalar_one_or_none()
        if found is not None:
            return found
        model_version_id = uuid.uuid4()
        session.add(ModelVersion(model_version_id=model_version_id, provider=provider, model=model))
        return model_version_id


@dataclass(frozen=True, slots=True)
class ClaimPersistResult:
    claim_ids: list[uuid.UUID] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    """Claims dropped because their quote is not in the document."""

    @property
    def accepted(self) -> int:
        return len(self.claim_ids)

    @property
    def hallucination_rate(self) -> float:
        """Fraction of proposed Claims whose span could not be found.

        The headline extraction-quality metric of issue #6, computed rather than
        estimated.
        """
        total = self.accepted + len(self.rejected)
        return len(self.rejected) / total if total else 0.0


class ClaimWriter:
    """Persists extracted Claims with verified source locations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def persist(
        self,
        *,
        document_id: uuid.UUID,
        output: ClaimExtractionOutput,
        parsed: ParsedDocument,
        agent_run_id: uuid.UUID,
    ) -> ClaimPersistResult:
        accepted: list[tuple[uuid.UUID, ProposedClaim, dict[str, object]]] = []
        rejected: list[str] = []

        for proposed in output.claims:
            quote = proposed.source_location.quote
            span = resolve_span(quote, parsed) if quote else None
            if span is None:
                rejected.append(proposed.text)
                continue
            accepted.append(
                (
                    uuid.uuid4(),
                    proposed,
                    {
                        "quote": quote,
                        "char_start": span.char_start,
                        "char_end": span.char_end,
                        "section": span.section_heading,
                        "section_index": span.section_index,
                        "paragraph": proposed.source_location.paragraph,
                        "page": proposed.source_location.page,
                    },
                )
            )

        if accepted:
            async with self.session_factory() as session:
                for claim_id, _, _ in accepted:
                    session.add(Node(node_id=claim_id, node_type=EntityType.CLAIM))
                await session.flush()
                for claim_id, proposed, location in accepted:
                    session.add(
                        Claim(
                            claim_id=claim_id,
                            document_id=document_id,
                            text=proposed.text,
                            claim_type=proposed.claim_type,
                            assertion_source=proposed.assertion_source.value,
                            attributed_to=proposed.attributed_to,
                            source_location=location,
                            extraction_confidence=proposed.extraction_confidence,
                            entities=[e.model_dump(mode="json") for e in proposed.entities],
                            stated_at=proposed.stated_at,
                            agent_run_id=agent_run_id,
                        )
                    )
                await session.commit()

        return ClaimPersistResult(
            claim_ids=[claim_id for claim_id, _, _ in accepted], rejected=rejected
        )
