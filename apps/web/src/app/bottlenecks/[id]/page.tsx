"use client";

/**
 * Bottleneck page (issue #27, ui_concept §10).
 *
 * §10 ends with the sentence that justifies this screen existing at all: a
 * Bottleneck page answers "what prevents the Process from scaling?", and that
 * "is often more actionable than the Process itself".
 *
 * The four measures are shown as a bar each rather than as a table of numbers,
 * because their *shape* is the finding. High demand pressure with high supply
 * elasticity is a constraint that will clear on its own; high demand pressure
 * with low elasticity and a long time to expand is one that will not, and that
 * is the case worth owning something for.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { RequirementTree } from "@/components/capability/requirement-tree";
import { api, ApiError } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

const MEASURES = [
  {
    key: "demand_pressure" as const,
    label: "Demand pressure",
    hint: "How hard the Process is pushing against this constraint.",
  },
  {
    key: "supply_elasticity" as const,
    label: "Supply elasticity",
    hint: "How readily capacity appears in response. Low is what makes a constraint durable.",
  },
  {
    key: "time_to_expand" as const,
    label: "Time to expand",
    hint: "How long relief takes once someone tries. High means slow.",
  },
  {
    key: "current_constraint" as const,
    label: "Current constraint",
    hint: "How binding it is right now.",
  },
];

export default function BottleneckPage() {
  const { id } = useParams<{ id: string }>();
  const { asOf } = useAsOf();

  const bottleneck = useQuery({
    queryKey: keyFor(["bottleneck", id], { asOf }),
    queryFn: ({ signal }) => api.bottlenecks.get(id, { asOf, signal }),
  });
  const requirements = useQuery({
    queryKey: keyFor(["requirements", id], { asOf }),
    queryFn: ({ signal }) => api.bottlenecks.requirements(id, { signal }),
    // A Bottleneck can legitimately have no requirement tree mapped yet.
    retry: false,
  });

  if (bottleneck.isPending) {
    return <p className="px-8 py-10 text-sm text-ink-muted">Loading…</p>;
  }
  if (bottleneck.isError) {
    return (
      <div className="mx-auto max-w-2xl px-8 py-16">
        <h1 className="text-lg font-semibold text-ink">Could not load</h1>
        <p className="mt-2 text-sm text-ink-muted">
          {bottleneck.error instanceof ApiError
            ? `${bottleneck.error.status}: ${bottleneck.error.detail}`
            : "No response from the API."}
        </p>
      </div>
    );
  }

  const row = bottleneck.data;

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <p className="text-xs uppercase tracking-wider text-ink-subtle">
        {humanise(row.kind)}
      </p>
      <h1 className="mt-1 text-2xl font-semibold text-ink">{row.name}</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink-muted">{row.description}</p>

      <div className="mt-3 flex items-center gap-3 text-xs">
        <span
          className={cn(
            "rounded border px-1.5 py-0.5",
            row.currently_binding
              ? "border-contradicts text-contradicts"
              : "border-border text-ink-subtle",
          )}
        >
          {row.currently_binding ? "currently binding" : "not currently binding"}
        </span>
        {row.resolved ? (
          <span className="rounded border border-supports px-1.5 py-0.5 text-supports">
            resolved
          </span>
        ) : null}
        <Link
          href={`/processes/${row.process_id}`}
          className="text-accent hover:underline"
        >
          Process
        </Link>
        <Link href={`/graph?node=${row.id}`} className="text-accent hover:underline">
          Graph
        </Link>
      </div>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-ink">Constraint profile</h2>
        <dl className="mt-3 space-y-3">
          {MEASURES.map((measure) => {
            const value = row[measure.key];
            return (
              <div key={measure.key}>
                <div className="flex items-baseline justify-between text-xs">
                  <dt className="text-ink-muted" title={measure.hint}>
                    {measure.label}
                  </dt>
                  <dd className="font-mono text-ink">
                    {value == null ? (
                      <span className="text-ink-subtle">not assessed</span>
                    ) : (
                      value.toFixed(1)
                    )}
                  </dd>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-surface-raised">
                  {value != null ? (
                    <div
                      className="h-1.5 rounded-full bg-accent"
                      style={{ width: `${Math.min(value, 10) * 10}%` }}
                    />
                  ) : null}
                </div>
              </div>
            );
          })}
        </dl>
      </section>

      {(row.relief_indicators ?? []).length > 0 ? (
        <section className="mt-8">
          <h2 className="text-sm font-medium text-ink">What would relieve it</h2>
          {/* The falsifiable half of a Bottleneck: an observation that would
              show the constraint is clearing. Without these the page is an
              opinion about difficulty. */}
          <ul className="mt-2 space-y-1 text-sm text-ink-muted">
            {row.relief_indicators?.map((indicator) => (
              <li key={indicator}>• {indicator}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mt-8">
        <h2 className="text-sm font-medium text-ink">Required Capabilities</h2>
        <p className="mt-1 text-xs text-ink-muted">
          What would have to exist for this constraint to clear. AND and OR
          describe different worlds, so the structure is shown rather than
          flattened to a list.
        </p>
        <div className="mt-3">
          {requirements.isPending ? (
            <p className="text-sm text-ink-muted">Loading…</p>
          ) : requirements.isError ? (
            <p className="text-sm text-ink-subtle">
              No requirement tree has been mapped for this Bottleneck yet.
            </p>
          ) : (
            <RequirementTree node={requirements.data.root} />
          )}
        </div>
      </section>
    </div>
  );
}
