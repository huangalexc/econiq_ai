"use client";

/**
 * Capability detail (issue #27, ui_concept §11).
 *
 * Three lists, in the order §11 gives them: the Processes upstream, the
 * Bottlenecks that require it, and the Assets that express it. The order is the
 * argument — a Capability is only interesting because something needs it, and
 * only investable because something expresses it.
 *
 * Upstream Processes come from the graph rather than from a stored count.
 * Confluence is a structural fact (ontology §13), and a cached number would
 * drift the moment an edge changed.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ApiError, api } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";

export default function CapabilityPage() {
  const { id } = useParams<{ id: string }>();
  const { asOf } = useAsOf();

  const capability = useQuery({
    queryKey: keyFor(["capability", id], { asOf }),
    queryFn: ({ signal }) => api.capabilities.get(id, { asOf, signal }),
  });

  if (capability.isPending) {
    return <p className="px-8 py-10 text-sm text-ink-muted">Loading…</p>;
  }
  if (capability.isError) {
    return (
      <div className="mx-auto max-w-2xl px-8 py-16">
        <h1 className="text-lg font-semibold text-ink">Could not load</h1>
        <p className="mt-2 text-sm text-ink-muted">
          {capability.error instanceof ApiError
            ? `${capability.error.status}: ${capability.error.detail}`
            : "No response from the API."}
        </p>
      </div>
    );
  }

  const row = capability.data;
  const upstream = row.upstream_processes ?? [];
  const assets = row.expressed_by ?? [];

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <p className="text-xs uppercase tracking-wider text-ink-subtle">Capability</p>
      <h1 className="mt-1 text-2xl font-semibold text-ink">{row.name}</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink-muted">{row.description}</p>
      {(row.aliases ?? []).length > 0 ? (
        <p className="mt-1 text-xs text-ink-subtle">
          also: {row.aliases?.join(", ")}
        </p>
      ) : null}
      <Link
        href={`/graph?node=${row.id}`}
        className="mt-3 inline-block text-xs text-accent hover:underline"
      >
        View in graph
      </Link>

      <div className="mt-8 grid gap-8 md:grid-cols-2">
        <section>
          <h2 className="text-sm font-medium text-ink">Upstream Processes</h2>
          {/* The confluence signal. Several *independent* Processes needing one
              Capability is ontology §13's whole point, so the count is said
              plainly rather than left to be counted off a list. */}
          <p className="mt-1 text-xs text-ink-muted">
            {upstream.length === 0
              ? "Nothing requires this yet."
              : upstream.length === 1
                ? "One Process requires this."
                : `${upstream.length} independent Processes require this — a confluence.`}
          </p>
          <ul className="mt-2 space-y-1">
            {upstream.map((node) => (
              <li key={node.id}>
                <Link
                  href={`/processes/${node.id}`}
                  className="text-sm text-ink hover:text-accent"
                >
                  {node.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2 className="text-sm font-medium text-ink">Expressed by</h2>
          <p className="mt-1 text-xs text-ink-muted">
            {assets.length === 0
              ? "No Asset expresses this Capability yet. Until one does, the Capability is a finding rather than a position."
              : `${assets.length} Asset${assets.length === 1 ? "" : "s"}.`}
          </p>
          <ul className="mt-2 space-y-1">
            {assets.map((node) => (
              <li key={node.id}>
                <Link
                  href={`/assets/${node.id}`}
                  className="text-sm text-ink hover:text-accent"
                >
                  {node.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
