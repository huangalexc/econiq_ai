# Services

Deployable units, each owning one stage of the pipeline. Empty until the issue
that introduces it is scheduled — a directory with a placeholder module is worse
than no directory, because it looks like something works.

| Directory | Issue | Purpose |
|---|---|---|
| `ingestion/` | #5 | Document acquisition, S3 storage, parsing |
| `agents/` | #6–#12 | The Phase 0 agent implementations over `packages/llm` |
| `graph/` | #13 | Relationship queries and traversal over Postgres |
| `quant/` | #48–#52 | Deterministic financial computation (Phase 3) |
| `historical/` | #35–#44 | Historical engine (Phase 2) |
| `alerts/` | #32 | Watchlists and semantic alerts (Phase 1) |
