# 1. Architecture Diagram

                         ┌──────────────────────────┐
                         │        Next.js UI        │
                         │ React + TypeScript       │
                         └────────────┬─────────────┘
                                      │
                              REST / GraphQL
                                      │
                         ┌────────────▼─────────────┐
                         │       API Gateway /       │
                         │      Backend-for-Frontend │
                         │       FastAPI / Python    │
                         └────────────┬─────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
 ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
 │ Ontology / Graph│        │ Research / Agent│        │ Quant / Market  │
 │    Services     │        │    Services     │        │    Services     │
 └────────┬────────┘        └────────┬────────┘        └────────┬────────┘
          │                          │                          │
          ▼                          ▼                          ▼
 ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
 │ PostgreSQL      │        │ Temporal        │        │ TimescaleDB /   │
 │ + pgvector      │        │ Workflow Engine │        │ ClickHouse      │
 └────────┬────────┘        └────────┬────────┘        └─────────────────┘
          │                          │
          ▼                          ▼
 ┌─────────────────┐        ┌─────────────────┐
 │ Neo4j / Graph   │        │ Python Workers  │
 │ Projection      │        │ LLM + Quant     │
 └─────────────────┘        └─────────────────┘

             ┌────────────────────────────────────┐
             │ S3 / Object Storage                │
             │ Documents / Filings / Raw Data     │
             └────────────────────────────────────┘

--

# 2. Frontend
Recommended

Next.js + React + TypeScript

With:

Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
TanStack Query
Zustand or Redux Toolkit where state actually warrants it
Visualization

Use:

React Flow for ontology graphs
D3.js for bespoke analytical visualizations
Plotly or Apache ECharts for quantitative charts
potentially deck.gl later for extremely large graph/market visualizations

I would not use D3 for everything. D3 is excellent for custom analytical visualizations but can become unnecessarily painful as an application UI framework.

---

# 3. Why React Flow is particularly useful

The ontology naturally becomes a node graph:

Process
   │
   ▼
Bottleneck
   │
   ▼
Capability
   │
   ▼
Asset

React Flow gives you a relatively straightforward way to implement:

expandable nodes,
typed edges,
node selection,
graph navigation,
mini-map,
zooming,
custom node rendering,
interactive filtering.

D3 can then handle things such as:

Process State trajectories,
evidence accumulation,
historical replay,
emergence radar,
multidimensional score visualizations.

---

# 4. Backend API

I would use:

Python + FastAPI

rather than Node for the main backend.

Reasons:

same language as the quantitative environment,
excellent LLM ecosystem,
Pydantic,
pandas/polars,
scientific libraries,
easier agent development,
easier integration with research notebooks,
strong async support.

The backend should be organized around domain services rather than individual AI agents.

For example:

/api/processes
/api/events
/api/evidence
/api/bottlenecks
/api/capabilities
/api/assets
/api/historical-analogs
/api/theses
/api/watchlists
/api/alerts
/api/research

---

# 5. Primary database
PostgreSQL

This should be the system of record.

I would put the canonical ontology in PostgreSQL.

It should contain entities such as:

documents
events
processes
process_states
bottlenecks
capabilities
assets
theses
evidence
relationships
scores
observations
historical_episodes
agent_runs
model_versions

Postgres is exceptionally good for this because the ontology is not actually "just a graph."

You have enormous amounts of relational metadata attached to every node:

timestamps,
provenance,
confidence,
ownership,
versioning,
source,
scores,
user annotations,
permissions,
model versions.

That is fundamentally relational data.

---

# 6. Graph database

This is one area where I would be slightly unusual.

I would not initially make Neo4j the canonical database.

Instead:

Postgres = source of truth
Neo4j = graph projection / traversal engine

The reason is that your graph has a lot of non-graph metadata.

For example:

Process
├── created_at
├── current_state
├── state_confidence
├── archetype
├── evidence_score
├── model_version
├── owner
├── historical_analog_score
└── ...

Postgres handles that extremely well.

Neo4j becomes useful when you start asking:

"Show me all Assets within 4 causal hops of Processes A, B and C where the relationships satisfy these conditions."

That is where a graph database becomes valuable.

So:

Postgres → authoritative ontology

Neo4j → optimized graph projection

This also prevents the graph database from becoming an architectural hostage.

---

# 7. Vector database

Initially:

pgvector inside PostgreSQL

rather than immediately introducing Pinecone, Weaviate, etc.

You need embeddings for:

document similarity,
Event deduplication,
historical analogue retrieval,
semantic search,
related Process discovery,
evidence clustering.

For the first version, pgvector is entirely adequate.

You can migrate the embedding workload later if scale demands it.

---

# 8. Raw document storage

Use:

Amazon S3

for:

PDFs,
HTML snapshots,
filings,
transcripts,
downloaded datasets,
extracted tables,
raw market data,
generated research artifacts.

Postgres should contain metadata and references.

Don't put large documents directly into Postgres.

Architecture:

S3
 │
 ├── raw document
 ├── normalized document
 ├── extracted tables
 └── derived artifacts

Postgres
 │
 └── metadata + provenance + relationships


---

# 9. Search

Eventually I would add:

OpenSearch

for full-text search across:

documents,
Events,
Processes,
Assets,
evidence,
research notes.

But I would not necessarily add it on day one.

Postgres full-text search + pgvector can get you surprisingly far.

Introduce OpenSearch once search becomes a significant product surface.

---

# 10. Workflow orchestration

This is one of the most important architectural choices.

I strongly recommend:

Temporal

rather than trying to orchestrate everything with Celery, cron jobs, or ad hoc queues.

Your workflows are inherently long-running and stateful.

For example:

Document arrives
     ↓
Extract
     ↓
Deduplicate
     ↓
Create Event
     ↓
Update Process A
     ↓
Update Process B
     ↓
Recalculate Bottleneck
     ↓
Update Capabilities
     ↓
Update Assets
     ↓
Generate alerts

Some steps might fail.

Some might need retries.

Some might wait for additional evidence.

Some might take hours.

Some might require human approval.

Temporal is designed for exactly this class of problem.

---

# 11. Message/event infrastructure

For asynchronous event propagation:

Kafka / Redpanda

or, initially, a managed cloud queue.

I would probably start with:

AWS SQS/SNS

for MVP simplicity.

Then migrate toward Kafka/Redpanda if event volume and streaming requirements justify it.

The conceptual architecture should nevertheless be event-driven:

DocumentIngested
EventCreated
EventUpdated
ProcessUpdated
StateTransitionCandidate
BottleneckUpdated
CapabilityUpdated
AssetUpdated
ThesisUpdated
AlertCreated

These should be typed domain events.

---

# 12. Agent runtime

I would avoid making the entire system dependent on one "agent framework."

Use ordinary Python services plus a thin agent abstraction.

For example:

class Agent:
    input_schema
    output_schema
    system_prompt
    tools
    model
    evaluator

Every agent should produce structured output validated with Pydantic.

For example:

ProcessUpdateAgent
        ↓
ProcessUpdateSchema
        ↓
Validation
        ↓
Database

This is much safer than letting an LLM return arbitrary JSON.

---

# 13. LLM framework

You could use LangGraph, but I would use it selectively.

It is useful for:

multi-step reasoning,
tool calls,
agent loops,
stateful agent execution.

But I would not make the ontology itself dependent on LangGraph.

The ontology should exist independently of whatever agent framework happens to be fashionable.

A reasonable architecture is:

Temporal
   ↓
Agent execution
   ↓
LangGraph / custom orchestration
   ↓
LLM
   ↓
Pydantic structured output
   ↓
Ontology

---

# 14. LLM providers

Build a provider abstraction from day one.

Something like:

LLMService
 ├── OpenAI
 ├── Anthropic
 ├── Google
 └── Local model

Do not scatter provider-specific API calls throughout the codebase.

This lets you evaluate:

reasoning quality,
extraction quality,
cost,
latency,
reliability

across models.

It also makes future model replacement painless.

---

# 15. Quantitative stack

This is particularly important given our earlier discussion.

Use:

Python

with:

Polars
Pandas
NumPy
SciPy
scikit-learn
statsmodels
PyArrow

For more advanced modeling:

XGBoost / LightGBM
PyTorch
possibly JAX

But don't introduce them simply because they're available.

---

# 16. Polars vs Pandas

I would make Polars the default production dataframe engine and retain Pandas compatibility.

Why?

Your system could eventually process:

millions of observations,
years of price history,
thousands of Assets,
hundreds of indicators,
large cross-sectional datasets.

Polars is very attractive for this workload.

Pandas remains useful because virtually every quantitative Python library understands it.

---

# 17. Quantitative database

There are two sensible choices.

Option A — simpler

PostgreSQL + TimescaleDB.

Option B — higher scale

ClickHouse.

For MVP, I'd choose:

Postgres + TimescaleDB

because it keeps the architecture simple.

You can store:

Asset
Timestamp
Price
Volume
MarketCap
Volatility
Technical indicators
Fundamental observations

and query historical time series efficiently.

If the system eventually becomes a huge market-data warehouse, move heavy analytical workloads into ClickHouse.

---

# 18. Data warehouse / analytical layer

Eventually I would introduce:

DuckDB + Parquet

for research workloads.

This is particularly attractive for historical analogue analysis.

For example:

S3
 ↓
Parquet
 ↓
DuckDB
 ↓
Historical Process analysis
 ↓
Python

DuckDB is exceptionally good for this kind of local/analytical research.

It also gives researchers a much easier way to reproduce analyses.

---

# 19. Market and financial data

The architecture should abstract market-data vendors.

Conceptually:

MarketDataProvider
 ├── equities
 ├── fundamentals
 ├── ownership
 ├── options
 ├── commodities
 ├── FX
 └── macro

Don't couple your internal Asset model to a specific vendor's schema.

Normalize everything into your own canonical representation.

---

# 20. Document extraction

Documents should go through a pipeline such as:

Raw Document
     ↓
Parser
     ↓
Normalized Text
     ↓
Structure Detection
     ↓
Table Extraction
     ↓
Document Sections
     ↓
Evidence Candidates

Useful technologies include:

PyMuPDF
Apache Tika
BeautifulSoup
trafilatura
OCR where necessary
specialized PDF/table extraction tools

For filings and earnings, structured source data should be preferred over asking an LLM to reconstruct numbers from prose.

---

# 21. Quantitative document processing

This deserves a separate pipeline.

For earnings:

Earnings Release
      ↓
Financial ETL
      ↓
Canonical Metrics
      ↓
Derived Metrics
      ↓
Historical Time Series
      ↓
Quant Agent

The LLM should explain quantitative observations, not be responsible for basic arithmetic.

For example:

Bad:

"Ask the LLM to analyze 20 quarters of revenue."

Better:

ETL
 ↓
Revenue growth = 27%
Gross margin = 73%
FCF margin = 31%
YoY acceleration = +8%
 ↓
LLM
 ↓
"Interpret the significance."

---

# 22. Agent sandbox

For agents that need Python:

Use isolated execution environments.

Something like:

Agent
 ↓
Code generation
 ↓
Sandbox
 ↓
Python / Polars / NumPy
 ↓
Results
 ↓
Agent interpretation

The sandbox should have:

resource limits,
filesystem isolation,
network restrictions,
package restrictions,
execution timeout,
audit logging.

This becomes increasingly important once agents can write arbitrary analysis code.

---

# 23. Caching

Use:

Redis

for:

API caching,
expensive query caching,
session state,
rate limiting,
temporary agent state,
frequently requested Process summaries.

Do not use Redis as the source of truth.

---

# 24. Authentication

For SaaS:

Auth0, Clerk, or AWS Cognito are reasonable.

I'd lean toward:

Clerk for a startup/MVP because of developer velocity.

You need:

users,
organizations,
roles,
invitations,
SSO eventually,
API keys,
permissions.
25. Observability

This system absolutely needs first-class observability.

Use:

OpenTelemetry

with:

traces,
logs,
metrics.

Then something like:

Grafana
Prometheus
Loki
Sentry

for operational visibility.

But also build research observability.

You want to know:

Agent
 ↓
Prompt version
 ↓
Input evidence
 ↓
Model
 ↓
Output
 ↓
Evaluator
 ↓
Database mutation

This is as important as ordinary infrastructure monitoring.

---

# 26. LLM observability

Use something such as:

Langfuse
Arize Phoenix
or an equivalent LLM tracing/evaluation system.

You want to measure:

token cost,
latency,
model,
prompt version,
tool calls,
structured-output failures,
evaluation score,
hallucination rate,
citation coverage.

The agent system should effectively have its own experiment database.

---

# 27. Evaluation infrastructure

This deserves to be treated as a first-class service.

You need an evaluation framework that can replay:

Historical Evidence
       ↓
Agent
       ↓
Prediction
       ↓
Actual Historical Outcome
       ↓
Evaluation

For example:

Process State prediction
       ↓
Did State transition occur?
       ↓
Within 3 months?
Within 6 months?
Within 12 months?

And:

Asset ranking
       ↓
Forward return
       ↓
Risk-adjusted return
       ↓
Ranking IC

This is where the system moves from "interesting AI demo" to actual research infrastructure.

---

# 28. Versioning

Everything needs versions.

At minimum:

Ontology version
Agent version
Prompt version
LLM model version
Data version
Feature version
Scoring version
Evaluation version

A Process update should effectively say:

Process: domestic semiconductor manufacturing
Updated: 2026-08-06
Agent: ProcessUpdateAgent v1.4
Prompt: v12
Model: X
Evidence snapshot: 8f91...
Ontology: v0.8

This is necessary for reproducibility.

---

# 29. Deployment

For an MVP, I would avoid Kubernetes.

A reasonable AWS architecture:

CloudFront
    ↓
Next.js
    ↓
ALB
    ↓
ECS / Fargate
    ↓
FastAPI

Workers
    ↓
ECS / Fargate

Temporal Cloud
    ↓
Workers

RDS PostgreSQL
S3
ElastiCache Redis
SQS/SNS

Then add:

Neo4j Aura
ClickHouse Cloud
OpenSearch

only when needed.

Kubernetes becomes worthwhile later if the system develops a large fleet of heterogeneous workers and significant infrastructure complexity.

---

# 30. Infrastructure as Code

Use:

Terraform

for infrastructure.

Repository structure could eventually look like:

/infrastructure
    /terraform
    /environments
        /dev
        /staging
        /production

CI/CD:

GitHub Actions

with:

unit tests,
integration tests,
type checking,
linting,
agent evaluations,
frontend tests,
container builds,
deployment.

---

# 31. Testing

This project needs several different testing layers.

Conventional software tests
unit tests
integration tests
API tests
frontend tests
Ontology tests

Ensure invalid graph relationships cannot be created.

Agent tests

Known input → expected structured output.

Historical replay tests

Run the system against historical data as if it were live.

Quantitative tests

Ensure calculations don't change unexpectedly.

Calibration tests

Compare predicted probabilities/states against realized outcomes.

Regression tests

Ensure a prompt/model change doesn't silently degrade performance.

---

# 32. Recommended repository structure

I would probably use a monorepo:

investment-intelligence/
│
├── apps/
│   ├── web/
│   └── api/
│
├── services/
│   ├── ingestion/
│   ├── agents/
│   ├── quant/
│   ├── historical/
│   ├── alerts/
│   └── graph/
│
├── packages/
│   ├── ontology/
│   ├── schemas/
│   ├── scoring/
│   ├── data-models/
│   └── llm/
│
├── research/
│   ├── notebooks/
│   ├── historical/
│   └── experiments/
│
├── infrastructure/
│   └── terraform/
│
└── docs/
    ├── economic_process_asset_ontology.md
    ├── agent_architecture_and_evaluation.md
    ├── ui_concept.md
    └── overview_prd.md

The ontology and schemas packages are particularly important because they become the contract between the agents, backend, database, and frontend.

---

# 33. The most important architectural decision

If I had to pick one architectural principle to protect aggressively, it would be:

The LLM must never be the source of truth.

The source of truth is:

Structured ontology
+
Evidence
+
Events
+
Quantitative observations
+
Temporal history

The LLM is a processor operating on that state.

So rather than:

User
 ↓
LLM
 ↓
Answer

the system should look like:

                     ┌── Documents
                     │
                     ├── Market data
                     │
                     ├── Financial data
                     │
                     └── Historical data
                              │
                              ▼
                       Structured State
                              │
                              ▼
                       Economic Graph
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
               Quant Engine        LLM Agents
                    │                   │
                    └─────────┬─────────┘
                              ▼
                       Updated Model
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                   UI                 Alerts

That architecture directly addresses the limitations we discussed at the beginning.