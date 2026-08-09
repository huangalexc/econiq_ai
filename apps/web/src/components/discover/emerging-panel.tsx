"use client";

/**
 * The emerging-Process panel (ui_concept §5.1).
 *
 * A ranked table, deliberately dense: this is the screen someone scans for
 * thirty seconds to answer "what moved?", and cards do not scan. The hot cards
 * below it are for the handful that survive that scan.
 */

import Link from "next/link";

import type { EmergingProcess } from "@/lib/api/client";
import { confidenceClass, humanise } from "@/lib/utils";

export function EmergingPanel({ processes }: { processes: EmergingProcess[] }) {
  return (
    <div className="overflow-x-auto rounded-panel border border-border bg-surface">
      <table className="w-full min-w-[52rem] text-sm">
        <caption className="sr-only">
          Processes ranked by evidence movement. A discovery ranking, not a
          forecast.
        </caption>
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-ink-subtle">
            <th scope="col" className="px-4 py-2 font-medium">
              Process
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              State
            </th>
            <th scope="col" className="px-4 py-2 text-right font-medium">
              Evidence Δ
            </th>
            <th scope="col" className="px-4 py-2 text-right font-medium">
              Confidence
            </th>
            <th scope="col" className="px-4 py-2 text-right font-medium">
              Against
            </th>
            <th
              scope="col"
              className="px-4 py-2 text-right font-medium"
              title="Distinct publishers — media coverage, not market attention"
            >
              Sources
            </th>
            <th scope="col" className="px-4 py-2 text-right font-medium">
              Assets
            </th>
            <th scope="col" className="px-4 py-2 text-right font-medium">
              Rank
            </th>
          </tr>
        </thead>
        <tbody>
          {processes.map((process) => {
            const delta = process.evidence_delta ?? 0;
            return (
              <tr
                key={process.id}
                className="border-b border-border last:border-0 hover:bg-surface-raised"
              >
                <td className="px-4 py-2">
                  <Link
                    href={`/processes/${process.id}`}
                    className="text-ink hover:text-accent"
                  >
                    {process.name}
                  </Link>
                  {process.requires_review ? (
                    <span
                      className="ml-2 rounded border border-needs-review px-1 text-[0.625rem] text-needs-review"
                      title="Flagged for human review before it is relied on"
                    >
                      review
                    </span>
                  ) : null}
                </td>
                <td className="px-4 py-2 text-ink-muted">
                  {process.current_state ? humanise(process.current_state) : "—"}
                </td>
                <td
                  className={`px-4 py-2 text-right ${
                    delta > 0
                      ? "text-supports"
                      : delta < 0
                        ? "text-contradicts"
                        : "text-ink-muted"
                  }`}
                >
                  {delta > 0 ? `+${delta}` : delta}
                </td>
                <td
                  className={`px-4 py-2 text-right ${
                    process.state_confidence != null
                      ? confidenceClass(process.state_confidence)
                      : "text-ink-subtle"
                  }`}
                >
                  {process.state_confidence != null
                    ? process.state_confidence.toFixed(2)
                    : "—"}
                </td>
                {/* Contradicting evidence has a column of its own rather than
                    being netted off the delta: it is a scored dimension of
                    thesis quality, not a deduction from momentum (§17). */}
                <td
                  className={`px-4 py-2 text-right ${
                    process.contradiction_count > 0
                      ? "text-contradicts"
                      : "text-ink-subtle"
                  }`}
                >
                  {process.contradiction_count}
                </td>
                <td className="px-4 py-2 text-right text-ink-muted">
                  {process.source_breadth}
                </td>
                <td className="px-4 py-2 text-right text-ink-muted">
                  {process.asset_count}
                </td>
                <td className="px-4 py-2 text-right font-mono text-ink">
                  {process.rank_score.toFixed(3)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
