# Orchestration: why Postgres, and when Temporal

**Status:** decision recorded. Resolves the open decision in
`ENGINEERING_HANDOFF.md` §6.4, "Temporal from day one vs queue+workers first".

Tech rec §10 recommends Temporal. This document explains why we are not adopting
it yet, what we built instead, and the specific condition that changes the
answer — so the decision can be revisited on evidence rather than re-argued.

## The decisive fact

**Every stage is already a reconciliation loop.** Each one derives its
outstanding work from durable ontology state, not from a queue:

| Stage | How it knows what is pending |
|---|---|
| Process discovery | Propagated Events with no `process_discovery` agent run |
| Archetype / State | Processes whose journal moved after their last State |
| Critic | Processes whose State moved after their last critique |
| Bottleneck / Capability | Processes whose State moved after their last Bottleneck |
| Asset discovery | Capabilities of binding Bottlenecks with no `expressed_by` edge |

Temporal's core value is durable execution for workflows whose progress would
otherwise be lost on a crash. Here it would not be lost — it is recoverable from
the ontology. Adopting Temporal now would mean maintaining a *second* durable
representation of "where has this document got to", and that second copy is what
becomes expensive to unwind later, not the queue.

## The volume argument

At 1,000 documents/day, with the compression the pipeline already performs:

| Stage | Input | LLM calls/day |
|---|---|---|
| Classify + extract | 1,000 documents | ~2,000 |
| Event resolution | ~5,000 claims, batched | ~100 |
| Significance | ~400 events | ~400 |
| *Propagation gate* | ~15% pass | — |
| Process → Asset layers | ~60 events | ~350 |

≈2,800 calls/day ≈ **2 per minute**. Ten-times burst is 20/minute. Postgres with
`FOR UPDATE SKIP LOCKED` is nowhere near stressed — it is the mechanism behind
River, Oban, Solid Queue and graphile-worker at far higher rates.

The number that *does* scale is cost: roughly **$150–200/day** at that volume,
dominated by reasoning-tier calls. So the orchestrator's job is deduplication,
batching and gating — not throughput. Every design choice below follows from
that.

## What we built

```
state change ──┬─> ontology tables        (the source of truth)
               └─> outbox_events          (same transaction — no dual write)
                          │
                    Dispatcher
                          ↓
                    work_items            (FOR UPDATE SKIP LOCKED)
                          ↓
                       Worker ──> stage handler ──> emits events ──┐
                          │                                        │
                          └── completion + events, one transaction ─┘

           Reconciler ──> queries ontology state ──> enqueues what was missed
```

Four properties, each load-bearing:

**Transactional outbox.** A domain event is a row written in the same commit as
the state change. There is no window in which the state exists and the event
does not, which is the failure a queue-plus-database dual write always has.

**Idempotency keys.** A partial unique index over *open* work items means the
event path and the reconciler can both enqueue the same work and the second is a
no-op. Completed items are kept, so the same stage can legitimately run again
when new evidence arrives.

**Atomic completion.** A worker marks its item done and stages its emitted
events in one transaction. A stage cannot complete without its successor being
scheduled, and cannot schedule a successor without being complete.

**The reconciler is the authority.** The event path provides latency; the
reconciler provides correctness. A dropped event is a delay, never a gap. This
is the property that makes running without a broker defensible — and it exists
only because the stages were written as reconciliation loops in the first place.

## Trigger types (agent doc §13)

All four express themselves through the same queue:

| Trigger | Mechanism |
|---|---|
| Delta | A domain event fires; the dispatcher enqueues |
| Threshold | The propagation gate emits `event.propagated` only when materiality, credibility and independent sourcing clear (`PropagationPolicy`) |
| Time | `run_after` in the future — accumulation windows are a scheduled item |
| Explicit | `Trigger.MANUAL` with a chosen priority |

## When Temporal earns its place

**Not volume.** The trigger is *human-in-the-loop waits measured in days*.

Today `requires_review` is a flag, and the pipeline continues past it. When a
Phase 1 reviewer actually blocks a stage — a new Process awaiting approval
before its Capabilities are mapped — the requirements change qualitatively:
durable timers, signals from an external actor, escalation after N days, and
visibility into everything parked. That is Temporal's problem domain, and
rebuilding it on a work queue would be rebuilding Temporal badly.

Secondary triggers, in rough order of likelihood:

1. **Cross-service sagas.** Phase 3 market-data ETL failing halfway and needing
   compensating actions across services.
2. **Sub-second dispatch latency** as a product requirement. Polling has a floor;
   Temporal's task queues do not.
3. **Queue depth sustained above ~10k items** with contention on the claim query.
   Realistically a Phase 2 backfill problem, and one that priority lanes solve
   first.

Explicitly *not* triggers: "the tech rec recommends it", "workflows are the
right abstraction", or the pipeline having many stages. It has many stages
today and they compose fine as declared data.

## How the migration would work

`stages.py` is a declaration, not control flow: each `StageDefinition` names
what triggers it, what it emits, its priority and its concurrency. The runner
consumes that.

1. Implement a Temporal worker that reads the same `PIPELINE` definitions.
2. Keep the outbox — it becomes the signal source instead of the dispatcher's
   input.
3. Keep the reconciler. Whatever executes the work, "what does the ontology say
   is outstanding" remains the correctness backstop, and it is cheap.
4. Cut over one stage at a time; both executors can claim from the same queue
   during the transition because the idempotency key prevents double-execution.

The stage handlers themselves do not change. That is the point of writing them
against `(subject_id, payload) -> [Emitted]` rather than against an executor.

## What is not solved here

- **Cost budgets.** Per-stage concurrency limits are declared but not yet
  enforced by the runner, and there is no spend ceiling. Issue #58's dashboard
  is where that surfaces; the data is already on `agent_runs`.
- **Event resolution fan-in** (issue #72). The batching in front of the
  clustering agent is the real scaling problem, and it is not an orchestration
  problem.
- **Backpressure.** Nothing currently slows ingestion when the queue is deep.
  At present volumes that is theoretical.
