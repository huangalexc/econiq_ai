"""The Document → Claims stage, wired together (issue #6).

Classify, then extract, then persist with verified spans. Kept as an explicit
function rather than hidden inside the agents so the orchestrator (issue #14)
can schedule the stage, and so a failure has one obvious place to look.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from econiq_data_models import Document as DocumentRow
from econiq_ingestion import ParsedDocument
from econiq_llm import LLMService, OutputValidationError, ProviderRefusalError
from econiq_ontology import DocumentType
from econiq_schemas import ClaimExtractionInput, DocumentClassifierInput, InformationMode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from econiq_agents.document_agents import (
    ClaimExtractionAgent,
    DocumentClassifierAgent,
    QuoteGroundingEvaluator,
)
from econiq_agents.persistence import AgentRunRecorder, ClaimPersistResult, ClaimWriter
from econiq_agents.prompts import CLAIM_EXTRACTION_V1, DOCUMENT_CLASSIFIER_V1

logger = logging.getLogger("econiq.agents")


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    document_id: uuid.UUID
    information_mode: InformationMode | None
    claims: ClaimPersistResult | None
    classifier_run_id: uuid.UUID | None = None
    extraction_run_id: uuid.UUID | None = None
    skipped_reason: str | None = None

    @property
    def ran_extraction(self) -> bool:
        return self.claims is not None


class DocumentExtractionStage:
    """Classify a document, then extract and persist its Claims."""

    def __init__(
        self,
        service: LLMService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.classifier = DocumentClassifierAgent(service, evaluators=[])
        self.extractor = ClaimExtractionAgent(service, evaluators=[QuoteGroundingEvaluator()])
        self.runs = AgentRunRecorder(session_factory)
        self.claims = ClaimWriter(session_factory)

    async def run(self, document_id: uuid.UUID, parsed: ParsedDocument) -> ExtractionOutcome:
        row = await self._load(document_id)
        as_of = row.publication_time

        classification = await self.classifier.run(
            DocumentClassifierInput(
                as_of=as_of,
                document_id=str(document_id),
                title=row.title,
                publisher=row.publisher,
                source=row.source,
                publication_time=row.publication_time,
                text=parsed.text,
            )
        )
        classifier_run_id = await self.runs.record(
            classification,
            payload=self._last_input(as_of, document_id, row, parsed),
            prompt=DOCUMENT_CLASSIFIER_V1,
            ontology_layer=self.classifier.ontology_layer,
            provider=self.service.provider.name,
        )

        mode = classification.output.primary_information_mode
        if mode is InformationMode.QUANTITATIVE:
            # Numbers go through the deterministic ETL service, not an LLM
            # (tech rec §20). Extracting them from prose here would be exactly
            # the reconstruction the specs warn against.
            logger.info("document %s is quantitative; deferring to the ETL service", document_id)
            return ExtractionOutcome(
                document_id=document_id,
                information_mode=mode,
                claims=None,
                classifier_run_id=classifier_run_id,
                skipped_reason="quantitative content is handled by the ETL service (issue #48)",
            )

        extraction_input = ClaimExtractionInput(
            as_of=as_of,
            document_id=str(document_id),
            document_type=classification.output.document_type or DocumentType.OTHER,
            publisher=row.publisher,
            publication_time=row.publication_time,
            text=parsed.text,
        )
        try:
            extraction = await self.extractor.run(extraction_input)
        except (OutputValidationError, ProviderRefusalError) as exc:
            logger.warning("claim extraction failed for %s: %s", document_id, exc)
            return ExtractionOutcome(
                document_id=document_id,
                information_mode=mode,
                claims=None,
                classifier_run_id=classifier_run_id,
                skipped_reason=str(exc),
            )

        extraction_run_id = await self.runs.record(
            extraction,
            payload=extraction_input,
            prompt=CLAIM_EXTRACTION_V1,
            ontology_layer=self.extractor.ontology_layer,
            provider=self.service.provider.name,
        )
        persisted = await self.claims.persist(
            document_id=document_id,
            output=extraction.output,
            parsed=parsed,
            agent_run_id=extraction_run_id,
        )
        if persisted.rejected:
            logger.warning(
                "dropped %d ungrounded claims from %s", len(persisted.rejected), document_id
            )

        return ExtractionOutcome(
            document_id=document_id,
            information_mode=mode,
            claims=persisted,
            classifier_run_id=classifier_run_id,
            extraction_run_id=extraction_run_id,
        )

    async def _load(self, document_id: uuid.UUID) -> DocumentRow:
        async with self.session_factory() as session:
            row = await session.get(DocumentRow, document_id)
        if row is None:
            raise LookupError(f"no document {document_id}")
        return row

    @staticmethod
    def _last_input(
        as_of: object, document_id: uuid.UUID, row: DocumentRow, parsed: ParsedDocument
    ) -> DocumentClassifierInput:
        return DocumentClassifierInput(
            as_of=row.publication_time,
            document_id=str(document_id),
            title=row.title,
            publisher=row.publisher,
            source=row.source,
            publication_time=row.publication_time,
            text=parsed.text,
        )
