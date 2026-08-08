"use client";

/**
 * Process screen (issue #23, ui_concept §6).
 *
 * §6 asks for four synchronized perspectives: overview, state evolution,
 * evidence timeline, dependency graph. "Synchronized" is the requirement that
 * does the work — every panel reads the same `as_of`, so moving the cut-off
 * moves all four together and the reader cannot end up comparing a July State
 * against August evidence.
 *
 * The dependency graph is #26. It is a tab that names the issue rather than a
 * missing tab, so the four perspectives are visibly four.
 */

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

import { EvidenceTimeline } from "@/components/process/evidence-timeline";
import { ProcessHeader } from "@/components/process/process-header";
import { StateBelief } from "@/components/process/state-belief";
import { StateMachineTrack } from "@/components/process/state-machine";
import { ApiError, api } from "@/lib/api/client";
import type { ProcessDetail } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "state", label: "State evolution" },
  { id: "evidence", label: "Evidence timeline" },
  { id: "graph", label: "Dependency graph" },
] as const;

type Tab = (typeof TABS)[number]["id"];

export default function ProcessPage() {
  const { id } = useParams<{ id: string }>();
  const { asOf } = useAsOf();
  const [tab, setTab] = useState<Tab>("overview");

  // One cut-off, four panels. Each query carries `asOf` in its key, so
  // switching the cut-off refetches all of them rather than leaving a stale
  // panel beside a fresh one.
  const detail = useQuery({
    queryKey: keyFor(["process", id], { asOf }),
    queryFn: ({ signal }) => api.processes.get(id, { asOf, signal }),
  });
  const states = useQuery({
    queryKey: keyFor(["process", id, "states"], { asOf }),
    queryFn: ({ signal }) => api.processes.states(id, { asOf, signal }),
  });
  const timeline = useQuery({
    queryKey: keyFor(["process", id, "timeline"], { asOf }),
    queryFn: ({ signal }) => api.processes.timeline(id, { asOf, signal }),
  });
  const scores = useQuery({
    queryKey: keyFor(["scores", id], { asOf }),
    queryFn: ({ signal }) => api.scores(id, { asOf, signal }),
  });
  const machines = useQuery({
    queryKey: ["archetypes"],
    queryFn: ({ signal }) => api.archetypes({ signal }),
    staleTime: Infinity,
  });

  if (detail.isPending) {
    return <p className="px-8 py-10 text-sm text-ink-muted">Loading…</p>;
  }
  if (detail.isError) {
    return <Failure error={detail.error} />;
  }

  const process = detail.data;
  const machine = machines.data?.find((m) => m.archetype === process.archetype);
  const history = states.data ?? [];

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <ProcessHeader
        process={process}
        scorecards={scores.data ?? []}
        evidenceDelta={evidenceDelta(timeline.data?.entries ?? [])}
      />

      <nav className="mt-6 flex gap-1 border-b border-border" aria-label="Perspectives">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            aria-current={tab === item.id ? "true" : undefined}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
              tab === item.id
                ? "border-accent text-ink"
                : "border-transparent text-ink-muted hover:text-ink",
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="py-6">
        {tab === "overview" ? (
          <Overview process={process} />
        ) : tab === "state" ? (
          <div className="grid gap-10 lg:grid-cols-2">
            <section>
              <h2 className="text-sm font-medium text-ink">State history</h2>
              <p className="mt-1 text-xs text-ink-muted">
                The archetype&rsquo;s machine, with the dates this Process
                arrived at each State. The sequence is served from the ontology.
              </p>
              <div className="mt-4">
                {machine ? (
                  <StateMachineTrack
                    states={machine.states ?? []}
                    history={history}
                    current={process.state?.categorical_state ?? null}
                  />
                ) : (
                  <p className="text-sm text-ink-subtle">
                    No archetype has been classified, so there is no machine to
                    place this Process on.
                  </p>
                )}
              </div>
            </section>
            {process.state ? <StateBelief state={process.state} /> : null}
          </div>
        ) : tab === "evidence" ? (
          <EvidenceTimeline entries={timeline.data?.entries ?? []} />
        ) : (
          <p className="text-sm text-ink-muted">
            The dependency graph explorer is <span className="text-ink">#26</span>.
            The traversal API behind it is built —{" "}
            <code className="text-xs">/api/graph/subgraph</code> walks the typed
            edges from this Process to its Assets, point-in-time.
          </p>
        )}
      </div>
    </div>
  );
}

function Overview({ process }: { process: ProcessDetail }) {
  const bottlenecks = process.open_bottlenecks ?? [];
  const critiques = process.open_critiques ?? [];
  const features = process.state?.features ?? [];

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <section>
        <h2 className="text-sm font-medium text-ink">Binding constraints</h2>
        {bottlenecks.length === 0 ? (
          <p className="mt-2 text-sm text-ink-subtle">
            No open Bottleneck has been identified.
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {bottlenecks.map((bottleneck) => (
              <li
                key={bottleneck.id}
                className="rounded-panel border border-border bg-surface p-3"
              >
                <p className="text-sm text-ink">
                  {bottleneck.name}
                  {bottleneck.currently_binding ? (
                    <span className="ml-2 text-[0.625rem] uppercase tracking-wider text-contradicts">
                      binding
                    </span>
                  ) : null}
                </p>
                <p className="mt-1 text-xs text-ink-muted">
                  {bottleneck.description}
                </p>
                <p className="mt-1 text-[0.6875rem] text-ink-subtle">
                  {humanise(bottleneck.kind)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        {/* Critiques are on the overview, not behind a tab. A thesis that
            survived four attacks is stronger than one never attacked, and that
            is only visible if the attacks are in front of the reader. */}
        <h2 className="text-sm font-medium text-ink">Open critiques</h2>
        {critiques.length === 0 ? (
          <p className="mt-2 text-sm text-ink-subtle">
            No open critique. This means the Critic found nothing outstanding,
            not that the thesis is unchallenged.
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {critiques.map((critique) => (
              <li
                key={critique.id}
                className="rounded-panel border border-border bg-surface p-3"
              >
                <p className="text-sm text-ink">
                  {critique.statement}
                  {critique.is_most_damaging ? (
                    <span className="ml-2 text-[0.625rem] uppercase tracking-wider text-contradicts">
                      most damaging
                    </span>
                  ) : null}
                </p>
                <p className="mt-1 text-xs text-ink-muted">{critique.rationale}</p>
                {critique.testable_with ? (
                  <p className="mt-1 text-xs text-ink-subtle">
                    Testable with: {critique.testable_with}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {features.length > 0 ? (
        <section className="lg:col-span-2">
          <h2 className="text-sm font-medium text-ink">State features</h2>
          <p className="mt-1 text-xs text-ink-muted">
            What the State estimate was built from, and whether each was measured
            by code or judged by a model.
          </p>
          <table className="mt-3 w-full text-sm">
            <tbody>
              {features.map((feature) => (
                <tr key={feature.name} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4 text-ink-muted">
                    {humanise(feature.name)}
                  </td>
                  <td className="py-2 pr-4 font-mono text-ink">
                    {feature.value.toFixed(2)}
                  </td>
                  <td className="py-2 pr-4">
                    <span
                      className={cn(
                        "text-xs",
                        feature.basis === "measured"
                          ? "text-ink-muted"
                          : "text-estimated",
                      )}
                    >
                      {feature.basis}
                    </span>
                  </td>
                  <td className="py-2 text-xs text-ink-subtle">
                    {feature.rationale}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}

/**
 * Evidence arrivals in the last 30 days against the 30 before it.
 *
 * Computed from `recorded_at`, matching the Discover ranking. Dating momentum
 * by when things happened rather than when they were learned would show a
 * backfill of old filings as a Process accelerating.
 */
function evidenceDelta(entries: { kind: string; recorded_at: string }[]): number | null {
  const evidence = entries.filter((entry) => entry.kind === "evidence");
  if (evidence.length === 0) return null;

  const now = Date.now();
  const day = 86_400_000;
  let recent = 0;
  let prior = 0;
  for (const entry of evidence) {
    const age = (now - Date.parse(entry.recorded_at)) / day;
    if (age <= 30) recent += 1;
    else if (age <= 60) prior += 1;
  }
  return recent - prior;
}

function Failure({ error }: { error: Error }) {
  const missing = error instanceof ApiError && error.status === 404;
  return (
    <div className="mx-auto max-w-2xl px-8 py-16">
      <h1 className="text-lg font-semibold text-ink">
        {missing ? "No such Process" : "Could not load this Process"}
      </h1>
      <p className="mt-2 text-sm text-ink-muted">
        {missing
          ? "It may not have existed at the selected point in time — try returning to now."
          : error instanceof ApiError
            ? `${error.status}: ${error.detail}`
            : "No response from the API."}
      </p>
    </div>
  );
}
