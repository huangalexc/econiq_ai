"use client";

/**
 * Hot Process card (ui_concept §5.3).
 *
 * §5.3 lists ten fields. Nine are available; historical precedent needs the
 * Phase 2 engine and is omitted rather than shown blank — an empty "Historical
 * precedent" row reads as a Process with no precedent, which is a claim, not an
 * absence.
 *
 * Contradictions are on the card. A card showing only supporting evidence would
 * be a pitch; ontology §17 makes contradiction a scored dimension of thesis
 * quality, so it belongs next to the momentum rather than behind a tab.
 */

import Link from "next/link";
import { useState } from "react";

import type { EmergingProcess } from "@/lib/api/client";
import { confidenceClass, humanise } from "@/lib/utils";

import { RankExplain } from "./rank-explain";

export function HotCard({ process }: { process: EmergingProcess }) {
  const [explaining, setExplaining] = useState(false);
  const delta = process.evidence_delta ?? 0;

  return (
    <article className="flex flex-col gap-3 rounded-panel border border-border bg-surface p-4">
      <div>
        <Link
          href={`/processes/${process.id}`}
          className="text-sm font-semibold text-ink hover:text-accent"
        >
          {process.name}
        </Link>
        <p className="mt-0.5 text-xs text-ink-subtle">
          {process.archetype ? humanise(process.archetype) : "Archetype not classified"}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <dt className="text-ink-subtle">State</dt>
        <dd className="text-ink">
          {process.current_state ? humanise(process.current_state) : "—"}
        </dd>

        <dt className="text-ink-subtle">Confidence</dt>
        <dd className={process.state_confidence != null ? confidenceClass(process.state_confidence) : "text-ink-subtle"}>
          {process.state_confidence != null
            ? process.state_confidence.toFixed(2)
            : "—"}
        </dd>

        <dt className="text-ink-subtle">Evidence momentum</dt>
        <dd className={delta > 0 ? "text-supports" : delta < 0 ? "text-contradicts" : "text-ink-muted"}>
          <Momentum delta={delta} />{" "}
          <span className="text-ink-subtle">
            ({process.evidence_recent} vs {process.evidence_prior})
          </span>
        </dd>

        <dt className="text-ink-subtle">Contradictions</dt>
        <dd className={process.contradiction_count > 0 ? "text-contradicts" : "text-ink-muted"}>
          {process.contradiction_count}
        </dd>

        <dt className="text-ink-subtle">Source breadth</dt>
        {/* Named for what it is. Phase 0 has no market data, and calling
            publisher count "attention" would make §5.2's central claim —
            evidence moving before attention — untestable. */}
        <dd className="text-ink-muted" title="Distinct publishers — media coverage, not market attention">
          {process.source_breadth} publisher
          {process.source_breadth === 1 ? "" : "s"}
        </dd>
      </dl>

      {process.binding_bottlenecks && process.binding_bottlenecks.length > 0 ? (
        <div>
          <p className="text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
            Binding bottlenecks
          </p>
          <ul className="mt-1 space-y-0.5 text-xs text-ink-muted">
            {process.binding_bottlenecks.map((name) => (
              <li key={name}>• {name}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-auto flex items-center justify-between border-t border-border pt-3 text-xs">
        <span className="text-ink-muted">
          {process.capability_count} capabilit
          {process.capability_count === 1 ? "y" : "ies"} ·{" "}
          {process.asset_count} asset{process.asset_count === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          onClick={() => setExplaining((open) => !open)}
          className="text-accent underline underline-offset-2"
          aria-expanded={explaining}
        >
          {explaining ? "Hide" : "Explain"} rank
        </button>
      </div>

      {explaining ? (
        <RankExplain
          components={process.components ?? []}
          score={process.rank_score}
        />
      ) : null}
    </article>
  );
}

function Momentum({ delta }: { delta: number }) {
  // Arrows rather than a number alone, per §5.3's "↑↑". Two arrows is a
  // threshold, not a scale — the underlying counts are shown beside it.
  if (delta >= 3) return <span aria-label="strongly accelerating">↑↑</span>;
  if (delta > 0) return <span aria-label="accelerating">↑</span>;
  if (delta < 0) return <span aria-label="decelerating">↓</span>;
  return <span aria-label="unchanged">→</span>;
}
