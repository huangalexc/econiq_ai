"use client";

/**
 * Asset list (issue #28).
 *
 * Deliberately plain, and deliberately not the entry point. The product is
 * Process-first (ui_concept §2.1); an Asset reached from here has no discovery
 * chain behind it in the reader's head, which is the state this whole system is
 * built to avoid. The chain is on the Asset page, and the route people should
 * arrive by is a Capability.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { ApiError, api } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { humanise } from "@/lib/utils";

export default function AssetsPage() {
  const { asOf } = useAsOf();
  const assets = useQuery({
    queryKey: keyFor(["assets"], { asOf }),
    queryFn: ({ signal }) => api.assets.list({ asOf, query: { limit: 200 }, signal }),
  });

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <h1 className="text-2xl font-semibold text-ink">Assets</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Instruments the graph has found. Each one arrived through a Capability —
        open it to see the chain.
      </p>

      {assets.isPending ? (
        <p className="mt-8 text-sm text-ink-muted">Loading…</p>
      ) : assets.isError ? (
        <p className="mt-8 text-sm text-contradicts">
          {assets.error instanceof ApiError
            ? `${assets.error.status}: ${assets.error.detail}`
            : "No response from the API."}
        </p>
      ) : (assets.data ?? []).length === 0 ? (
        <p className="mt-8 text-sm text-ink-subtle">
          None discovered yet. Assets are found from Capabilities, which are
          found from Bottlenecks.
        </p>
      ) : (
        <ul className="mt-6 divide-y divide-border rounded-panel border border-border bg-surface">
          {assets.data?.map((asset) => (
            <li key={asset.id} className="flex items-baseline gap-3 px-3 py-2">
              <Link
                href={`/assets/${asset.id}`}
                className="text-sm text-ink hover:text-accent"
              >
                {asset.name}
              </Link>
              {asset.identifiers?.ticker ? (
                <span className="font-mono text-xs text-ink-muted">
                  {asset.identifiers.ticker}
                </span>
              ) : null}
              <span className="ml-auto text-xs text-ink-subtle">
                {humanise(asset.asset_class)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
