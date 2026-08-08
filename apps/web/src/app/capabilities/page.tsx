"use client";

/**
 * Capability explorer and confluence search (issue #27, ui_concept §11).
 *
 * §11 calls Capabilities "the bridge between economic Processes and investable
 * Assets", and the confluence search is the reason this screen is not just a
 * list: selecting several Processes and finding what they *all* need is an AND,
 * and §11 is explicit that this "supports AND relationships rather than forcing
 * everything into OR-style exposure".
 *
 * The distinction is the whole feature. A union of Capabilities relevant to any
 * of three theses is a long list of things one thesis needs. The intersection is
 * short, and everything in it is needed by three independent arguments — which
 * is what makes it worth owning.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn } from "@/lib/utils";

export default function CapabilitiesPage() {
  const { asOf } = useAsOf();
  const [selected, setSelected] = useState<string[]>([]);
  const [requireAll, setRequireAll] = useState(true);

  const capabilities = useQuery({
    queryKey: keyFor(["capabilities"], { asOf }),
    queryFn: ({ signal }) => api.capabilities.list({ asOf, signal }),
  });
  const processes = useQuery({
    queryKey: keyFor(["processes"], { asOf }),
    queryFn: ({ signal }) => api.processes.list({ asOf, query: { limit: 100 }, signal }),
  });

  const confluence = useQuery({
    queryKey: keyFor(["confluence"], {
      asOf,
      query: { process_id: selected, require_all: requireAll },
    }),
    queryFn: ({ signal }) =>
      api.confluence({
        asOf,
        query: { process_id: selected, require_all: requireAll },
        signal,
      }),
    enabled: selected.length > 0,
  });

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <h1 className="text-2xl font-semibold text-ink">Capabilities</h1>
      <p className="mt-1 text-sm text-ink-muted">
        The bridge between a Process and something investable. Select several
        Processes to find what they all require.
      </p>

      <section className="mt-8">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium uppercase tracking-wider text-ink-subtle">
            Confluence search
          </h2>
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              checked={requireAll}
              onChange={(event) => setRequireAll(event.target.checked)}
            />
            Require all selected (AND)
          </label>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {(processes.data ?? []).map((process) => {
            const on = selected.includes(process.id);
            return (
              <button
                key={process.id}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  setSelected((current) =>
                    current.includes(process.id)
                      ? current.filter((id) => id !== process.id)
                      : [...current, process.id],
                  )
                }
                className={cn(
                  "rounded border px-2 py-1 text-xs",
                  on
                    ? "border-accent text-accent"
                    : "border-border text-ink-muted hover:text-ink",
                )}
              >
                {process.name}
              </button>
            );
          })}
        </div>

        {selected.length === 0 ? (
          <p className="mt-4 text-sm text-ink-subtle">
            Select at least one Process.
          </p>
        ) : confluence.isPending ? (
          <p className="mt-4 text-sm text-ink-muted">Searching…</p>
        ) : (confluence.data?.capabilities ?? []).length === 0 ? (
          <p className="mt-4 text-sm text-ink-muted">
            {requireAll && selected.length > 1
              ? "No Capability is required by all of these. That is a finding: these theses do not converge."
              : "No Capability is reachable from this selection."}
          </p>
        ) : (
          <ul className="mt-4 space-y-2">
            {confluence.data?.capabilities?.map((hit) => (
              <li
                key={hit.capability.id}
                className="flex items-baseline justify-between gap-4 rounded-panel border border-border bg-surface px-3 py-2"
              >
                <Link
                  href={`/capabilities/${hit.capability.id}`}
                  className="text-sm text-ink hover:text-accent"
                >
                  {hit.capability.label}
                </Link>
                <span className="shrink-0 text-xs text-ink-subtle">
                  needed by {hit.reached_by} of {selected.length} ·{" "}
                  <span className={hit.asset_count > 0 ? "text-supports" : undefined}>
                    {hit.asset_count} asset{hit.asset_count === 1 ? "" : "s"}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-medium uppercase tracking-wider text-ink-subtle">
          All Capabilities
        </h2>
        {capabilities.isPending ? (
          <p className="mt-3 text-sm text-ink-muted">Loading…</p>
        ) : (capabilities.data ?? []).length === 0 ? (
          <p className="mt-3 text-sm text-ink-subtle">
            None mapped yet. Capabilities come from Bottlenecks, which come from
            Processes.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-border rounded-panel border border-border bg-surface">
            {capabilities.data?.map((capability) => (
              <li key={capability.id} className="px-3 py-2">
                <Link
                  href={`/capabilities/${capability.id}`}
                  className="text-sm text-ink hover:text-accent"
                >
                  {capability.name}
                </Link>
                <p className="mt-0.5 text-xs text-ink-muted">
                  {capability.description}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
