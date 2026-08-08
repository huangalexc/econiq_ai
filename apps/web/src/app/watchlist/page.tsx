"use client";

/**
 * Watchlist (issues #19, #32).
 *
 * The one screen in the terminal that shows data belonging to a person rather
 * than to the graph. Everything else is readable signed out, which is PRD §23's
 * distinction and the reason this page — not the Process screen — is the one
 * that asks for a session.
 *
 * Alerts here are the same derivation the public feed uses, narrowed to what
 * this workspace watches. That is the filter #32 always wanted and could not
 * have until there was a workspace to hang it on.
 */

import { SignInButton, useAuth } from "@clerk/nextjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { ApiError, api } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

const HREF: Record<string, string> = {
  process: "/processes",
  bottleneck: "/bottlenecks",
  capability: "/capabilities",
  asset: "/assets",
};

export default function WatchlistPage() {
  const { isLoaded, isSignedIn } = useAuth();
  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <h1 className="text-2xl font-semibold text-ink">Watchlist</h1>
      <p className="mt-1 text-sm text-ink-muted">
        What you are following, and what changed about it. Watching is an
        opinion about relevance — the objects themselves are shared.
      </p>

      {isLoaded && !isSignedIn ? (
        <div className="mt-8 rounded-panel border border-border bg-surface p-6">
          <p className="text-sm text-ink">
            A watchlist belongs to a workspace, so this is the one screen that
            needs a session.
          </p>
          <p className="mt-2 text-sm text-ink-muted">
            Everything else — Processes, Capabilities, Assets, the graph — stays
            readable signed out. The research graph is shared by design.
          </p>
          <SignInButton mode="modal">
            <button
              type="button"
              className="mt-4 rounded border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent/10"
            >
              Sign in
            </button>
          </SignInButton>
        </div>
      ) : null}

      {isSignedIn ? <Watched /> : null}
    </div>
  );
}

function Watched() {
  const { asOf } = useAsOf();
  const queryClient = useQueryClient();

  const watchlist = useQuery({
    queryKey: keyFor(["watchlist"], { asOf }),
    queryFn: ({ signal }) => api.workspace.watchlist({ signal }),
  });
  const alerts = useQuery({
    queryKey: keyFor(["watchlist-alerts"], { asOf }),
    queryFn: ({ signal }) => api.workspace.alerts({ asOf, signal }),
  });

  const unwatch = useMutation({
    mutationFn: (nodeId: string) => api.workspace.unwatch(nodeId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["watchlist"] });
      void queryClient.invalidateQueries({ queryKey: ["watchlist-alerts"] });
    },
  });

  if (watchlist.isPending) {
    return <p className="mt-8 text-sm text-ink-muted">Loading…</p>;
  }
  if (watchlist.isError) {
    return (
      <p className="mt-8 text-sm text-contradicts">
        {watchlist.error instanceof ApiError
          ? `${watchlist.error.status}: ${watchlist.error.detail}`
          : "No response from the API."}
      </p>
    );
  }

  const items = watchlist.data ?? [];

  return (
    <>
      {(alerts.data ?? []).length > 0 ? (
        <section className="mt-8">
          <h2 className="text-sm font-medium uppercase tracking-wider text-ink-subtle">
            Changed recently
          </h2>
          <ul className="mt-3 divide-y divide-border rounded-panel border border-border bg-surface">
            {alerts.data?.map((alert) => (
              <li key={alert.id} className="px-3 py-2">
                <span
                  className={cn(
                    "mr-2 rounded border px-1 text-[0.625rem] uppercase tracking-wider",
                    alert.severity === "urgent"
                      ? "border-contradicts text-contradicts"
                      : "border-border text-ink-subtle",
                  )}
                >
                  {alert.severity}
                </span>
                <Link
                  href={`/processes/${alert.subject.id}`}
                  className="text-sm text-ink hover:text-accent"
                >
                  {alert.headline}
                </Link>
                <p className="mt-0.5 text-xs text-ink-muted">{alert.detail}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mt-8">
        <h2 className="text-sm font-medium uppercase tracking-wider text-ink-subtle">
          Following
        </h2>
        {items.length === 0 ? (
          <p className="mt-3 text-sm text-ink-subtle">
            Nothing yet. Open a Process and choose Track.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-border rounded-panel border border-border bg-surface">
            {items.map((item) => (
              <li key={item.id} className="flex items-baseline gap-3 px-3 py-2">
                <span className="text-[0.5625rem] uppercase tracking-wider text-ink-subtle">
                  {humanise(item.node.type)}
                </span>
                <Link
                  href={`${HREF[item.node.type] ?? "/processes"}/${item.node.id}`}
                  className="text-sm text-ink hover:text-accent"
                >
                  {item.node.label}
                </Link>
                {item.note ? (
                  <span className="text-xs text-ink-muted">{item.note}</span>
                ) : null}
                <button
                  type="button"
                  onClick={() => unwatch.mutate(item.node.id)}
                  className="ml-auto text-xs text-ink-subtle hover:text-contradicts"
                >
                  Stop watching
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
