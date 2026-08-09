"use client";

/**
 * Asset comparison matrix (issue #29, ui_concept §13).
 *
 * §13's second sentence is the design constraint: the interface "should allow
 * users to change ranking weights without changing the underlying scores". So
 * the weights live here, in the client, and the API returns no overall score at
 * all — a server-computed overall would be one weighting frozen into the data,
 * and every reader would end up arguing with it instead of adjusting it.
 *
 * **The empty cells are the point.** Five of §8.3's nine analyses have no source
 * in this deployment (#75), and each empty cell says why rather than showing a
 * dash. A dash reads as zero, and a plausible number would be worse still: once
 * a guessed valuation and a measured one are both rendered as numbers, nobody
 * can tell them apart.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { Explain } from "@/components/explain/explain";
import { ApiError, api } from "@/lib/api/client";
import type { Comparison, ComparisonCell, ComparisonColumn } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

export default function ComparisonPage() {
  return (
    <Suspense fallback={null}>
      <ComparisonRoute />
    </Suspense>
  );
}

function ComparisonRoute() {
  const params = useSearchParams();
  const capabilityId = params.get("capability");
  const { asOf } = useAsOf();
  const [weights, setWeights] = useState<Record<string, number>>({});

  const comparison = useQuery({
    queryKey: keyFor(["comparison", capabilityId ?? ""], { asOf }),
    queryFn: ({ signal }) =>
      api.comparison({ asOf, query: { capability_id: capabilityId }, signal }),
    enabled: Boolean(capabilityId),
  });

  if (!capabilityId) {
    return (
      <div className="mx-auto max-w-2xl px-8 py-16">
        <h1 className="text-lg font-semibold text-ink">Asset comparison</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Open this from a Capability. §13 compares Assets as expressions of one
          Capability, so there is nothing to compare without one — the same
          company is a strong expression of one and a weak expression of another.
        </p>
        <Link
          href="/capabilities"
          className="mt-3 inline-block text-sm text-accent hover:underline"
        >
          Browse Capabilities
        </Link>
      </div>
    );
  }

  if (comparison.isPending) {
    return <p className="px-8 py-10 text-sm text-ink-muted">Loading…</p>;
  }
  if (comparison.isError) {
    return (
      <p className="px-8 py-10 text-sm text-contradicts">
        {comparison.error instanceof ApiError
          ? `${comparison.error.status}: ${comparison.error.detail}`
          : "No response from the API."}
      </p>
    );
  }

  const data = comparison.data;
  const scoredDimensions = (data.dimensions ?? []).filter((dimension) =>
    (data.columns ?? []).some(
      (column) =>
        (column.cells ?? []).find((cell) => cell.dimension === dimension)?.value != null,
    ),
  );

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <h1 className="text-2xl font-semibold text-ink">
        Comparing expressions of {data.capability.label}
      </h1>
      <p className="mt-1 text-sm text-ink-muted">
        Weights are yours and change the ranking only. The underlying scores do
        not move.
      </p>

      {(data.columns ?? []).length === 0 ? (
        <p className="mt-8 text-sm text-ink-subtle">
          No Asset expresses this Capability yet.
        </p>
      ) : (
        <>
          <Weights
            dimensions={scoredDimensions}
            weights={weights}
            onChange={setWeights}
          />
          <Matrix data={data} weights={weights} scored={scoredDimensions} />
        </>
      )}

      <section className="mt-10 rounded-panel border border-border bg-surface p-4">
        <h2 className="text-xs uppercase tracking-wider text-ink-subtle">
          Analyses this deployment cannot source
        </h2>
        <dl className="mt-2 space-y-1.5 text-xs">
          {(data.unavailable ?? []).map((item) => (
            <div key={item.name} className="grid grid-cols-[10rem_1fr] gap-3">
              <dt className="text-ink">{humanise(item.name)}</dt>
              <dd className="text-ink-muted">{item.reason}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

function Weights({
  dimensions,
  weights,
  onChange,
}: {
  dimensions: string[];
  weights: Record<string, number>;
  onChange: (next: Record<string, number>) => void;
}) {
  if (dimensions.length === 0) return null;
  return (
    <div className="mt-6 flex flex-wrap items-end gap-4 rounded-panel border border-border bg-surface px-4 py-3">
      <span className="text-xs uppercase tracking-wider text-ink-subtle">
        Ranking weights
      </span>
      {dimensions.map((dimension) => (
        <label key={dimension} className="flex flex-col gap-1 text-xs text-ink-muted">
          {humanise(dimension)}
          <input
            type="range"
            min={0}
            max={3}
            step={0.5}
            value={weights[dimension] ?? 1}
            onChange={(event) =>
              onChange({ ...weights, [dimension]: Number(event.target.value) })
            }
          />
        </label>
      ))}
      <button
        type="button"
        onClick={() => onChange({})}
        className="ml-auto pb-1 text-xs text-ink-subtle underline underline-offset-2 hover:text-ink"
      >
        Reset
      </button>
    </div>
  );
}

function Matrix({
  data,
  weights,
  scored,
}: {
  data: Comparison;
  weights: Record<string, number>;
  scored: string[];
}) {
  const ranked = [...(data.columns ?? [])]
    .map((column) => {
      // Weighted mean over the dimensions this Asset actually has, so an Asset
      // missing a score is not penalised for the gap — it is ranked on what is
      // known about it, and the coverage count says how much that is.
      let total = 0;
      let weight = 0;
      for (const dimension of scored) {
        const cell = (column.cells ?? []).find((c) => c.dimension === dimension);
        if (cell?.value == null) continue;
        const w = weights[dimension] ?? 1;
        total += cell.value * w;
        weight += w;
      }
      const covered = (column.cells ?? []).filter((c) => c.value != null).length;
      return { column, score: weight > 0 ? total / weight : null, covered };
    })
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));

  return (
    <div className="mt-4 overflow-x-auto rounded-panel border border-border bg-surface">
      <table className="w-full min-w-[48rem] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-subtle">
            <th className="px-4 py-2 font-medium">Dimension</th>
            {ranked.map(({ column }) => (
              <th key={column.asset.id} className="px-4 py-2 font-medium">
                <Link
                  href={`/assets/${column.asset.id}`}
                  className="text-ink hover:text-accent"
                >
                  {column.asset.label}
                </Link>
                {column.ticker ? (
                  <span className="ml-1 font-mono text-ink-subtle">
                    {column.ticker}
                  </span>
                ) : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-border bg-surface-raised/40">
            <th scope="row" className="px-4 py-2 text-left font-medium text-ink-muted">
              Exposure magnitude
            </th>
            {ranked.map(({ column }) => (
              <td key={column.asset.id} className="px-4 py-2 font-mono text-ink">
                {column.exposure_magnitude?.toFixed(1) ?? "—"}
              </td>
            ))}
          </tr>

          {(data.dimensions ?? []).map((dimension) => (
            <tr key={dimension} className="border-b border-border">
              <th scope="row" className="px-4 py-2 text-left font-normal text-ink-muted">
                {humanise(dimension)}
              </th>
              {ranked.map(({ column }) => {
                const cell = (column.cells ?? []).find((c) => c.dimension === dimension);
                return (
                  <td key={column.asset.id} className="px-4 py-2 align-top">
                    <Cell cell={cell} provenance={column.provenance ?? null} />
                  </td>
                );
              })}
            </tr>
          ))}

          <tr className="bg-surface-raised/40">
            <th scope="row" className="px-4 py-2 text-left font-medium text-ink">
              Weighted rank
              <span className="ml-1 text-[0.625rem] font-normal uppercase tracking-wider text-ink-subtle">
                yours
              </span>
            </th>
            {ranked.map(({ column, score, covered }) => (
              <td key={column.asset.id} className="px-4 py-2">
                <span className="font-mono text-ink">
                  {score == null ? "—" : score.toFixed(2)}
                </span>
                <span className="ml-2 text-[0.625rem] text-ink-subtle">
                  {covered} scored
                </span>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function Cell({
  cell,
  provenance,
}: {
  cell: ComparisonCell | undefined;
  provenance: ComparisonColumn["provenance"] | null;
}) {
  if (!cell || cell.value == null) {
    return (
      <span
        className="text-xs text-ink-subtle"
        title={cell?.unavailable_reason ?? "Not scored."}
      >
        not sourced
      </span>
    );
  }
  return (
    <div>
      <span className={cn("font-mono text-ink")}>{cell.value.toFixed(1)}</span>
      <Explain
        label="why"
        explanation={{
          conclusion: humanise(cell.dimension),
          value: `${cell.value.toFixed(1)} / 10`,
          confidence: cell.confidence ?? null,
          rationale: cell.rationale,
          supporting: Object.entries(cell.inputs ?? {}).map(([label, value]) => ({
            label: humanise(label),
            value: String(value),
          })),
          contradicting: [],
          provenance: provenance ?? null,
        }}
      />
    </div>
  );
}
