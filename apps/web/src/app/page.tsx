"use client";

/**
 * Discover (issue #21, ui_concept §5).
 *
 * Answers "what is changing in the economic state space?" — not "how is my
 * portfolio doing". §5 is explicit that this is not primarily a dashboard, and
 * the ordering of the page follows: the ranked panel first for scanning, hot
 * cards second for the few that survive the scan, and no positions anywhere.
 *
 * The Emergence Radar (§5.2) is #22 and is not here yet.
 */

import { useQuery } from "@tanstack/react-query";

import { EmergingPanel } from "@/components/discover/emerging-panel";
import { HotCard } from "@/components/discover/hot-card";
import { Screener, useScreener } from "@/components/discover/screener";
import { ApiError, api } from "@/lib/api/client";
import type { DiscoverFeed } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";

export default function DiscoverPage() {
  const { asOf } = useAsOf();
  const [filters] = useScreener();

  const query = {
    archetype: filters.archetype,
    min_state_confidence: filters.minStateConfidence,
    min_assets: filters.minAssets,
    min_capabilities: filters.minCapabilities,
    accelerating_only: filters.acceleratingOnly || null,
    limit: 50,
  };

  const feed = useQuery({
    queryKey: keyFor(["discover"], { asOf, query }),
    queryFn: ({ signal }) => api.discover({ asOf, query, signal }),
  });

  return (
    <div className="mx-auto max-w-7xl px-8 py-8">
      <header>
        <h1 className="text-2xl font-semibold text-ink">Discover</h1>
        <p className="mt-1 text-sm text-ink-muted">
          What is changing in the economic state space. Ranked by how much the
          evidence moved — a discovery ordering, not a forecast.
        </p>
      </header>

      <div className="mt-6">
        <Screener />
      </div>

      {feed.isPending ? (
        <p className="mt-8 text-sm text-ink-muted">Ranking…</p>
      ) : feed.isError ? (
        <FeedError error={feed.error} />
      ) : feed.data.processes && feed.data.processes.length > 0 ? (
        <>
          <section className="mt-6">
            <h2 className="sr-only">Emerging Processes</h2>
            <EmergingPanel processes={feed.data.processes} />
          </section>

          <section className="mt-8">
            <h2 className="text-sm font-medium uppercase tracking-wider text-ink-subtle">
              Hot Processes
            </h2>
            <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {feed.data.processes.slice(0, 6).map((process) => (
                <HotCard key={process.id} process={process} />
              ))}
            </div>
          </section>

          <RankingLimits feed={feed.data} />
        </>
      ) : (
        <Empty filtered={hasFilters(filters)} />
      )}
    </div>
  );
}

function hasFilters(filters: ReturnType<typeof useScreener>[0]): boolean {
  return (
    filters.archetype !== null ||
    filters.minStateConfidence !== null ||
    filters.minAssets !== null ||
    filters.minCapabilities !== null ||
    filters.acceleratingOnly
  );
}

/**
 * The ranking's own limits, on the screen that uses it.
 *
 * The API returns which §5.1 inputs it could not compute, and this renders
 * them. A ranking that quietly drops two of its eight stated inputs is a
 * different ranking wearing the same name, and the person reading the order has
 * the most reason to know that.
 */
function RankingLimits({ feed }: { feed: DiscoverFeed }) {
  const missing = feed.unavailable_inputs ?? [];
  if (missing.length === 0) return null;

  return (
    <section className="mt-10 rounded-panel border border-border bg-surface p-4">
      <h2 className="text-xs uppercase tracking-wider text-ink-subtle">
        What this ranking does not include
      </h2>
      <dl className="mt-2 space-y-2 text-xs">
        {missing.map((item) => (
          <div key={item.name}>
            <dt className="text-ink">{item.name}</dt>
            <dd className="text-ink-muted">{item.reason}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-ink-subtle">
        Trailing window: {feed.window_days} days.
      </p>
    </section>
  );
}

function Empty({ filtered }: { filtered: boolean }) {
  return (
    <div className="mt-12 rounded-panel border border-border bg-surface p-8 text-center">
      <p className="text-sm text-ink">
        {filtered
          ? "No Process matches these filters."
          : "No Processes have been discovered yet."}
      </p>
      <p className="mt-2 text-sm text-ink-muted">
        {filtered
          ? "Loosen a filter, or clear them to see the full ranking."
          : "Run the ingestion pipeline to populate the graph — this screen ranks what the agents found, and finds nothing on its own."}
      </p>
    </div>
  );
}

function FeedError({ error }: { error: Error }) {
  const detail =
    error instanceof ApiError
      ? `${error.status}: ${error.detail}`
      : "no response — is the API running?";
  return (
    <div className="mt-8 rounded-panel border border-border bg-surface p-6">
      <p className="text-sm text-contradicts">Could not load the feed.</p>
      <p className="mt-1 text-sm text-ink-muted">{detail}</p>
    </div>
  );
}
