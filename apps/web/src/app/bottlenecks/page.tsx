"use client";

/**
 * Bottleneck list (issue #27, ui_concept §10).
 *
 * Binding constraints first, and the sort is the argument: §10 says the
 * Bottleneck layer "is often more actionable than the Process itself", and what
 * makes one actionable is that it binds *now* and will not clear on its own.
 * So the default order is binding-first, then by how inelastic supply is —
 * a constraint that resolves itself is a worse thing to own than one that does
 * not.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { ApiError, api } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

export default function BottlenecksPage() {
  const { asOf } = useAsOf();
  const [bindingOnly, setBindingOnly] = useState(false);

  const bottlenecks = useQuery({
    queryKey: keyFor(["bottlenecks"], { asOf, query: { binding_only: bindingOnly } }),
    queryFn: ({ signal }) =>
      api.bottlenecks.list({
        asOf,
        query: { binding_only: bindingOnly || null, limit: 100 },
        signal,
      }),
  });

  const rows = [...(bottlenecks.data ?? [])].sort(
    (a, b) =>
      Number(b.currently_binding) - Number(a.currently_binding) ||
      (a.supply_elasticity ?? 10) - (b.supply_elasticity ?? 10),
  );

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Bottlenecks</h1>
          <p className="mt-1 text-sm text-ink-muted">
            What prevents each Process from scaling. Binding first, then by how
            slowly supply responds.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          <input
            type="checkbox"
            checked={bindingOnly}
            onChange={(event) => setBindingOnly(event.target.checked)}
          />
          Binding now only
        </label>
      </div>

      {bottlenecks.isPending ? (
        <p className="mt-8 text-sm text-ink-muted">Loading…</p>
      ) : bottlenecks.isError ? (
        <p className="mt-8 text-sm text-contradicts">
          {bottlenecks.error instanceof ApiError
            ? `${bottlenecks.error.status}: ${bottlenecks.error.detail}`
            : "No response from the API."}
        </p>
      ) : rows.length === 0 ? (
        <p className="mt-8 text-sm text-ink-subtle">
          None identified yet. Bottlenecks are found from Processes, so this
          fills in as the pipeline runs.
        </p>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-panel border border-border bg-surface">
          <table className="w-full min-w-[44rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-subtle">
                <th className="px-4 py-2 font-medium">Constraint</th>
                <th className="px-4 py-2 font-medium">Kind</th>
                <th className="px-4 py-2 text-right font-medium">Demand</th>
                <th
                  className="px-4 py-2 text-right font-medium"
                  title="Low elasticity means capacity does not appear in response — the constraint is durable"
                >
                  Elasticity
                </th>
                <th className="px-4 py-2 text-right font-medium">Binding</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-2">
                    <Link
                      href={`/bottlenecks/${row.id}`}
                      className="text-ink hover:text-accent"
                    >
                      {row.name}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-ink-muted">{humanise(row.kind)}</td>
                  <td className="px-4 py-2 text-right font-mono text-ink-muted">
                    {row.demand_pressure?.toFixed(1) ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-ink-muted">
                    {row.supply_elasticity?.toFixed(1) ?? "—"}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-2 text-right",
                      row.currently_binding ? "text-contradicts" : "text-ink-subtle",
                    )}
                  >
                    {row.currently_binding ? "yes" : "no"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
