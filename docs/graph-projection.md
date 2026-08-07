# When to add a graph database

**Status:** decision recorded, not scheduled. Written as part of issue #13.

Tech rec §6 makes the call: **Postgres is the source of truth, Neo4j is a
projection.** This document says what that means in practice, when the
projection becomes worth building, and what has to be true before it does.

## Why Postgres holds the graph

The ontology is not "just a graph". Every node carries timestamps, provenance,
confidence, revisions, agent runs, scores and permissions, and every edge
carries evidence and a rationale. That is relational data with a graph shape
attached, not the reverse.

Concretely, the things this system does constantly are:

| Query | Shape |
|---|---|
| "What does this Process currently believe, and why?" | Row lookup + joins |
| "What changed since July 14?" | Temporal range scan |
| "Which Claims support this Event?" | Join |
| "Which Assets sit within four causal hops of these Processes?" | **Traversal** |

Only the last is a graph query, and `econiq_graph.queries` answers it with a
recursive CTE. The others would be worse in a graph database, not better.

## What we would lose by making Neo4j canonical

- **Temporal integrity.** Every traversal here takes an `as_of` and filters
  edges by their validity window (`_temporal_sql`). Point-in-time correctness is
  a hard rule (ontology §33), and reproducing bitemporal revisions in a second
  store is a source of drift, not a feature.
- **One writer.** Today `GraphWriter` is the only path that creates an edge, and
  it validates the triple against `ALLOWED_EDGES`. Two stores means either two
  writers or an eventually-consistent sync, and the second store is then a place
  where illegal edges can exist.
- **Provenance in one place.** `agent_runs`, `evidence_links` and the revision
  tables are all foreign-keyed together. A projection cannot enforce that.

## When the projection becomes worth building

Add it when a **measured** traversal problem appears that Postgres cannot serve.
The honest triggers, in order of likelihood:

1. **Depth.** Traversals routinely need more than ~6 hops. Recursive CTEs
   degrade with depth and branching; property-graph engines do not degrade the
   same way.
2. **Latency at breadth.** An interactive query — the dependency graph explorer
   of issue #26, or Discover-screen ranking — exceeds a few hundred milliseconds
   on a warm cache with realistic Phase 2 volumes.
3. **Path-shape queries.** Questions that are awkward as CTEs become common:
   shortest weighted path, all-paths-with-constraints, centrality, community
   detection over the Process graph.

Two things that are **not** triggers: "a graph database is the natural fit for a
graph" (the data is mostly not graph-shaped), and "the query is hard to write"
(a hard CTE is cheaper than a second datastore).

## How to build it when the time comes

1. **Project, never dual-write.** A worker tails the revision tables and rebuilds
   the projection. Postgres stays the only thing anything writes to.
2. **Project the skeleton only.** Node id, node type, edge type, weight,
   confidence, validity window. No prose, no scores, no evidence — Neo4j answers
   "which ids are connected how", then Postgres is asked about those ids. This
   keeps the projection small enough to rebuild from scratch, which is the
   property that makes drift recoverable.
3. **Keep the interface.** `GraphQueries` is the internal API. A Neo4j-backed
   implementation should satisfy the same methods, so agents and the API do not
   learn that a second store exists.
4. **Verify against Postgres.** The CTE implementation becomes the oracle: run
   both for a period and diff the results. A projection that disagrees with the
   source of truth and is trusted anyway is worse than no projection.
5. **Rebuild, don't repair.** If the projection drifts, drop and rebuild it.
   Reconciliation logic is where the correctness of the second store goes to
   die.

## What exists today

`services/graph` provides the interface a projection would have to satisfy:

- `GraphQueries.traverse` — bounded, cycle-safe, point-in-time traversal
- `GraphQueries.assets_within_hops` — the tech rec §6 query
- `GraphQueries.discovery_chain` — why an Asset is in the graph (issue #28)
- `GraphQueries.confluence` — independent upstream Processes (ontology §13)
- `GraphQueries.subgraph` — nodes and edges for rendering (issue #26)
- `GraphIntegrity` — illegal edges, causal cycles, orphans, revision uniqueness

Until one of the three triggers above is measured on real data, adding Neo4j
buys an operational burden and a consistency problem in exchange for a query
plan we do not yet need.
