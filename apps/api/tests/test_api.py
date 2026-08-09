"""The domain API, against a real database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from econiq_data_models import (
    AgentRun,
    AgentRunStatus,
    Asset,
    AssetExposure,
    Bottleneck,
    Capability,
    Claim,
    Critique,
    Document,
    Event,
    EventClaim,
    EvidenceLink,
    JournalEntry,
    JournalEntryKind,
    Node,
    Process,
    ProcessState,
    ProcessStateFeature,
    Relationship,
    Scorecard,
    ScoreDimension,
    ValueBasis,
)
from econiq_ontology import (
    AssetClass,
    BottleneckKind,
    ClaimType,
    CritiqueKind,
    CritiqueStatus,
    DocumentType,
    EntityType,
    EpistemicStatus,
    EventType,
    ExposureKind,
    ExtractionStatus,
    ProcessArchetype,
    ProcessStatus,
    RelationshipType,
    ScoreFamily,
    ThesisQualityDimension,
    states_for,
)
from econiq_ontology import (
    ProcessStateLabel as S,
)
from sqlalchemy import update

pytestmark = pytest.mark.integration

# Anchored to now, not to a literal date. `recorded_at >= observed_at` is a
# database constraint, so a fixture date that the calendar eventually overtakes
# turns into a check violation months after anyone touched this file.
PUB = datetime.now(UTC) - timedelta(days=90)


@pytest.fixture
async def graph(session_factory) -> dict[str, uuid.UUID]:
    """A full chain: Document → Claim → Event → Process → Bottleneck → Capability → Asset."""
    ids = {
        key: uuid.uuid4()
        for key in ("document", "claim", "event", "process", "bottleneck", "capability", "asset")
    }

    async with session_factory() as session:
        session.add(Node(created_at=PUB, node_id=ids["document"], node_type=EntityType.DOCUMENT))
        session.add(Node(created_at=PUB, node_id=ids["claim"], node_type=EntityType.CLAIM))
        session.add(Node(created_at=PUB, node_id=ids["event"], node_type=EntityType.EVENT))
        session.add(
            Node(
                created_at=PUB,
                node_id=ids["process"],
                node_type=EntityType.PROCESS,
                slug="minerals",
            )
        )
        session.add(
            Node(created_at=PUB, node_id=ids["bottleneck"], node_type=EntityType.BOTTLENECK)
        )
        session.add(
            Node(
                created_at=PUB,
                node_id=ids["capability"],
                node_type=EntityType.CAPABILITY,
                slug="sep",
            )
        )
        session.add(Node(created_at=PUB, node_id=ids["asset"], node_type=EntityType.ASSET))
        await session.flush()

        session.add(
            Document(
                document_id=ids["document"],
                source="reuters-rss",
                publisher="Reuters",
                title="Separation capacity remains constrained",
                document_type=DocumentType.NEWS_ARTICLE,
                publication_time=PUB,
                retrieved_at=PUB + timedelta(minutes=1),
                content_hash=uuid.uuid4().hex,
                extraction_status=ExtractionStatus.PARSED,
                created_at=PUB,
            )
        )
        session.add(
            Process(
                process_id=ids["process"],
                revision=1,
                name="Domestic strategic-mineral security",
                slug="minerals",
                description="The state is underwriting domestic rare-earth capacity.",
                archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                archetype_confidence=0.85,
                status=ProcessStatus.ACTIVE,
                requires_review=True,
                valid_from=PUB,
            )
        )
        session.add(
            Event(
                event_id=ids["event"],
                revision=1,
                event_type=EventType.GOVERNMENT_FUNDING,
                title="Pentagon takes stake in a rare-earth producer",
                description="A 15 percent equity position was announced.",
                occurred_at=PUB,
                entities=[],
                independent_source_count=2,
                novelty=8.0,
                materiality=8.5,
                confidence=0.9,
                epistemic_status=EpistemicStatus.OBSERVED,
                contradictions=["Timing of the tranche is disputed"],
                propagated_at=PUB,
                valid_from=PUB,
            )
        )
        session.add(
            Bottleneck(
                bottleneck_id=ids["bottleneck"],
                revision=1,
                process_id=ids["process"],
                name="Heavy rare-earth separation capacity",
                description="Separation capacity outside China is minimal.",
                kind=BottleneckKind.PROCESSING_CAPACITY,
                currently_binding=True,
                demand_pressure=9.1,
                relief_indicators=["Non-Chinese separation tonnage rises"],
                confidence=0.85,
                resolved=False,
                valid_from=PUB,
            )
        )
        session.add(
            Capability(
                capability_id=ids["capability"],
                revision=1,
                name="Heavy rare-earth separation",
                slug="sep",
                description="The ability to separate heavy rare-earth oxides at scale.",
                aliases=[],
                valid_from=PUB,
            )
        )
        session.add(
            Asset(
                asset_id=ids["asset"],
                revision=1,
                name="Neodymium-praseodymium oxide",
                asset_class=AssetClass.COMMODITY,
                commodity_code="NDPR",
                benchmark="Asian Metal NdPr Oxide",
                currency="USD",
                valid_from=PUB,
            )
        )
        await session.flush()

        session.add(
            Claim(
                claim_id=ids["claim"],
                document_id=ids["document"],
                text="Separation capacity outside China remains under 10 percent of supply.",
                claim_type=ClaimType.REPORTED_CLAIM,
                assertion_source="reported_statement",
                source_location={"quote": "under 10 percent", "char_start": 40, "char_end": 56},
                extraction_confidence=0.92,
                entities=[],
                created_at=PUB,
            )
        )
        session.add(EventClaim(event_id=ids["event"], claim_id=ids["claim"]))
        session.add(
            EvidenceLink(
                subject_id=ids["process"],
                evidence_id=ids["event"],
                supports=True,
                weight=0.9,
                created_at=PUB,
            )
        )

        state_id = uuid.uuid4()
        ids["state"] = state_id
        session.add(
            ProcessState(
                process_state_id=state_id,
                process_id=ids["process"],
                observed_at=PUB,
                archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                categorical_state=S.SUPPLY_TIGHTNESS,
                state_confidence=0.82,
                transition_beliefs={"price_acceleration": 0.6},
                transition_indicators=["Spot premia widening"],
                reversal_indicators=["New separation capacity commissioned"],
                recorded_at=PUB,
            )
        )
        await session.flush()
        session.add(
            ProcessStateFeature(
                process_state_id=state_id,
                name="supply_tightness",
                value=8.4,
                basis=ValueBasis.MEASURED,
                rationale="From reported tonnage.",
            )
        )
        session.add(
            JournalEntry(
                subject_id=ids["process"],
                subject_type=EntityType.PROCESS,
                kind=JournalEntryKind.BELIEF_CHANGE,
                observed_at=PUB,
                summary="+1 strengthened; supply_tightness +0.40",
                confidence_before=0.78,
                confidence_after=0.82,
                changes=[{"direction": "strengthened", "statement": "…", "rationale": "…"}],
                triggering_event_id=ids["event"],
                recorded_at=PUB,
            )
        )
        session.add(
            Critique(
                critique_id=uuid.uuid4(),
                subject_id=ids["process"],
                subject_type=EntityType.PROCESS,
                kind=CritiqueKind.UNSUPPORTED_ASSUMPTION,
                statement="The thesis assumes permitting timelines hold.",
                severity=7.0,
                rationale="No supplied evidence speaks to permitting.",
                testable_with="Published permit decisions.",
                is_most_damaging=True,
                status=CritiqueStatus.OPEN,
                observed_at=PUB,
                recorded_at=PUB,
                supporting_claim_ids=[],
            )
        )
        for source, target, kind in (
            (ids["event"], ids["process"], RelationshipType.AFFECTS),
            (ids["process"], ids["bottleneck"], RelationshipType.CREATES),
            (ids["bottleneck"], ids["capability"], RelationshipType.REQUIRES),
            (ids["capability"], ids["asset"], RelationshipType.EXPRESSED_BY),
        ):
            session.add(
                Relationship(
                    relationship_id=uuid.uuid4(),
                    revision=1,
                    source_id=source,
                    target_id=target,
                    relationship_type=kind,
                    weight=0.9,
                    confidence=0.9,
                    rationale=f"{kind.value} because the evidence says so",
                    valid_from=PUB,
                )
            )
        session.add(
            AssetExposure(
                asset_exposure_id=uuid.uuid4(),
                asset_id=ids["asset"],
                target_id=ids["capability"],
                target_type=EntityType.CAPABILITY,
                exposure_kind=ExposureKind.PRODUCTION_CAPABILITY,
                directness="direct",
                magnitude=9.0,
                rationale="The commodity is the constrained output itself.",
                confidence=0.85,
                observed_at=PUB,
                recorded_at=PUB,
            )
        )

        run_id = uuid.uuid4()
        ids["run"] = run_id
        session.add(
            AgentRun(
                agent_run_id=run_id,
                agent_name="process_critic",
                agent_version="1.0.0",
                ontology_layer="Process",
                input_schema_version="1.0.0",
                as_of=PUB,
                status=AgentRunStatus.SUCCEEDED,
                input_payload={},
                output_payload={},
                evaluation={"passed": True, "checks": [], "advisories": []},
                attempts=1,
                input_tokens=12000,
                output_tokens=2400,
                cost_usd=0.12,
                latency_ms=8400.0,
            )
        )
        scorecard_id = uuid.uuid4()
        session.add(
            Scorecard(
                scorecard_id=scorecard_id,
                subject_id=ids["process"],
                subject_type=EntityType.PROCESS,
                family=ScoreFamily.THESIS_QUALITY,
                observed_at=PUB,
                recorded_at=PUB,
                agent_run_id=run_id,
            )
        )
        await session.flush()
        session.add(
            ScoreDimension(
                scorecard_id=scorecard_id,
                dimension=ThesisQualityDimension.CONTRADICTION.value,
                value=6.5,
                confidence=0.8,
                method="llm_judgement",
                inputs={"critique_count": 1.0, "max_severity": 7.0},
            )
        )
        await session.commit()
    return ids


async def test_health_reports_the_schema_version(client):
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    # An API one migration behind fails like a data problem; naming it helps.
    assert body["schema_version"]


async def test_a_process_carries_its_state_bottlenecks_and_critiques(client, graph):
    response = await client.get(f"/api/processes/{graph['process']}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Domestic strategic-mineral security"
    assert body["requires_review"] is True
    assert body["current_state"] == "supply_tightness"
    assert body["state"]["features"][0]["basis"] == "measured"
    assert body["open_bottlenecks"][0]["currently_binding"] is True
    assert body["open_critiques"][0]["is_most_damaging"] is True
    assert body["evidence_event_count"] == 1


async def test_state_features_report_whether_code_or_a_model_produced_them(client, graph):
    response = await client.get(f"/api/processes/{graph['process']}/states")

    features = response.json()[0]["features"]
    assert features[0]["name"] == "supply_tightness"
    assert features[0]["basis"] == "measured"


async def test_transition_beliefs_are_not_called_probabilities(client, graph):
    """Uncalibrated belief must not be dressed as probability (ontology §35)."""
    spec = (await client.get("/openapi.json")).json()
    state_schema = spec["components"]["schemas"]["ProcessStateOut"]

    assert "transition_beliefs" in state_schema["properties"]
    assert "transition_probabilities" not in state_schema["properties"]
    assert "Not probabilities" in state_schema["properties"]["transition_beliefs"]["description"]


async def test_the_journal_explains_why_belief_changed(client, graph):
    response = await client.get(f"/api/processes/{graph['process']}/journal")

    entry = response.json()[0]
    assert entry["confidence_before"] == pytest.approx(0.78)
    assert entry["confidence_after"] == pytest.approx(0.82)
    assert entry["triggering_event_id"] == str(graph["event"])


async def test_an_event_reports_independent_sources_not_document_count(client, graph):
    response = await client.get(f"/api/events/{graph['event']}")

    body = response.json()
    assert body["independent_source_count"] == 2
    assert body["propagated_at"] is not None
    assert body["contradictions"] == ["Timing of the tranche is disputed"]
    # The claim carries the verified span, so the quote can be checked.
    assert body["claims"][0]["source_location"]["quote"] == "under 10 percent"
    assert body["documents"][0]["publisher"] == "Reuters"


async def test_evidence_trails_reach_the_documents(client, graph):
    response = await client.get(f"/api/evidence/{graph['process']}")

    body = response.json()
    assert body["subject"]["type"] == "process"
    assert body["document_ids"] == [str(graph["document"])]
    assert body["is_evidenced"] is True


async def test_an_asset_leads_with_why_it_is_here(client, graph):
    response = await client.get(f"/api/assets/{graph['asset']}")

    body = response.json()
    # Not equity-shaped: a commodity carries a code and a benchmark.
    assert body["asset_class"] == "commodity"
    assert body["identifiers"]["commodity_code"] == "NDPR"
    assert body["identifiers"]["ticker"] is None

    chain = body["discovery_chain"][0]
    assert chain["start"]["id"] == str(graph["asset"])
    assert [step["relationship_type"] for step in chain["steps"]] == [
        "expressed_by",
        "requires",
        "creates",
    ]
    assert all(step["rationale"] for step in chain["steps"])
    assert body["exposures"][0]["magnitude"] == pytest.approx(9.0)


async def test_the_requirement_tree_is_returned_as_a_tree(client, graph, session_factory):
    """AND and OR imply different participants; flattening would lose that."""
    from econiq_data_models import CapabilityRequirement, RequirementNode, RequirementNodeKind
    from econiq_ontology import LogicOperator, Necessity

    requirement_id, root_id, leaf_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        session.add(
            CapabilityRequirement(
                requirement_id=requirement_id,
                revision=1,
                bottleneck_id=graph["bottleneck"],
                process_id=graph["process"],
                root_node_id=root_id,
            )
        )
        await session.flush()
        session.add(
            RequirementNode(
                requirement_node_id=root_id,
                requirement_id=requirement_id,
                requirement_revision=1,
                position=0,
                kind=RequirementNodeKind.GROUP,
                operator=LogicOperator.AND,
                necessity=Necessity.REQUIRED,
                weight=1.0,
            )
        )
        session.add(
            RequirementNode(
                requirement_node_id=leaf_id,
                requirement_id=requirement_id,
                requirement_revision=1,
                parent_id=root_id,
                position=0,
                kind=RequirementNodeKind.CAPABILITY,
                capability_id=graph["capability"],
                necessity=Necessity.REQUIRED,
                weight=1.0,
            )
        )
        await session.commit()

    response = await client.get(f"/api/bottlenecks/{graph['bottleneck']}/requirements")

    body = response.json()
    assert body["root"]["kind"] == "group"
    assert body["root"]["operator"] == "and"
    assert body["root"]["children"][0]["capability"]["label"] == "Heavy rare-earth separation"
    assert body["capability_count"] == 1


async def test_capability_confluence_is_read_off_the_graph(client, graph):
    response = await client.get(f"/api/capabilities/{graph['capability']}")

    body = response.json()
    assert [p["id"] for p in body["upstream_processes"]] == [str(graph["process"])]
    assert [a["id"] for a in body["expressed_by"]] == [str(graph["asset"])]


async def test_asset_reach_answers_the_multi_hop_question(client, graph):
    response = await client.get("/api/graph/reach", params={"process_id": str(graph["process"])})

    reach = response.json()[0]
    assert reach["asset"]["id"] == str(graph["asset"])
    assert reach["shortest_hops"] == 3
    assert reach["distinct_source_count"] == 1


async def test_integrity_is_exposed(client, graph):
    response = await client.get("/api/graph/integrity")

    body = response.json()
    assert "violations" in body
    assert body["checked_at"]


async def test_scores_carry_their_inputs(client, graph):
    """A score the UI cannot decompose is an assertion, not a measurement."""
    response = await client.get(f"/api/scores/{graph['process']}")

    card = response.json()[0]
    assert card["family"] == "thesis_quality"
    # One contributed dimension is not a summary of the family.
    assert card["composite"] is None
    dimension = card["dimensions"][0]
    assert dimension["dimension"] == "contradiction"
    assert dimension["inputs"]["max_severity"] == pytest.approx(7.0)


async def test_there_is_no_endpoint_that_blends_score_families(client):
    """Thesis, Asset and Trade quality are separate by construction."""
    spec = (await client.get("/openapi.json")).json()

    combined = [
        path
        for path in spec["paths"]
        if any(word in path for word in ("overall", "combined", "rank", "composite-score"))
    ]
    assert combined == []


async def test_the_api_offers_no_way_to_write_ontology_objects(client):
    """A row created here would have no agent run, prompt version or evaluation.

    Asserted as "no write touches an ontology path" rather than "no writes at
    all". Watchlists are writable (#19) and are not ontology: a watchlist entry
    is a person saying they care, nothing downstream reasons from it, and PRD
    §23 draws exactly this line. The invariant being protected is that the
    *graph* stays agent-written.
    """
    spec = (await client.get("/openapi.json")).json()

    writes = {
        (method.upper(), path)
        for path, methods in spec["paths"].items()
        for method in methods
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert all(path.startswith("/api/workspace/") for _, path in writes), writes
    # And nothing writable mentions an ontology object.
    forbidden = ("process", "event", "claim", "bottleneck", "capability", "asset", "score")
    assert not [path for _, path in writes if any(word in path for word in forbidden)]


async def test_workspace_endpoints_refuse_without_an_identity_provider(client):
    """Running open is a state a deployment must announce, not imitate."""
    response = await client.get("/api/workspace")

    assert response.status_code == 501
    assert "CLERK_ISSUER" in response.json()["detail"]


async def test_a_forged_token_is_rejected_rather_than_treated_as_anonymous(client, monkeypatch):
    """Presenting a bad credential is not the same as presenting none; letting
    it through would hide an attack as a preference."""
    from econiq_api import auth

    monkeypatch.setattr(auth._verifier, "_issuer", "https://example.clerk.dev")

    response = await client.get("/api/processes", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


async def test_the_graph_is_readable_without_signing_in(client, graph):
    """PRD §23: the canonical Process graph is system-wide. Gating it would turn
    a shared research asset into a per-tenant silo."""
    for path in ("/api/processes", "/api/discover", f"/api/processes/{graph['process']}"):
        assert (await client.get(path)).status_code == 200


async def test_agent_runs_expose_cost_and_evaluation(client, graph):
    response = await client.get("/api/runs")

    run = response.json()[0]
    assert run["agent_name"] == "process_critic"
    assert run["cost_usd"] == pytest.approx(0.12)
    assert run["evaluation"]["passed"] is True


async def test_rejected_runs_can_be_listed(client, graph, session_factory):
    async with session_factory() as session:
        await session.execute(
            update(AgentRun)
            .where(AgentRun.agent_run_id == graph["run"])
            .values(status=AgentRunStatus.REJECTED)
        )
        await session.commit()

    response = await client.get("/api/runs", params={"failed_evaluation": "true"})

    assert [r["id"] for r in response.json()] == [str(graph["run"])]


async def test_the_pipeline_reports_what_is_unwired(client):
    """A stage with no handler never runs; a stage with no reconciler has no backstop."""
    response = await client.get("/api/pipeline")

    stages = {stage["name"]: stage for stage in response.json()}
    assert "resolve_events" in stages
    assert stages["critique_process"]["priority"] > stages["extract_claims"]["priority"]
    # This API process wires no handlers, and says so rather than implying idle.
    assert all(stage["has_handler"] is False for stage in stages.values())


async def test_an_as_of_read_excludes_later_knowledge(client, graph, session_factory):
    """Reconstructing a past belief must not see what was recorded afterwards."""
    async with session_factory() as session:
        session.add(
            ProcessState(
                process_id=graph["process"],
                observed_at=PUB + timedelta(days=30),
                archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                categorical_state=S.PRICE_ACCELERATION,
                state_confidence=0.9,
                transition_beliefs={},
                transition_indicators=[],
                reversal_indicators=[],
            )
        )
        await session.commit()

    current = await client.get(f"/api/processes/{graph['process']}")
    assert current.json()["current_state"] == "price_acceleration"

    # Both States were recorded now, whatever they claim to have observed. A
    # cut-off before now therefore excludes the second one — the filter is on
    # recorded_at, and reading it off observed_at would leak the later belief
    # into a replay of the earlier one.
    earlier = await client.get(
        f"/api/processes/{graph['process']}",
        params={"as_of": (PUB + timedelta(days=1)).isoformat()},
    )
    assert earlier.json()["current_state"] == "supply_tightness"


async def test_a_superseded_revision_is_hidden_but_recoverable(client, graph, session_factory):
    """A revision that takes effect later is not the current one until it does."""
    takes_effect = datetime.now(UTC) + timedelta(hours=1)
    async with session_factory() as session:
        await session.execute(
            update(Process)
            .where(Process.process_id == graph["process"], Process.valid_to.is_(None))
            .values(valid_to=takes_effect)
        )
        session.add(
            Process(
                process_id=graph["process"],
                revision=2,
                name="Domestic strategic-mineral security (revised)",
                slug="minerals",
                description="…",
                archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                status=ProcessStatus.ACTIVE,
                valid_from=takes_effect,
            )
        )
        await session.commit()

    current = await client.get(f"/api/processes/{graph['process']}")
    assert current.json()["revision"] == 1  # revision 2 is not yet valid

    later = await client.get(
        f"/api/processes/{graph['process']}",
        params={"as_of": (takes_effect + timedelta(seconds=1)).isoformat()},
    )
    assert later.json()["revision"] == 2


async def test_unknown_ids_are_404_not_500(client):
    missing = uuid.uuid4()
    for path in (
        f"/api/processes/{missing}",
        f"/api/events/{missing}",
        f"/api/assets/{missing}",
        f"/api/capabilities/{missing}",
        f"/api/bottlenecks/{missing}",
        f"/api/evidence/{missing}",
    ):
        response = await client.get(path)
        assert response.status_code == 404, path


async def test_filters_narrow_the_lists(client, graph):
    assert len((await client.get("/api/processes")).json()) == 1
    assert len((await client.get("/api/processes", params={"status": "dormant"})).json()) == 0
    assert len((await client.get("/api/bottlenecks", params={"binding_only": "true"})).json()) == 1
    assert len((await client.get("/api/assets", params={"asset_class": "commodity"})).json()) == 1
    assert (
        len((await client.get("/api/assets", params={"asset_class": "common_stock"})).json()) == 0
    )


async def test_the_terminal_can_reach_the_api_from_a_browser(client):
    """CORS, which only fails in a browser and so fails no other test.

    The terminal (#18) runs on its own origin in development. Without the
    preflight answer every request from it is blocked, and the failure surfaces
    in a devtools console rather than in CI.
    """
    response = await client.options(
        "/api/processes",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_an_unknown_origin_is_not_allowed(client):
    """An allowlist that was permissive before authentication (#19) existed is
    one nobody tightens afterwards."""
    response = await client.options(
        "/api/processes",
        headers={
            "Origin": "https://not-the-terminal.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


async def test_the_timeline_puts_evidence_next_to_the_belief_it_changed(client, graph):
    """Issue #20. Three separate lists would leave the reader doing this join by eye."""
    response = await client.get(f"/api/processes/{graph['process']}/timeline")

    assert response.status_code == 200
    entries = response.json()["entries"]
    kinds = {entry["kind"] for entry in entries}
    assert kinds == {"state", "journal", "evidence", "critique"}

    # Newest first, on the axis of when things happened in the world.
    occurred = [entry["occurred_at"] for entry in entries]
    assert occurred == sorted(occurred, reverse=True)

    # Both clocks travel with every entry: a document published in July and
    # ingested in August belongs in two different places depending on the
    # question being asked.
    assert all(entry["recorded_at"] for entry in entries)


async def test_a_timeline_entry_says_which_direction_the_evidence_pointed(client, graph):
    entries = (await client.get(f"/api/processes/{graph['process']}/timeline")).json()["entries"]

    evidence = next(entry for entry in entries if entry["kind"] == "evidence")
    assert evidence["supports"] is True
    # A critique is evidence against the thesis surviving unchanged.
    critique = next(entry for entry in entries if entry["kind"] == "critique")
    assert critique["supports"] is False


async def test_the_timeline_excludes_what_was_recorded_after_the_cut_off(client, graph):
    """A replay must not show a belief change the system had not made yet."""
    entries = (
        await client.get(
            f"/api/processes/{graph['process']}/timeline",
            params={"as_of": (PUB - timedelta(days=1)).isoformat()},
        )
    ).json()["entries"]

    assert entries == []


async def test_the_state_machines_are_served_from_the_ontology(client):
    """Issues #22, #23. The terminal draws the machine; it must not own a copy."""
    response = await client.get("/api/archetypes")

    assert response.status_code == 200
    machines = {row["archetype"]: row for row in response.json()}
    assert set(machines) == {a.value for a in ProcessArchetype}

    s_curve = machines["infrastructure_s_curve"]
    labels = [node["state"] for node in s_curve["states"]]
    # The sequence is developmental order, which is what makes "one step early"
    # a near miss rather than a wrong answer.
    assert labels == [state.value for state in states_for(ProcessArchetype.INFRASTRUCTURE_S_CURVE)]
    assert [node["ordinal"] for node in s_curve["states"]] == list(range(len(labels)))


async def test_maturity_runs_from_the_first_state_to_the_last(client):
    """The Emergence Radar's X axis (§5.2) is a position on the machine."""
    machine = (await client.get("/api/archetypes/commodity_supply_cycle")).json()

    maturities = [node["maturity"] for node in machine["states"]]
    assert maturities[0] == 0.0
    assert maturities[-1] == 1.0
    assert maturities == sorted(maturities)


async def test_a_terminal_state_is_marked_as_one(client):
    machine = (await client.get("/api/archetypes/infrastructure_s_curve")).json()

    terminal = [node["state"] for node in machine["states"] if node["is_terminal"]]
    assert terminal, "a non-cyclical machine must end somewhere"
    assert all(not node["transitions_to"] for node in machine["states"] if node["is_terminal"])


async def test_an_unknown_archetype_is_rejected_rather_than_invented(client):
    response = await client.get("/api/archetypes/not_an_archetype")

    assert response.status_code == 422


async def test_a_claim_names_the_run_that_extracted_it(client, graph, session_factory):
    """Issues #24, #25. ui_concept §23 requires model version on every explanation."""
    async with session_factory() as session:
        await session.execute(
            update(Claim).where(Claim.claim_id == graph["claim"]).values(agent_run_id=graph["run"])
        )
        await session.commit()

    body = (await client.get(f"/api/evidence/{graph['process']}/inspect")).json()

    claim = next(c for c in body["claims"] if c["id"] == str(graph["claim"]))
    assert claim["provenance"]["agent_name"] == "process_critic"
    assert claim["provenance"]["agent_run_id"] == str(graph["run"])


async def test_the_inspector_returns_the_claims_not_a_summary_of_them(client, graph):
    """§29: evidence must never be shown as an undifferentiated AI summary."""
    body = (await client.get(f"/api/evidence/{graph['process']}/inspect")).json()

    assert body["is_evidenced"] is True
    claim = body["claims"][0]
    # The verified span, so a reader can reach the sentence in the document.
    assert claim["source_location"]["char_start"] is not None
    assert claim["text"]
    assert body["documents"][0]["title"]


async def test_the_inspector_counts_independent_sources_not_documents(client, graph):
    """Four syndicated copies of one wire report are one source (§47)."""
    body = (await client.get(f"/api/evidence/{graph['process']}/inspect")).json()

    assert body["independent_source_count"] == 2


async def test_a_scorecard_carries_the_model_that_produced_it(client, graph):
    body = (await client.get(f"/api/scores/{graph['process']}")).json()

    card = body[0]
    assert card["provenance"]["agent_run_id"] == str(graph["run"])
    assert card["provenance"]["as_of"]
    assert card["provenance"]["recorded_at"]


async def test_provenance_is_null_rather_than_absent_when_nothing_produced_a_row(
    client, graph, session_factory
):
    """A row nobody can attribute is either a seed or a defect, and both are
    things the reader should see rather than a blank space."""
    body = (await client.get(f"/api/evidence/{graph['process']}/inspect")).json()

    claim = body["claims"][0]
    assert "provenance" in claim
    assert claim["provenance"] is None


async def test_a_state_assignment_is_explainable_like_a_score_is(client, graph):
    """§23 lists State assignments alongside scores as explainable objects."""
    body = (await client.get(f"/api/processes/{graph['process']}")).json()

    assert "provenance" in body["state"]


async def test_confluence_requires_every_selected_process_by_default(client, graph):
    """ui_concept §11's AND: a Capability several independent theses all need
    is more interesting than one a single thesis needs badly."""
    response = await client.get("/api/confluence", params={"process_id": str(graph["process"])})

    assert response.status_code == 200
    body = response.json()
    assert body["require_all"] is True
    hit = body["capabilities"][0]
    assert hit["capability"]["label"] == "Heavy rare-earth separation"
    assert hit["reached_by"] == 1
    # Where the confluence becomes investable.
    assert hit["asset_count"] == 1


async def test_confluence_drops_a_capability_only_one_process_reaches(
    client, session_factory, graph
):
    """With two Processes selected and AND semantics, a Capability reached by
    one of them is not a confluence."""
    other = uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=other, node_type=EntityType.PROCESS, slug="other"))
        await session.flush()
        session.add(
            Process(
                process_id=other,
                revision=1,
                name="Unrelated",
                slug="other",
                description="…",
                archetype=ProcessArchetype.COMMODITY_SUPPLY_CYCLE,
                status=ProcessStatus.ACTIVE,
                valid_from=PUB,
            )
        )
        await session.commit()

    body = (
        await client.get(
            "/api/confluence",
            params={"process_id": [str(graph["process"]), str(other)]},
        )
    ).json()

    assert body["capabilities"] == []

    union = (
        await client.get(
            "/api/confluence",
            params={
                "process_id": [str(graph["process"]), str(other)],
                "require_all": "false",
            },
        )
    ).json()
    assert len(union["capabilities"]) == 1


async def test_the_journal_feed_reaches_the_model_that_changed_its_mind(client, graph):
    """#31: a belief change nobody can attribute is one nobody can review."""
    body = (await client.get("/api/journal")).json()

    assert body
    entry = body[0]
    assert entry["subject_id"] == str(graph["process"])
    assert entry["subject_type"] == "process"
    assert "provenance" in entry
    assert entry["recorded_at"]


async def test_alerts_describe_the_thesis_not_the_price(client, graph):
    """PRD §20. The fixture's critique is a new open finding, which is a change
    to the argument."""
    body = (await client.get("/api/alerts", params={"window_days": 365})).json()

    assert body
    kinds = {alert["kind"] for alert in body}
    assert "critique_opened" in kinds
    assert all("%" not in alert["headline"] for alert in body)


async def test_the_most_damaging_critique_raises_the_severity(client, graph):
    body = (await client.get("/api/alerts", params={"window_days": 365})).json()

    critique = next(a for a in body if a["kind"] == "critique_opened")
    assert critique["severity"] == "urgent"
    assert critique["subject"]["label"] == "Domestic strategic-mineral security"


async def test_an_alert_id_is_stable_across_reads(client, graph):
    """Derived at read time, so the same change must not alert twice."""
    first = (await client.get("/api/alerts", params={"window_days": 365})).json()
    second = (await client.get("/api/alerts", params={"window_days": 365})).json()

    assert [a["id"] for a in first] == [a["id"] for a in second]


async def test_a_past_cut_off_returns_the_alerts_that_existed_then(client, graph):
    """The point of deriving rather than storing them."""
    body = (
        await client.get(
            "/api/alerts",
            params={"as_of": (PUB - timedelta(days=1)).isoformat(), "window_days": 365},
        )
    ).json()

    assert body == []


async def test_alerts_can_be_narrowed_to_what_is_urgent(client, graph):
    body = (
        await client.get("/api/alerts", params={"window_days": 365, "severity": "urgent"})
    ).json()

    assert body
    assert all(alert["severity"] == "urgent" for alert in body)


async def test_the_comparison_matrix_labels_its_holes(client, graph):
    """#29. A gap with a reason beats a plausible number: once both render as
    numbers nobody can tell a measured multiple from a guessed one."""
    response = await client.get(
        "/api/comparison", params={"capability_id": str(graph["capability"])}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["capability"]["label"] == "Heavy rare-earth separation"
    assert body["columns"], "the fixture's Asset expresses this Capability"

    cells = {cell["dimension"]: cell for cell in body["columns"][0]["cells"]}
    valuation = cells["valuation"]
    assert valuation["value"] is None
    assert "fundamentals" in valuation["unavailable_reason"]

    reasons = {item["name"] for item in body["unavailable"]}
    assert "valuation" in reasons


async def test_the_comparison_offers_no_overall_score(client, graph):
    """§13 asks that users change ranking weights without changing the scores,
    which puts the weighting on the reader's side of the line."""
    body = (
        await client.get("/api/comparison", params={"capability_id": str(graph["capability"])})
    ).json()

    assert "overall" not in body
    assert all("overall" not in cell["dimension"] for cell in body["columns"][0]["cells"])


async def test_comparing_a_capability_nothing_expresses_is_not_an_error(
    client, session_factory, graph
):
    lonely = uuid.uuid4()
    async with session_factory() as session:
        session.add(Node(node_id=lonely, node_type=EntityType.CAPABILITY, slug="lonely"))
        await session.flush()
        session.add(
            Capability(
                capability_id=lonely,
                revision=1,
                name="Unexpressed",
                slug="lonely",
                description="…",
                aliases=[],
                valid_from=PUB,
            )
        )
        await session.commit()

    body = (await client.get("/api/comparison", params={"capability_id": str(lonely)})).json()

    assert body["columns"] == []
    # The dimensions are still named, so the screen renders a shape rather than
    # nothing.
    assert body["dimensions"]


async def test_the_why_not_panel_is_empty_before_the_agent_has_run(client, graph):
    """#30, §14.3. An empty panel is honest; a fabricated one is not."""
    body = (await client.get(f"/api/processes/{graph['process']}/counterfactuals")).json()

    assert body == []


async def test_the_stream_pushes_invalidations_not_data(client, session_factory):
    """#34. Pushing rows would give two paths to every value — the push and the
    fetch — and they diverge the first time one is read at a different as_of."""
    from econiq_data_models import OutboxEvent, OutboxStatus

    async with session_factory() as session:
        session.add(
            OutboxEvent(
                outbox_event_id=uuid.uuid4(),
                event_name="process.updated",
                subject_id=uuid.uuid4(),
                subject_type=EntityType.PROCESS,
                payload={},
                occurred_at=datetime.now(UTC),
                status=OutboxStatus.PENDING,
            )
        )
        await session.commit()

    from econiq_api.routers.stream import INVALIDATES

    # The contract is a list of caches to drop, never the changed row.
    assert INVALIDATES["process.updated"] == ("discover", "process", "journal", "alerts")
    assert "payload" not in str(INVALIDATES)


async def test_only_meaningful_domain_events_wake_a_screen(client):
    """A stream that fires on every internal step trains people to ignore it."""
    from econiq_api.routers.stream import INVALIDATES

    assert "event.created" not in INVALIDATES  # ungated, pre-propagation
    assert "event.propagated" in INVALIDATES


async def test_the_assistant_says_it_is_not_wired_up_rather_than_faking_it(client, monkeypatch):
    """#33. A command bar that silently answers from a fixture is worse than one
    that says it has no provider."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    body = (await client.get("/api/assistant/ask", params={"question": "what changed?"})).json()

    assert body["results"] == []
    assert "ANTHROPIC_API_KEY" in body["unsupported_reason"]


async def test_the_assistant_response_has_no_prose_field(client):
    """§2.5 and PRD §18: the model emits a plan, code runs it, and the answer is
    the rows. There is nowhere for invented narration to live."""
    spec = (await client.get("/openapi.json")).json()
    schema = spec["components"]["schemas"]["AssistantAnswer"]["properties"]

    assert "answer" not in schema
    assert "narrative" not in schema
    assert set(schema) >= {"resource", "results", "unsupported_reason"}
