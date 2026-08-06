# Engineering Handoff — econiq_ai

**Date:** 2026-08-06
**Status:** Handoff for senior engineering review
**Source of truth:** the specification documents in `product_description/`. This document is a map, an audit, and a starting plan — it does not replace the specs.

---

## 1. What this document is

All 64 GitHub issues (#1–#64) were audited against the source specifications and **closed for review**. They are not abandoned: each issue is a well-scoped work item with verified references into the specs, and should be **reopened as its phase is scheduled**. This document records:

1. The system in brief and the non-negotiable engineering constraints.
2. The phase plan and the full issue inventory.
3. The audit findings: what the issue set covers correctly, what it is missing, and the sequencing risks and open decisions senior devs must resolve.
4. Where to start.

## 2. Source documents

| File | Role |
|---|---|
| `product_description/prd.txt` | Overview PRD: vision, principles, MVP scope, non-goals, success criteria |
| `product_description/economic_process_asset_ontology.md` | Canonical domain ontology + historical forecasting architecture (the most load-bearing spec) |
| `product_description/agent_architecture_and_evaluation.md` | 32-agent inventory, prompts, agent boundaries, evaluation framework |
| `product_description/ui_concept.md` | Research terminal UX: screens, visual primitives, interaction model |
| `product_description/technical_recommendations.md` | Stack and architecture recommendations (§1–§33) |
| `product_description/phases.txt` | The authoritative 5-phase build sequence |
| `product_description/recommended_stack.txt` | One-line stack summary table |

Issue #1 moves these into `docs/` as part of monorepo scaffolding.

## 3. The system in one page

An evidence-backed, **Process-first** investment research platform. The core chain:

```
Documents → Claims → Events → Economic Processes → Process States
→ Bottlenecks → Capabilities → Assets → (later) Trades → Outcomes → Learning
```

- **Processes, not stocks, are the unit of research.** An Asset is an investable projection of an upstream Process/Capability configuration.
- **Events are a deduplication layer**: 100 documents → clustered Claims → 1 canonical Event. Repeated reporting of one Reuters story is not 20 pieces of evidence.
- **Historical learning is state-conditioned, case-based forecasting**: find historical Processes at the same Archetype + State, find Assets that looked like the current candidate *at that time*, and use their subsequent outcomes as the empirical forecast basis. The core object is the **State-Conditioned Asset Episode** (ontology §29).
- **Thesis quality ≠ Asset quality ≠ Trade quality.** Never collapsed into one score, anywhere.

## 4. Non-negotiable engineering constraints

These recur throughout the specs and should be protected in code review:

1. **The LLM is never the source of truth** (tech rec §33). Postgres holds the canonical ontology; LLMs are processors over structured state. LLMs formulate and interpret; deterministic code computes every number.
2. **Point-in-time integrity is a hard rule** (ontology §33; agent doc §19–§20). Historical snapshots may only use information available at the observation date, restatement-aware, enforced programmatically — not by convention. Synthetic fault injection must be able to catch violations.
3. **Every material statement has provenance**: statement → claim → event → document → source location, plus agent/prompt/model/data versions on every output (agent doc §21; tech rec §28).
4. **Agents are narrow, typed, and bounded**: Pydantic-validated structured I/O at every boundary; each agent stops at its ontology layer (the Bottleneck agent never says "buy MP Materials") (agent doc §2, §14, §16).
5. **Staged, triggered updates** — documents never propagate synchronously through the whole graph (ontology §46; agent doc §13).
6. **Uncertainty language is earned**: "state distribution" is *model belief* until the calibration framework (P3.09) validates it; empirical distributions are described as "among historically comparable situations…" until calibrated (ontology §35).
7. **Temporal versioning everywhere**: no destructive updates; journal entries immutable; any past conclusion reconstructible ("Why did the system believe this on July 14?" — ui_concept §32).

## 5. Phase plan and issue inventory

Phase objectives from `phases.txt`. Labels on every issue: `phase-N` + `order-NN` (build order within phase).

### Phase 0 — Research engine (#1–#17)
*Objective: prove a document stream can become a coherent, evolving Process graph. No fancy frontend.*

| # | Title |
|---|---|
| 1 | Monorepo scaffolding, CI/CD, local dev environment |
| 2 | Core ontology schema in PostgreSQL (system of record) |
| 3 | Shared Pydantic ontology & schemas package |
| 4 | LLM provider abstraction, structured outputs, prompt versioning |
| 5 | Document ingestion pipeline (S3 + metadata + parsing) |
| 6 | Document Classifier & Claim Extraction agents |
| 7 | Event resolution — clustering, dedup & significance |
| 8 | Process Discovery & Process Update agents |
| 9 | Process Archetype & Process State agents |
| 10 | Process Critic agent (adversarial falsification) |
| 11 | Bottleneck Identification & Capability Mapping agents |
| 12 | Basic Asset discovery & exposure mapping |
| 13 | Graph relationship queries & traversal layer (Postgres-first; Neo4j deferred) |
| 14 | Update & trigger orchestration (staged event-driven pipeline) |
| 15 | FastAPI domain API |
| 16 | Agent run logging, versioning & evaluation harness |
| 17 | End-to-end validation: document stream → coherent Process graph |

### Phase 1 — Research terminal (#18–#34)
*Objective: the system becomes usable. Next.js terminal over the Phase 0 engine.*

| # | Title |
|---|---|
| 18 | Next.js frontend scaffold & app shell |
| 19 | Authentication, users & workspaces (Clerk) |
| 20 | UI-facing BFF endpoints |
| 21 | Discover screen: emerging Processes, hot cards, screener |
| 22 | Emergence Radar visualization |
| 23 | Process screen: overview, state history, state distribution |
| 24 | Evidence timeline & provenance inspector |
| 25 | Explainable score decomposition — universal [Explain] primitive |
| 26 | Dependency graph explorer (React Flow) |
| 27 | Bottleneck view & Capability explorer |
| 28 | Asset page & discovery chain |
| 29 | Asset comparison matrix |
| 30 | Asset underwriting screen (Why this / Why now / Why not) |
| 31 | Thesis journal |
| 32 | Watchlist, semantic alerts & notification center |
| 33 | Natural-language research assistant (grounded) |
| 34 | Event-driven UI updates (SSE/WebSockets) |

### Phase 2 — Historical engine (#35–#46)
*Objective: the differentiating layer — historical State matching, Asset matching, replay, forward-return analysis.*

| # | Title |
|---|---|
| 35 | Historical dataset acquisition & ingestion (survivorship-bias-free) |
| 36 | DuckDB + Parquet analytical layer |
| 37 | Historical Process timelines & State snapshots |
| 38 | Historical Asset snapshots & Outcome engine (deterministic) |
| 39 | Point-in-time integrity enforcement & leakage detection |
| 40 | State-Conditioned Asset Episodes |
| 41 | Historical analog retrieval & similarity scoring |
| 42 | Historical State Alignment agent |
| 43 | Historical Asset Matching agent |
| 44 | Forward-return analysis (non-probabilistic framing) |
| 45 | Historical analogue UI & Thesis Replay |
| 46 | Extreme-opportunity discovery (pattern search) |

### Phase 3 — Quantitative ranking (#47–#58)
*Objective: richer market data, deterministic financial normalization, cross-sectional ranking, calibration.*

| # | Title |
|---|---|
| 47 | Market data provider abstraction & time-series store (TimescaleDB) |
| 48 | Financial ETL & derived metrics (deterministic) |
| 49 | Technical analysis service |
| 50 | Asset Quant service — cross-sectional comparison |
| 51 | Analysis library (reusable quant templates) |
| 52 | Sandboxed Quantitative Analysis agent |
| 53 | Asset Ranking agent & explainability |
| 54 | Empirical Process→Asset relationship measurement |
| 55 | Calibration framework |
| 56 | Evaluation benchmark datasets |
| 57 | Research Quality Auditor & synthetic fault injection |
| 58 | System Performance dashboard |

### Phase 4 — Probabilistic forecasting (#59–#64)
*Objective: only after calibration — Current State → historical conditional distribution → Asset outcome distributions.*

| # | Title |
|---|---|
| 59 | Empirical conditional distribution engine |
| 60 | Analog Forecast & Forecast Explanation agents |
| 61 | Forecast evolution tracking & visualization |
| 62 | Tail-aware forecasting & extreme-winner metrics |
| 63 | Process State transition & trajectory modeling |
| 64 | Trade construction layer (exploratory; gated on P3.09 + P4.01 validation) |

## 6. Audit findings

### 6.1 What checks out

- **Full phase coverage.** All items in `phases.txt` map to issues; build order within each phase is sensible (contracts → data → agents → API → validation).
- **References verified.** Spot-checked section references across all 64 issues against the specs — they are accurate (e.g. #2 → ontology §3–§17, #39 → ontology §33 + agent doc §19–§20, #59 → ontology §34–§36).
- **PRD MVP scope (§25) and non-goals (§26) are respected.** Trade construction is exploratory-only and explicitly gated (#64); options/portfolio work is excluded from V1 everywhere.
- **The hard constraints are embedded in the right issues**: point-in-time enforcement is its own issue (#39) with fault injection; provenance and versioning appear in #2, #4, #16, #24; the Postgres-first / Neo4j-as-projection decision (#13) matches tech rec §6.
- **27 of the 32 specified agents/services** in the agent doc's inventory are covered by an issue (see the gap list below for the 5 that aren't).

### 6.2 Gaps — specified in docs, initially covered by no issue

Each gap has since been filed as a new issue (#65–#71, open):

1. **Thesis Scoring Agent** (agent doc §11.1; ontology §42) → **#65 (P1.18)**. The Phase 1 scorecard UI (#25) displays multidimensional Thesis Quality, and #30 persists a structured thesis object — but no original issue built the agent that computes those scores. This is a Phase 1 blocker, not a nice-to-have.
2. **Counterfactual / Falsification Agent** (agent doc §10.1) → **#66 (P1.19)**. Distinct from the Process Critic (#10). The "Counterfactual Robustness" score shown on Phase 1 screens (#23, #25) had no producer.
3. **Evidence Independence Agent** (agent doc §10.2) → **#67 (P1.20)**. #7 tracks source independence during event resolution, but the dedicated agent producing an evidence-dependence graph — which feeds the "Evidence Independence" scorecard dimension — was unassigned.
4. **Thesis Synthesis Agent** (agent doc §11.3) → **#68 (P1.21)** and **Asset Synthesis Agent** (§11.4) → **#69 (P1.22)**. Human-readable, evidence-cited narratives. Thesis Synthesis is in the agent doc's *recommended MVP* list (§24); the underwriting screen (#30) implicitly needs it.
5. **Cloud deployment & IaC** → **#70 (P1.23)**. Tech rec §29–§30 specifies AWS (CloudFront/ALB/ECS-Fargate, RDS, ElastiCache, SQS/SNS) with Terraform. #1 covers only CI and local Docker Compose. Needed at the *start* of Phase 1 (Clerk-authenticated SaaS), despite the order label.
6. **Research workspace & user-supplied research** (ui_concept §21, §33; PRD §23) → **#71 (P2.13)**. Only labeling groundwork existed (#24). ui_concept §36 places workspaces in its Phase 2.

### 6.3 Sequencing risks inside the existing issues

1. **Phase 1 screens reference Phase 2/3 data.** "Historical precedent" scores (#21, #23) precede the Phase 2 historical engine; valuation/technicals/crowding columns (#29) and "technical confirmation/invalidation" alerts (#32) precede Phase 3 services. #29 acknowledges this; the others should ship with those fields stubbed/hidden and the dependency stated.
2. **Phase 1 Asset pages have no data source.** #28 shows "basic fundamentals/metadata" and #30 builds investment cases, but the earliest financial/market data ingestion is Phase 2 (historical) and Phase 3 (live). Decide: pull a minimal reference/fundamentals feed forward into Phase 1, or restrict Phase 1 Asset pages to ontology-derived content (exposure chains, evidence).
3. **Agent-doc MVP vs phases.txt sequencing.** Agent doc §24's recommended MVP includes historical agents and the Research Quality Auditor; the issues follow `phases.txt` and defer them to Phases 2–3. This is a deliberate, reasonable choice — but it means Phase 0/1 runs without the Auditor's leakage/provenance checks. #16's eval harness is the interim safety net; keep it honest.
4. **Ontology §39 places empirical return distributions in V1; `phases.txt` defers them to Phase 4.** The issues follow `phases.txt` (#44 ships descriptive forward-return summaries in Phase 2; #59 ships the distribution engine in Phase 4). Treat `phases.txt` as controlling; the interim framing rule of ontology §35 (no probability language) applies throughout.

### 6.4 Open decisions for senior devs

| Decision | Where | Notes |
|---|---|---|
| Temporal from day one vs queue+workers first | #14 | Tech rec §10 strongly recommends Temporal; #14 permits starting minimal with explicit resumable workflow definitions. Migrating orchestration later is expensive — decide before #14 starts. |
| Phase 1 asset data source | #28–#30 | See 6.3.2. |
| Historical data vendor & licensing | #35, #47 | Cost/licensing evaluation is scoped in #35 but no vendor shortlist exists. Longest-lead-time item in Phase 2 — start early. |
| Attention-proxy metric definition | #21, #22 | "Market attention" drives the Emergence Radar and discover ranking; no spec defines how it's measured. |
| LLM provider(s) and model tiering per agent | #4 | The abstraction is specced; the actual model choices and cost budget are not. |

## 7. Where to start

Phase 0, in label order. The critical path is **#1 → #2 → #3 → #4**, because #2/#3 (schema + Pydantic contracts) are the contract every agent, API, and the future frontend depend on — get senior review on those two before building any agent. Then #5–#12 (pipeline + agents) can partially parallelize against #13–#16 (graph, orchestration, API, eval harness). #17 is the phase gate: a written evaluation against PRD §28 criteria on a curated corpus of 2–3 known real Processes.

The gap issues from §6.2 are filed as #65–#71 and left open. #65–#67 (Thesis Scoring, Counterfactual, Evidence Independence) block Phase 1's scorecard; #70 (deployment/IaC) should be scheduled at the start of Phase 1.

## 8. Issue state

All 64 original issues (#1–#64) were closed on 2026-08-06 with an audit comment referencing this document. Reopen per phase as work is scheduled — the scopes and references in the issue bodies were verified against the specs and can be used as-is.

The 7 gap issues found by the audit were filed the same day as **#65–#71** and remain **open**:

| # | Title | Fills gap |
|---|---|---|
| 65 | P1.18: Thesis Scoring agent | §6.2.1 |
| 66 | P1.19: Counterfactual / Falsification agent | §6.2.2 |
| 67 | P1.20: Evidence Independence agent | §6.2.3 |
| 68 | P1.21: Thesis Synthesis agent | §6.2.4 |
| 69 | P1.22: Asset Synthesis agent | §6.2.4 |
| 70 | P1.23: Cloud deployment & Terraform IaC | §6.2.5 |
| 71 | P2.13: Research workspace & user-supplied research | §6.2.6 |
