"use client";

import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn } from "@/lib/utils";

/**
 * Connection and pipeline status.
 *
 * Deliberately real rather than a stub. A typed client that nothing calls is a
 * client nobody has proven, and this is the cheapest screen that exercises the
 * whole path — generated types, the fetch wrapper, TanStack Query, and the
 * error state — against the running API.
 *
 * The full System Performance dashboard (ui_concept §24) is #24; this is the
 * shell's own readout, not that.
 */
export default function SystemPage() {
  const { asOf } = useAsOf();

  const health = useQuery({
    queryKey: keyFor(["health"]),
    queryFn: ({ signal }) => api.health({ signal }),
  });

  const pipeline = useQuery({
    queryKey: keyFor(["pipeline"], { asOf }),
    queryFn: ({ signal }) => api.pipeline.stages({ asOf, signal }),
  });

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <h1 className="text-2xl font-semibold text-ink">System</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Read through the generated API client. If this screen works, every other
        screen&rsquo;s data path works.
      </p>

      <section className="mt-8">
        <h2 className="text-sm font-medium uppercase tracking-wider text-ink-subtle">
          API
        </h2>
        <div className="mt-3 rounded-panel border border-border bg-surface p-4">
          {health.isPending ? (
            <p className="text-sm text-ink-muted">Checking…</p>
          ) : health.isError ? (
            <Unreachable error={health.error} />
          ) : (
            <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
              <dt className="text-ink-subtle">Status</dt>
              <dd className="text-supports">{health.data.status}</dd>
              <dt className="text-ink-subtle">Database</dt>
              <dd className="text-ink">
                {health.data.database ? "connected" : "unreachable"}
              </dd>
              <dt className="text-ink-subtle">Schema</dt>
              {/* An API one migration behind fails like a data problem, so the
                  migration is on the health screen rather than in a log. */}
              <dd className="font-mono text-xs text-ink-muted">
                {health.data.schema_version ?? "unknown"}
              </dd>
            </dl>
          )}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-medium uppercase tracking-wider text-ink-subtle">
          Pipeline stages
        </h2>
        <div className="mt-3 overflow-x-auto rounded-panel border border-border bg-surface">
          {pipeline.isPending ? (
            <p className="p-4 text-sm text-ink-muted">Loading…</p>
          ) : pipeline.isError ? (
            <div className="p-4">
              <Unreachable error={pipeline.error} />
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-subtle">
                  <th className="px-4 py-2 font-medium">Stage</th>
                  <th className="px-4 py-2 font-medium">Triggered by</th>
                  <th className="px-4 py-2 font-medium">Priority</th>
                  <th className="px-4 py-2 font-medium">Handler</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(pipeline.data).map(([name, stage]) => (
                  <tr key={name} className="border-b border-border last:border-0">
                    <td className="px-4 py-2 font-mono text-xs text-ink">{name}</td>
                    <td className="px-4 py-2 text-ink-muted">
                      {stage.triggered_by.join(", ") || "—"}
                    </td>
                    <td className="px-4 py-2 text-ink-muted">{stage.priority}</td>
                    <td
                      className={cn(
                        "px-4 py-2",
                        stage.has_handler ? "text-supports" : "text-ink-subtle",
                      )}
                    >
                      {stage.has_handler ? "registered" : "none in this process"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}

function Unreachable({ error }: { error: Error }) {
  const detail =
    error instanceof ApiError
      ? `${error.status}: ${error.detail}`
      : "no response — is the API running?";
  return (
    <div className="text-sm">
      <p className="text-contradicts">Could not read the API.</p>
      <p className="mt-1 text-ink-muted">{detail}</p>
      <p className="mt-2 font-mono text-xs text-ink-subtle">
        uv run uvicorn econiq_api.main:app --reload
      </p>
    </div>
  );
}
