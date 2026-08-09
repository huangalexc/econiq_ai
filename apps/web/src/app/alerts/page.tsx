"use client";

/**
 * Notification centre (issue #32, ui_concept §19, §26; PRD §20).
 *
 * Monitoring that watches thesis integrity rather than price. §19's example
 * copy is "Bottleneck potentially resolving: …", not "XYZ down 5%", and the
 * difference is not stylistic — a feed that mixes the two trains the reader to
 * skim both, and the one worth reading is the one that gets skimmed.
 *
 * Grouped by semantic class (§26) rather than sorted purely by time, because
 * the question this screen answers is "what kind of thing changed", and six
 * contradicting-evidence alerts read as one situation while six alerts of six
 * kinds read as six.
 *
 * There is no watchlist filter yet: watchlists need users (#19). Until then the
 * feed is the whole graph, which is the right default for one analyst.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { ApiError, api } from "@/lib/api/client";
import type { Alert } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

const SEVERITY_ORDER = ["urgent", "notable", "informational"] as const;

const SEVERITY_STYLE: Record<string, string> = {
  urgent: "border-contradicts text-contradicts",
  notable: "border-needs-review text-needs-review",
  informational: "border-border text-ink-subtle",
};

export default function AlertsPage() {
  const { asOf } = useAsOf();
  const [windowDays, setWindowDays] = useState(14);

  const alerts = useQuery({
    queryKey: keyFor(["alerts"], { asOf, query: { window_days: windowDays } }),
    queryFn: ({ signal }) =>
      api.alerts({ asOf, query: { window_days: windowDays, limit: 200 }, signal }),
  });

  const grouped = new Map<string, Alert[]>();
  for (const alert of alerts.data ?? []) {
    const bucket = grouped.get(alert.kind);
    if (bucket) bucket.push(alert);
    else grouped.set(alert.kind, [alert]);
  }
  const kinds = [...grouped.entries()].sort(
    (a, b) =>
      SEVERITY_ORDER.indexOf(a[1][0].severity as (typeof SEVERITY_ORDER)[number]) -
        SEVERITY_ORDER.indexOf(b[1][0].severity as (typeof SEVERITY_ORDER)[number]) ||
      b[1].length - a[1].length,
  );

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Alerts</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Changes to the thesis, not to the price.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          Window
          <select
            value={windowDays}
            onChange={(event) => setWindowDays(Number(event.target.value))}
            className="rounded border border-border bg-surface-raised px-2 py-1 text-xs text-ink"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </label>
      </div>

      {alerts.isPending ? (
        <p className="mt-8 text-sm text-ink-muted">Loading…</p>
      ) : alerts.isError ? (
        <p className="mt-8 text-sm text-contradicts">
          {alerts.error instanceof ApiError
            ? `${alerts.error.status}: ${alerts.error.detail}`
            : "No response from the API."}
        </p>
      ) : kinds.length === 0 ? (
        <p className="mt-8 text-sm text-ink-subtle">
          Nothing changed in this window. That is a finding, not an empty screen
          — no State moved, no evidence arrived against anything, and no
          constraint appeared or cleared.
        </p>
      ) : (
        <div className="mt-6 space-y-8">
          {kinds.map(([kind, group]) => (
            <section key={kind}>
              <h2 className="text-sm font-medium uppercase tracking-wider text-ink-subtle">
                {humanise(kind)}{" "}
                <span className="text-ink-subtle">({group.length})</span>
              </h2>
              <ul className="mt-2 divide-y divide-border rounded-panel border border-border bg-surface">
                {group.map((alert) => (
                  <li key={alert.id} className="px-3 py-2.5">
                    <div className="flex items-baseline gap-2">
                      <span
                        className={cn(
                          "shrink-0 rounded border px-1 text-[0.625rem] uppercase tracking-wider",
                          SEVERITY_STYLE[alert.severity] ?? SEVERITY_STYLE.informational,
                        )}
                      >
                        {alert.severity}
                      </span>
                      <Link
                        href={`/processes/${alert.subject.id}`}
                        className="min-w-0 text-sm text-ink hover:text-accent"
                      >
                        {alert.headline}
                      </Link>
                      <time
                        dateTime={alert.observed_at}
                        className="ml-auto shrink-0 text-xs text-ink-subtle"
                      >
                        {alert.observed_at.slice(0, 10)}
                      </time>
                    </div>
                    <p className="mt-1 text-xs text-ink-muted">{alert.detail}</p>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <p className="mt-10 text-xs text-ink-subtle">
        Alerts are derived when this screen is read rather than stored, so a
        past <code>as_of</code> shows the alerts that existed then, and an alert
        whose change was later superseded stops existing rather than lingering.
        Watchlist filtering arrives with users (#19).
      </p>
    </div>
  );
}
