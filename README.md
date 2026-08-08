# econiq

An evidence-backed, **Process-first** investment research platform.

```
Documents → Claims → Events → Economic Processes → Process States
→ Bottlenecks → Capabilities → Assets
```

Processes, not stocks, are the unit of research. An Asset is an investable
projection of an upstream Process/Capability configuration, and the chain from
document to asset stays explicit so every conclusion can be traced back to the
evidence that produced it.

The specifications in [`docs/`](docs/) are the source of truth;
[`ENGINEERING_HANDOFF.md`](ENGINEERING_HANDOFF.md) is the phase plan and issue
map.

## Status

Phase 0 complete — issues **#1–#17**. The gate (#17) passes **9 of 9 in-scope
PRD §28 criteria**, with §28.7 reassigned to Phase 1 (#29) and §28.11 to Phase 2.
See [docs/phase-0-validation.md](docs/phase-0-validation.md).

| Issue | Delivered |
|---|---|
| #1 Monorepo, CI, local dev | `uv` workspace, GitHub Actions, Docker Compose (Postgres+pgvector, MinIO, Redis) |
| #2 Postgres system of record | 25 tables, temporal versioning, pgvector, Alembic |
| #3 Pydantic ontology & schemas | `packages/ontology`, `packages/schemas` — the contract everything else depends on |
| #4 LLM abstraction | `packages/llm` — providers, agent runtime, prompt versioning, cost tracking |
| #5 Document ingestion | `services/ingestion` — S3/MinIO storage, parsing to sections, idempotent ingest, `DocumentIngested` |
| #6 Classifier & Claim extraction | `services/agents` — the first two agents, with quote grounding verified in code |
| #7 Event resolution | clustering with pgvector candidate retrieval, computed source independence, and a deterministic propagation gate |
| #8 Process discovery & update | persistent Processes accumulating evidence as revisions, with a journal and typed-edge enforcement |
| #9 Archetype & State | classification, then State estimation constrained by the archetype's machine, with append-only State history |
| #10 Process Critic | adversarial falsification with no route to rescue the thesis, stored as durable findings |
| #11 Bottleneck & Capability | binding constraints, AND/OR/optional requirement trees that round-trip through Postgres, shared Capability nodes |
| #12 Asset discovery & exposure | equities, commodities, currencies and indices; deterministic resolution; append-only exposure observations |
| #13 Graph traversal & integrity | cycle-safe point-in-time traversal in Postgres, plus the structural checks Postgres cannot express |
| #14 Staged orchestration | transactional outbox, Postgres work queue, and a reconciler that makes a dropped event a latency problem |
| #15 Domain API | `apps/api` — 25 read endpoints, every one accepting `as_of`; no route can write an ontology row |
| #16 Eval harness | `services/eval` — benchmarks, point-in-time and provenance audits, and fault injection that proves the audits fire |
| #17 End-to-end validation | a corpus run from document to instrument, graded against PRD §28 |

The full chain — document to instrument — runs as a staged, triggered pipeline,
is readable over HTTP at any point in its history, and is measured by a harness
that injects known faults to check its own integrity checks still fire.

The gate surfaced one scope gap rather than smoothing it over: nothing in Phase 0
writes an `asset_quality` scorecard, because the Asset Quant and Asset Quality
agents (agent doc §8.3–8.4) were in no phase's issue list. PRD §28.7 has been
reassigned to Phase 1 alongside the Asset comparison matrix (#29). The check
still runs and still reports what it finds — a deferral suspends the verdict,
not the measurement.

## Phase 1 — research terminal

| Issue | Delivered |
|---|---|
| #18 App shell | `apps/web` — Next.js 16 + Tailwind 4, sidebar per ui_concept §3, ⌘K command bar, a global `as_of` control, and an API client generated from the FastAPI OpenAPI document |
| #20 BFF endpoints | `/api/discover` — Processes ranked by evidence movement, every rank decomposable; `/api/processes/{id}/timeline` — state, belief, evidence and critique on one axis |
| #21 Discover screen | the emerging-Process panel, hot cards and the screener, with [Explain] on every rank |
| #22 Emergence Radar | maturity against evidence acceleration, positioned from the archetype's State machine |
| #23 Process screen | four synchronised perspectives over one `as_of`: overview, State evolution, evidence timeline, dependency graph |
| #24 Provenance inspector | `/api/evidence/{id}/inspect` — Claims with verified spans, their documents, and the run that extracted each |
| #25 [Explain] | one explanation shape for every derived number, carrying model, prompt version and timestamp |
| #26 Graph explorer | React Flow over the typed edges, expanded a hop at a time, laid out by ontology layer |
| #65 Thesis Scoring agent | ten Thesis Quality axes — five measured from rows, four judged, one deferred to Phase 2 |
| #66 Counterfactual agent | alternative worlds the thesis has to survive, with "no straw men" enforced rather than requested |
| #67 Evidence Independence | cross-Event dependence graph; code finds what is structural, the agent judges the rest |
| #27 Bottleneck & Capability | constraint profiles, the AND/OR requirement tree, and confluence search with AND semantics |
| #31 Thesis journal | every belief change, immutable, each reaching the run that made it |
| #32 Semantic alerts | thesis changes rather than price moves, derived at read time |
| #77 Market data | `services/market` — Tiingo daily and FX, storing raw *and* adjusted closes with both clocks |

```bash
cd apps/web && npm install && npm run dev   # needs the API on :8000
```

The `as_of` cut-off lives in the URL and in every query key, so a reconstructed
view is linkable and can never share a cache entry with the present. When one is
set the whole header changes colour — mistaking a reconstruction for the current
state is worse than not having the feature.

The Discover ranking returns its own limits. Of the eight inputs ui_concept §5.1
asks for, six are computed, market attention is proxied by publisher count (and
named `source_breadth`, because it is media coverage), and historical analogue
strength needs Phase 2. The API says which are missing and the screen renders it.

Archetype State machines are served from `/api/archetypes` rather than copied
into the client. The sequence defines which States are adjacent, and an inlined
copy would drift the first time an archetype gained one — as the S-curve did
during Phase 0.

Every derived number carries a uniform provenance envelope — agent, model,
prompt version and content hash, cut-off, and whether the deterministic checks
accepted the output. That is what makes [Explain] a primitive rather than a
component written once per screen.

The Thesis Quality scorecard now fills nine of its ten axes. Five are computed
from rows rather than judged — a model re-scoring a number the system already
measured is not a second opinion, it is an opportunity to disagree with nothing
to settle it. Historical precedent stays empty until Phase 2.

`evidence_independence` counts *effective* sources: the dependence graph is
collapsed into connected components, so four Events all citing one filing count
once rather than four.

Alerts are derived when read rather than stored, so a past `as_of` returns the
alerts that existed then, and one whose underlying change was later superseded
stops existing rather than lingering. Watchlist filtering plugs into the same
endpoint once users exist (#19).

Still open: watchlists need users (#19); Asset comparison needs the Quant and
Quality agents (#75, #76), which in turn need market data (#77).

## Quick start

```bash
make install          # sync the workspace virtualenv (installs uv-managed Python)
make up               # Postgres + MinIO + Redis
make migrate          # apply the ontology schema
make check            # lint, type-check, unit tests
make test-integration # migration round-trip against the running database
```

If a local Postgres already owns port 5432:

```bash
export ECONIQ_POSTGRES_PORT=55432
make up migrate
```

## Layout

```
apps/          web (Phase 1), api (#15)
services/
  ingestion/   document acquisition, storage, parsing (#5)
  agents/      agent implementations over packages/llm (#6 onward)
  graph/       traversal and integrity over the ontology (#13)
  orchestration/ staged triggers, work queue, reconciler (#14)
  quant, historical, alerts — later phases
packages/
  ontology/    Pydantic ontology — Document…Asset, archetype State machines
  schemas/     typed agent I/O contracts, one per agent
  data-models/ SQLAlchemy models + Alembic migrations (the system of record)
  llm/         provider abstraction, Agent base class, prompt versioning
  scoring/     reusable score computation (#65)
research/      notebooks and experiments
infrastructure/ Terraform (#70)
docs/          the specifications
```

## The constraints this code protects

These recur throughout the specs and should be defended in review:

1. **The LLM is never the source of truth** (tech rec §33). Postgres holds the
   canonical ontology. Every agent output is validated against a Pydantic model
   before it can become a row; `packages/llm` has no path that writes an
   unvalidated object.
2. **Point-in-time integrity is programmatic, not conventional** (ontology §33).
   Every agent input carries an `as_of` cut-off; every observation records both
   `observed_at` and `recorded_at`.
3. **Every material statement has provenance** (agent doc §2.4, §21). Every
   agent-written row references the `agent_run` that produced it, which
   references the prompt version, its content hash, and the model.
4. **Agents are narrow, typed and bounded** (agent doc §2.1, §14). Each stops at
   its ontology layer — the Bottleneck agent never names a ticker — and typed
   edges make skipping a layer a validation error.
5. **Nothing is destroyed** (PRD §21, §30). Revisable entities are append-only
   revisions with a single-current-revision index; observations are append-only
   by nature.
6. **Uncertainty language is earned** (ontology §35). Confidence values are model
   belief, not probability, until the calibration framework (#55) validates them
   — which is why State transitions are stored as `transition_beliefs`.
7. **Thesis quality ≠ Asset quality ≠ Trade quality** (ontology §17). Enforced
   structurally: a scorecard carries one family and may only use that family's
   dimensions.

## Decisions worth a second opinion

Recorded here rather than buried in commit messages, because #2 and #3 are the
contract everything downstream depends on:

- **Two archetype State machines are proposals, not spec.** Ontology §8.3 and
  §8.5 give examples but no State sequence for Industrial Bottleneck and
  Business Model Disruption. The sequences in `econiq_ontology.archetypes` are
  derived from the descriptions and flagged in `UNSPECIFIED_IN_SOURCE`.
- **`transition_probabilities` is named `transition_beliefs`.** Ontology §10 uses
  the former; §35 and agent doc §2.5 forbid probability language until
  calibration. The rename is reversible when #55 lands.
- **Node-type integrity is enforced in the application, not the database.**
  Edges are foreign keys into a `nodes` registry, so they cannot dangle — but
  "this column may only reference a Process" would need the type denormalised
  into every child table.
- **Recursive schemas bypass provider-side structured output.** The Capability
  requirement tree is recursive, which providers reject; those calls fall back
  to an inline schema in the prompt plus local validation and repair.
- **`asset_states` uses JSONB for its five dimension groups.** The contract is
  pinned in `econiq_ontology.asset_layer`; committing to columns before a Phase 3
  data vendor is chosen would be guessing.
- **A Claim whose quote is not in the document is dropped, not stored.**
  `ClaimWriter` resolves every quoted span against the parsed text and rejects
  what it cannot find; the rejection rate is the extraction hallucination
  metric issue #6 asks for. The alternative — storing the model's own guessed
  offsets — makes the provenance inspector confidently wrong.
- **The model never sets its own propagation bar.** The significance agent
  scores an Event; `PropagationPolicy` — thresholds in code, tunable against
  the eval corpus — decides whether it reaches the Process layer. A trigger bar
  that drifts with prompt wording is one nobody can reason about.
- **Independent source count is computed, not reported.** The resolution agent
  names publishers; `assess_independence` collapses same-publisher pieces and
  syndicated reprints (token-shingle overlap) and returns what is actually
  behind a cluster. Twenty outlets carrying one wire story score 1.
- **`ALLOWED_EDGES` is enforced at the write.** Every relationship goes through
  `GraphWriter`, which checks the (source, type, target) triple and raises. An
  illegal edge means an agent reasoned past its layer, so it never lands.
- **New Processes are flagged, not gated.** A false Process contaminates the
  graph (agent doc §23), so discovery creates them as `candidate` with
  `requires_review` set and journals the request. Phase 0 has no reviewer, and
  blocking on one nobody has assigned would just stop the pipeline.
- **Postgres is the queue; Temporal waits for a reason.** Every stage already
  derives its pending work from ontology state, so there is no in-flight
  workflow state Temporal would be protecting — adopting it now would mean a
  second durable copy of "where has this document got to".
  [`docs/orchestration.md`](docs/orchestration.md) records the volume maths and
  names the real trigger: human-in-the-loop waits measured in days, which
  arrives with Phase 1's review queue rather than with document count.
- **The reconciler is the authority; the event path is the accelerator.** A
  dropped domain event costs latency, never correctness — which is the property
  that makes running without a broker defensible.
- **Postgres is the graph; Neo4j stays a projection.** The multi-hop query
  tech rec §6 uses to argue for a graph database is a recursive CTE. What has to
  be measured before that changes is written down in
  [`docs/graph-projection.md`](docs/graph-projection.md) — depth beyond ~6 hops,
  interactive latency, or path-shape queries. "It is a graph" is not a trigger.
- **Every traversal takes an `as_of`.** The validity-window filter lives in one
  place and is always applied: walking today's graph while claiming to describe
  July is the easiest way to produce a leaked backtest.
- **The Asset layer is not equity-only.** Commodities, currencies, bonds and
  indices are first-class: a copper shortage is expressed by copper more
  directly than by any one miner, whose costs, hedging, jurisdiction and balance
  sheet all sit between the thesis and the outcome. `reference_universe` gives
  commodities and currencies deterministic resolution — a small closed set is
  the *easiest* class to resolve, not the hardest — and an equity-only answer on
  a commodity cycle raises an advisory.
- **Advisory checks record without refusing.** `EvaluationCheck.blocking=False`
  exists for findings worth surfacing that should not discard the work — an
  equity-only Asset universe is a real signal, but throwing away the equities
  the agent did find would leave the graph emptier rather than better.
- **An unresolvable Asset candidate is kept, not invented.** No security master
  exists until #47, so an equity with no usable ticker stays a Candidate. The
  resolution rate is a discovery-quality metric.
- **Only the binding Bottleneck is mapped.** Mapping a constraint that will
  not bite for three years produces a Capability set — and eventually an Asset
  universe — for a problem nobody has yet.
- **Capabilities are shared nodes, resolved by slug then by vector.** Creating
  "heavy rare-earth separation" afresh for every Process that needs it would
  destroy ontology §13's confluence signal through a naming accident. The
  match threshold is deliberately tight: a near-duplicate is cheaper than a
  wrong merge, which fuses two Bottlenecks' Asset universes.
- **The requirement tree is stored as a tree.** `requirement_nodes` rebuild
  into the ontology's own `CapabilityRequirement`, so `is_satisfied_by` and
  `coverage` answer identically against Postgres and against the model.
- **The critic has nowhere to defend the thesis.** `ProcessCriticOutput` has no
  mitigations field and no verdict, and `NoRescueEvaluator` refuses a finding
  that argues itself down. Adjudication happens downstream with the full
  picture; the critic's output is the attack (agent doc §15).
- **Critiques are superseded, never deleted.** A thesis that survived four
  attacks is stronger than one never attacked, and that is only visible if the
  attacks stay on the record.
- **Independence is recorded, not claimed.** `LLMSettings.critic_model` points
  the critic at a different model family when one exists; until then the run
  records `prompt_only` rather than implying more.
- **An illegal State transition is refused, not stored.** The schema rejects a
  State that does not belong to the Archetype; `StateTransitionEvaluator`
  rejects a move the machine does not permit from where the Process already
  was. The agent run is kept as the record of what was proposed and why it was
  refused.
- **`basis` is assigned by code, not by the agent.** A feature the agent was
  given a measurement for is `measured`; everything else is `estimated`. Letting
  a model label its own guess as a measurement would erase the distinction
  ontology §2.4 rests on.
- **A State estimate is dated by its evidence, not by wall-clock time.** A State
  inferred from evidence ending in July is a July observation; dating it today
  would corrupt every point-in-time query that reads it.
- **Corroboration does not write a revision.** An Event that changes no belief
  adds evidence and a journal entry only — otherwise "how often did this
  Process actually move?" becomes unanswerable.
- **The default embedder is lexical, not semantic.** `HashingEmbedder` is
  deterministic and dependency-free so retrieval, tests and offline development
  work without a vendor; a semantic provider plugs in behind `Embedder`. It
  narrows candidates only — it never decides a merge.
- **Quantitative documents are not sent to Claim extraction.** The classifier
  routes them to the (not yet built) deterministic ETL service, because
  reconstructing figures from prose with an LLM is what tech rec §20 forbids.
- **Only the Anthropic provider is implemented.** The abstraction is
  provider-neutral and `ScriptedProvider` makes every agent testable offline;
  OpenAI/Google/local are a class implementing `LLMProvider` away.
