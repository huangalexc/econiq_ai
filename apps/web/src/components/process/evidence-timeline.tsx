"use client";

/**
 * Evidence timeline (ui_concept §7, and §6's third perspective).
 *
 * The API returns state changes, belief changes, evidence and critiques on one
 * axis, and this renders them in that order — because the join is the value. A
 * belief change is only defensible next to the evidence that arrived before it,
 * and reading them from two separate lists is how a reader ends up trusting a
 * confidence number without checking what moved it.
 *
 * Both clocks are shown wherever they differ. §7 asks for publication date and
 * event date separately, and the equivalent here is `occurred_at` against
 * `recorded_at`: a document published in July and ingested in August is a
 * different fact from one published and ingested in August, and only the second
 * could have influenced a belief formed in July.
 */

import type { TimelineEntry } from "@/lib/api/client";
import { cn, humanise } from "@/lib/utils";

const KIND_LABEL: Record<TimelineEntry["kind"], string> = {
  state: "State",
  journal: "Belief",
  evidence: "Evidence",
  critique: "Critique",
};

export function EvidenceTimeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-ink-muted">
        Nothing recorded for this Process as of the selected date.
      </p>
    );
  }

  return (
    <ol className="space-y-0">
      {entries.map((entry, index) => {
        const lagged =
          entry.recorded_at.slice(0, 10) !== entry.occurred_at.slice(0, 10);
        return (
          <li
            key={`${entry.kind}-${entry.subject_id ?? index}-${entry.occurred_at}`}
            className="flex gap-4 border-b border-border py-3 last:border-0"
          >
            <div className="w-24 shrink-0">
              <time
                dateTime={entry.occurred_at}
                className="block text-xs text-ink-muted"
              >
                {entry.occurred_at.slice(0, 10)}
              </time>
              {lagged ? (
                <time
                  dateTime={entry.recorded_at}
                  className="block text-[0.625rem] text-ink-subtle"
                  title="When the system learned it — a later date means it could not have informed earlier beliefs"
                >
                  learned {entry.recorded_at.slice(0, 10)}
                </time>
              ) : null}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span
                  className={cn(
                    "shrink-0 rounded border px-1.5 py-0.5 text-[0.625rem] uppercase tracking-wider",
                    entry.supports === true
                      ? "border-supports text-supports"
                      : entry.supports === false
                        ? "border-contradicts text-contradicts"
                        : "border-border text-ink-subtle",
                  )}
                >
                  {KIND_LABEL[entry.kind]}
                </span>
                <p className="min-w-0 text-sm text-ink">
                  {entry.kind === "state"
                    ? humanise(entry.title)
                    : entry.title}
                </p>
              </div>

              {entry.detail ? (
                <p className="mt-0.5 text-xs text-ink-muted">{entry.detail}</p>
              ) : null}

              {entry.confidence_before != null && entry.confidence_after != null ? (
                <p className="mt-0.5 font-mono text-xs text-ink-subtle">
                  {entry.confidence_before.toFixed(2)} →{" "}
                  <span
                    className={
                      entry.confidence_after >= entry.confidence_before
                        ? "text-supports"
                        : "text-contradicts"
                    }
                  >
                    {entry.confidence_after.toFixed(2)}
                  </span>
                </p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
