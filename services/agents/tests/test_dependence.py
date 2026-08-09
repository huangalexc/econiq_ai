"""Cross-Event evidence dependence (issue #67, agent doc §10.2)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from econiq_agents.dependence import (
    Dependence,
    EvidenceItem,
    effective_sources,
    structural_dependencies,
    undecided_pairs,
)
from econiq_agents.independence_agent import (
    CorroborationEvaluator,
    EvidenceIndependenceAgent,
    ScopeEvaluator,
)
from econiq_llm import LLMService, ScriptedProvider
from econiq_ontology import EvidenceDependenceKind as Kind
from econiq_schemas import (
    EvidenceIndependenceInput,
    EvidenceIndependenceOutput,
    EvidencePair,
)

NOW = datetime(2026, 8, 1, tzinfo=UTC)

A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
DOC = uuid.uuid4()


def _item(event_id: uuid.UUID, **kwargs) -> EvidenceItem:
    return EvidenceItem(event_id=event_id, title=str(event_id)[:8], **kwargs)


def test_two_events_citing_one_document_are_one_source():
    """Definitional, so code decides it and the agent is never asked."""
    items = [
        _item(A, document_ids=frozenset({DOC})),
        _item(B, document_ids=frozenset({DOC})),
    ]

    found = structural_dependencies(items)

    assert len(found) == 1
    assert found[0].kind is Kind.SHARED_SOURCE
    assert found[0].confidence == 1.0
    assert found[0].detected_by == "computed"


def test_one_newsroom_reporting_twice_is_weaker_evidence_than_a_shared_filing():
    """The same outlet can report genuinely separate observations; the same
    document cannot be two of them."""
    shared_doc = structural_dependencies(
        [_item(A, document_ids=frozenset({DOC})), _item(B, document_ids=frozenset({DOC}))]
    )
    shared_publisher = structural_dependencies(
        [_item(A, publishers=frozenset({"Wire"})), _item(B, publishers=frozenset({"Wire"}))]
    )

    assert shared_publisher[0].confidence < shared_doc[0].confidence


def test_a_shared_document_does_not_also_raise_a_publisher_finding():
    """One relationship, one edge — otherwise the explanation double-counts."""
    items = [
        _item(A, document_ids=frozenset({DOC}), publishers=frozenset({"Wire"})),
        _item(B, document_ids=frozenset({DOC}), publishers=frozenset({"Wire"})),
    ]

    assert len(structural_dependencies(items)) == 1


def test_only_unsettled_pairs_reach_the_agent():
    """Sending settled pairs would spend budget re-deriving a set intersection,
    and would let the model disagree with a fact."""
    items = [
        _item(A, document_ids=frozenset({DOC})),
        _item(B, document_ids=frozenset({DOC})),
        _item(C),
    ]
    structural = structural_dependencies(items)

    undecided = undecided_pairs(items, structural)

    assert {frozenset(pair) for pair in undecided} == {
        frozenset({A, C}),
        frozenset({B, C}),
    }


def test_dependence_is_transitive_across_the_graph():
    """If A shares a filing with B and B a publisher with C, all three rest on
    one observation — the question is how many distinct observations there are."""
    items = [_item(A), _item(B), _item(C)]
    edges = [
        Dependence(A, B, Kind.SHARED_SOURCE, "…", 1.0, "computed"),
        Dependence(B, C, Kind.SHARED_SOURCE, "…", 0.6, "computed"),
    ]

    total, groups = effective_sources(items, edges)

    assert total == 1
    assert len(groups) == 1


def test_independent_events_are_not_collapsed():
    items = [_item(A), _item(B), _item(C)]

    total, groups = effective_sources(items, [])

    assert total == 3
    assert len(groups) == 3


def test_a_component_keeps_the_largest_source_count_within_it():
    """An Event already resolved from three independent reports is three
    sources; collapsing it to one because it shares a publisher would throw
    away work the Event layer did."""
    items = [
        _item(A, independent_source_count=3),
        _item(B, independent_source_count=1),
    ]
    edges = [Dependence(A, B, Kind.SHARED_SOURCE, "…", 0.6, "computed")]

    total, _ = effective_sources(items, edges)

    assert total == 3


def test_the_groups_travel_with_the_number():
    """A count without its grouping cannot be explained on a scorecard (#25)."""
    items = [_item(A), _item(B), _item(C)]
    edges = [Dependence(A, B, Kind.DERIVATIVE_REPORTING, "…", 0.8, "judged")]

    total, groups = effective_sources(items, edges)

    assert total == 2
    assert frozenset({A, B}) in groups
    assert frozenset({C}) in groups


# --------------------------------------------------------------------------- #
# The agent
# --------------------------------------------------------------------------- #


def _payload(*pairs: tuple[uuid.UUID, uuid.UUID]) -> EvidenceIndependenceInput:
    return EvidenceIndependenceInput(
        as_of=NOW,
        process_name="Minerals",
        events={str(A): "Stake taken", str(B): "Stake reported", str(C): "Train slips"},
        undecided=[
            EvidencePair(source_event_id=str(a), dependent_event_id=str(b)) for a, b in pairs
        ],
    )


def _output(*found: tuple[uuid.UUID, uuid.UUID, Kind]) -> str:
    return json.dumps(
        {
            "dependencies": [
                {
                    "source_event_id": str(a),
                    "dependent_event_id": str(b),
                    "kind": kind.value,
                    "rationale": "The second attributes the first.",
                    "confidence": 0.8,
                    "schema_version": "1.0.0",
                }
                for a, b, kind in found
            ],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def test_a_finding_about_a_pair_nobody_asked_about_is_rejected():
    """It either contradicts the structural pass, which read the rows, or
    invents a pair. Both corrupt the component grouping."""
    output = EvidenceIndependenceOutput.model_validate_json(
        _output((A, C, Kind.DERIVATIVE_REPORTING))
    )

    checks = ScopeEvaluator().evaluate(_payload((A, B)), output)

    assert checks[0].passed is False
    assert checks[0].blocking is True


def test_a_finding_in_the_reverse_direction_is_still_in_scope():
    """Which of the pair is the source is the agent's judgement to make."""
    output = EvidenceIndependenceOutput.model_validate_json(
        _output((B, A, Kind.DERIVATIVE_REPORTING))
    )

    assert ScopeEvaluator().evaluate(_payload((A, B)), output)[0].passed is True


def test_collapsing_most_of_the_evidence_is_flagged_advisory():
    """The more damaging of §10.2's two error directions: a false dependence
    silently reduces a well-evidenced thesis to one source."""
    output = EvidenceIndependenceOutput.model_validate_json(
        _output((A, B, Kind.REPEATED_CLAIM), (A, C, Kind.REPEATED_CLAIM))
    )

    checks = CorroborationEvaluator().evaluate(_payload((A, B), (A, C)), output)

    assert checks[0].passed is False
    assert checks[0].blocking is False


def test_finding_nothing_is_a_valid_answer():
    """Independence is the default and needs no assertion."""
    output = EvidenceIndependenceOutput.model_validate_json(_output())

    payload = _payload((A, B), (A, C), (B, C))
    assert ScopeEvaluator().evaluate(payload, output)[0].passed is True
    assert CorroborationEvaluator().evaluate(payload, output)[0].passed is True


async def test_the_agent_is_shown_only_the_pairs_it_must_decide():
    agent = EvidenceIndependenceAgent(LLMService(ScriptedProvider([]), observers=[]))

    content = agent.build_user_content(_payload((A, B)))

    assert str(A) in content and str(B) in content
    assert "Decide these pairs" in content
    # C appears as context but not as a pair to decide.
    assert f"- {A} and {C}" not in content


# --------------------------------------------------------------------------- #
# The stage, and the effect on the score
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402


@pytest.mark.integration
class TestIndependenceStage:
    @staticmethod
    async def _seed(session_factory, *, shared_document: bool) -> uuid.UUID:
        """Three Events. With `shared_document`, two cite one filing."""
        from econiq_data_models import (
            Claim,
            Document,
            Event,
            EventClaim,
            EvidenceLink,
            Node,
            Process,
        )
        from econiq_ontology import (
            ClaimType,
            DocumentType,
            EntityType,
            EpistemicStatus,
            EventType,
            ExtractionStatus,
            ProcessArchetype,
            ProcessStatus,
        )

        process_id = uuid.uuid4()
        async with session_factory() as session:
            session.add(Node(node_id=process_id, node_type=EntityType.PROCESS, slug="dep"))
            await session.flush()
            session.add(
                Process(
                    process_id=process_id,
                    revision=1,
                    name="Minerals",
                    slug="dep",
                    description="…",
                    archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                    status=ProcessStatus.ACTIVE,
                )
            )
            await session.flush()

            shared_doc_id = uuid.uuid4()
            if shared_document:
                session.add(Node(node_id=shared_doc_id, node_type=EntityType.DOCUMENT))
                await session.flush()
                session.add(
                    Document(
                        document_id=shared_doc_id,
                        source="filing",
                        publisher="Registry",
                        title="The filing",
                        document_type=DocumentType.REGULATORY_FILING,
                        publication_time=datetime.now(UTC),
                        retrieved_at=datetime.now(UTC),
                        content_hash=uuid.uuid4().hex,
                        extraction_status=ExtractionStatus.PARSED,
                    )
                )
                await session.flush()

            for index in range(3):
                event_id, claim_id = uuid.uuid4(), uuid.uuid4()
                session.add(Node(node_id=event_id, node_type=EntityType.EVENT))
                session.add(Node(node_id=claim_id, node_type=EntityType.CLAIM))
                document_id = shared_doc_id if shared_document and index < 2 else uuid.uuid4()
                if document_id != shared_doc_id:
                    session.add(Node(node_id=document_id, node_type=EntityType.DOCUMENT))
                await session.flush()
                if document_id != shared_doc_id:
                    session.add(
                        Document(
                            document_id=document_id,
                            source=f"wire-{index}",
                            publisher=f"Publisher {index}",
                            title="…",
                            document_type=DocumentType.NEWS_ARTICLE,
                            publication_time=datetime.now(UTC),
                            retrieved_at=datetime.now(UTC),
                            content_hash=uuid.uuid4().hex,
                            extraction_status=ExtractionStatus.PARSED,
                        )
                    )
                session.add(
                    Event(
                        event_id=event_id,
                        revision=1,
                        event_type=EventType.GOVERNMENT_FUNDING,
                        title=f"Event {index}",
                        description="…",
                        occurred_at=datetime.now(UTC),
                        entities=[],
                        independent_source_count=1,
                        novelty=7.0,
                        materiality=8.0,
                        confidence=0.9,
                        epistemic_status=EpistemicStatus.OBSERVED,
                        contradictions=[],
                    )
                )
                await session.flush()
                session.add(
                    Claim(
                        claim_id=claim_id,
                        document_id=document_id,
                        text=f"Claim {index}",
                        claim_type=ClaimType.REPORTED_CLAIM,
                        source_location={"quote": "x", "char_start": 0, "char_end": 1},
                        extraction_confidence=0.9,
                        entities=[],
                    )
                )
                await session.flush()
                session.add(EventClaim(event_id=event_id, claim_id=claim_id))
                session.add(
                    EvidenceLink(
                        evidence_link_id=uuid.uuid4(),
                        subject_id=process_id,
                        evidence_id=event_id,
                        supports=True,
                    )
                )
            await session.commit()
        return process_id

    @staticmethod
    def _stage(session_factory, *responses: str):
        from econiq_agents import IndependenceStage

        return IndependenceStage(
            LLMService(ScriptedProvider(responses), observers=[]), session_factory
        )

    async def test_a_shared_filing_reduces_the_effective_source_count(self, session_factory):
        """The whole point: four Events citing one filing are not four sources."""
        process_id = await self._seed(session_factory, shared_document=True)

        outcome = await self._stage(session_factory, _output()).run(process_id)

        assert outcome.naive_sources == 3
        assert outcome.effective_sources == 2
        assert outcome.collapsed == 1
        assert outcome.computed_count == 1

    async def test_independent_evidence_is_left_alone(self, session_factory):
        process_id = await self._seed(session_factory, shared_document=False)

        outcome = await self._stage(session_factory, _output()).run(process_id)

        assert outcome.effective_sources == outcome.naive_sources == 3
        assert outcome.collapsed == 0

    async def test_structural_findings_are_not_attributed_to_the_model(self, session_factory):
        """Crediting an agent run with a set intersection would make the
        provenance chain say a model found something code did."""
        from econiq_data_models import EvidenceDependence
        from sqlalchemy import select

        process_id = await self._seed(session_factory, shared_document=True)
        await self._stage(session_factory, _output()).run(process_id)

        async with session_factory() as session:
            rows = (await session.execute(select(EvidenceDependence))).scalars().all()

        computed = [row for row in rows if row.detected_by == "computed"]
        assert computed
        assert all(row.agent_run_id is None for row in computed)

    async def test_a_rejected_judgement_leaves_the_structural_findings_standing(
        self, session_factory
    ):
        """They were never the agent's to get wrong."""
        process_id = await self._seed(session_factory, shared_document=True)
        # A finding about a pair that was never undecided: blocked by scope.
        stage = self._stage(
            session_factory,
            json.dumps(
                {
                    "dependencies": [
                        {
                            "source_event_id": str(uuid.uuid4()),
                            "dependent_event_id": str(uuid.uuid4()),
                            "kind": "repeated_claim",
                            "rationale": "…",
                            "confidence": 0.8,
                            "schema_version": "1.0.0",
                        }
                    ],
                    "abstained": False,
                    "abstention_reason": None,
                    "uncertainty_notes": [],
                    "schema_version": "1.0.0",
                }
            ),
        )

        outcome = await stage.run(process_id)

        assert outcome.judged_count == 0
        assert outcome.computed_count == 1
        assert outcome.effective_sources == 2

    async def test_the_thesis_score_uses_the_effective_count(self, session_factory):
        """The improvement in evidence weighting §10.2 asks to be measured."""
        from econiq_agents import ThesisStage
        from econiq_agents.thesis_scorer import JUDGED_AXES
        from econiq_ontology import ThesisQualityDimension as Axis

        from .test_thesis import _axis, _counterfactuals, _scoring, _world

        process_id = await self._seed(session_factory, shared_document=True)

        def score() -> ThesisStage:
            return ThesisStage(
                LLMService(
                    ScriptedProvider(
                        [
                            _counterfactuals(_world("Permitting holds")),
                            _scoring(*[_axis(a) for a in JUDGED_AXES]),
                        ]
                    ),
                    observers=[],
                ),
                session_factory,
            )

        before = await score().run(process_id)
        independence_axis = next(m for m in before.computed if m.axis is Axis.EVIDENCE_INDEPENDENCE)
        assert independence_axis.inputs["independent_sources"] == 3.0

        await self._stage(session_factory, _output()).run(process_id)

        after = await score().run(process_id)
        after_axis = next(m for m in after.computed if m.axis is Axis.EVIDENCE_INDEPENDENCE)
        assert after_axis.inputs["independent_sources"] == 2.0
        assert after_axis.value < independence_axis.value
