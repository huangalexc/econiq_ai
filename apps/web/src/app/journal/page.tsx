"use client";

/**
 * Thesis journal (issue #31, ui_concept §20; PRD §21).
 *
 * The record of every time the system changed its mind, and why. Entries are
 * immutable once written — an audit trail that can be edited is a narrative —
 * and every one reaches the run that produced it, because a belief change
 * nobody can attribute is a belief change nobody can review.
 *
 * Read as a feed across subjects rather than per Process. The per-Process view
 * already exists on the Process screen; this answers the different question of
 * what the system has changed its mind about lately.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Explain } from "@/components/explain/explain";
import { ApiError, api } from "@/lib/api/client";
import type { JournalEntry } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

export default function JournalPage() {
  const { asOf } = useAsOf();
  const [changedOnly, setChangedOnly] = useState(false);

  const journal = useQuery({
    queryKey: keyFor(["journal"], { asOf }),
    queryFn: ({ signal }) => api.journal({ asOf, query: { limit: 100 }, signal }),
  });

  const entries = (journal.data ?? []).filter(
    (entry) =>
      !changedOnly ||
      (entry.confidence_before != null && entry.confidence_after != null),
  );

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Thesis journal</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Why the system changed its mind, chronologically. Entries are
            immutable once written.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          <input
            type="checkbox"
            checked={changedOnly}
            onChange={(event) => setChangedOnly(event.target.checked)}
          />
          Confidence changes only
        </label>
      </div>

      {journal.isPending ? (
        <p className="mt-8 text-sm text-ink-muted">Loading…</p>
      ) : journal.isError ? (
        <p className="mt-8 text-sm text-contradicts">
          {journal.error instanceof ApiError
            ? `${journal.error.status}: ${journal.error.detail}`
            : "No response from the API."}
        </p>
      ) : entries.length === 0 ? (
        <p className="mt-8 text-sm text-ink-subtle">
          Nothing recorded as of the selected date.
        </p>
      ) : (
        <ol className="mt-6 space-y-0">
          {entries.map((entry) => (
            <Entry key={entry.id} entry={entry} />
          ))}
        </ol>
      )}
    </div>
  );
}

function Entry({ entry }: { entry: JournalEntry }) {
  const before = entry.confidence_before;
  const after = entry.confidence_after;
  const delta = before != null && after != null ? after - before : null;

  return (
    <li className="flex gap-4 border-b border-border py-4 last:border-0">
      <div className="w-24 shrink-0">
        <time dateTime={entry.observed_at} className="block text-xs text-ink-muted">
          {entry.observed_at.slice(0, 10)}
        </time>
        <span className="mt-0.5 block text-[0.625rem] uppercase tracking-wider text-ink-subtle">
          {humanise(entry.kind)}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <p className="text-sm text-ink">{entry.summary}</p>
        <p className="mt-0.5 text-xs">
          <Link
            href={`/processes/${entry.subject_id}`}
            className="text-ink-muted hover:text-accent"
          >
            {humanise(entry.subject_type)}
          </Link>
          {delta != null ? (
            <>
              <span className="text-ink-subtle"> · confidence </span>
              <span className="font-mono text-ink-subtle">{before!.toFixed(2)}</span>
              <span className="text-ink-subtle"> → </span>
              <span
                className={cn(
                  "font-mono",
                  delta >= 0 ? "text-supports" : "text-contradicts",
                )}
              >
                {after!.toFixed(2)}
              </span>
            </>
          ) : null}
        </p>

        {(entry.changes ?? []).length > 0 ? (
          <ul className="mt-2 space-y-0.5 text-xs text-ink-muted">
            {entry.changes?.map((change, index) => {
              const direction = String(
                (change as { direction?: unknown }).direction ?? "",
              );
              const statement = String(
                (change as { statement?: unknown }).statement ?? "",
              );
              return (
                <li key={index} className="flex gap-2">
                  <span
                    className={
                      direction === "weakened" ? "text-contradicts" : "text-supports"
                    }
                    aria-hidden
                  >
                    {direction === "weakened" ? "−" : "+"}
                  </span>
                  <span>{statement || direction}</span>
                </li>
              );
            })}
          </ul>
        ) : null}

        <div className="mt-2">
          <Explain
            label="Provenance"
            explanation={{
              conclusion: entry.summary,
              confidence: after ?? null,
              supporting: (entry.changes ?? [])
                .filter(
                  (c) => String((c as { direction?: unknown }).direction) !== "weakened",
                )
                .map((c) => ({
                  label: String((c as { statement?: unknown }).statement ?? "change"),
                })),
              contradicting: (entry.changes ?? [])
                .filter(
                  (c) => String((c as { direction?: unknown }).direction) === "weakened",
                )
                .map((c) => ({
                  label: String((c as { statement?: unknown }).statement ?? "change"),
                })),
              provenance: entry.provenance ?? null,
              evidenceHref: entry.triggering_event_id
                ? `/processes/${entry.subject_id}`
                : undefined,
            }}
          />
        </div>
      </div>
    </li>
  );
}
