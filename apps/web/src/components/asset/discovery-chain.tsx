"use client";

/**
 * The visible discovery chain (issue #28, ui_concept §12).
 *
 * §12's requirement is that "when a user reaches an Asset from a Process, the
 * system should explicitly explain why it appears", and it draws the chain:
 * a Process creates a Bottleneck, which requires a Capability, which the Asset
 * expresses.
 *
 * Rendered as the chain rather than as a list of related objects. The order is
 * the argument — this Asset is here *because* a Process created a constraint
 * that needs a Capability it happens to have — and a flat "related Processes"
 * list is the same data with the reasoning removed.
 *
 * Each step carries the rationale the agent gave for that edge, so the chain is
 * inspectable at every hop rather than only at its ends.
 */

import Link from "next/link";

import type { DiscoveryChain } from "@/lib/api/client";
import { humanise } from "@/lib/utils";

type Path = DiscoveryChain[number];

const HREF: Record<string, string> = {
  process: "/processes",
  bottleneck: "/bottlenecks",
  capability: "/capabilities",
  asset: "/assets",
};

function NodeLink({
  node,
}: {
  node: { id: string; type: string; label: string };
}) {
  const href = HREF[node.type];
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[0.5625rem] uppercase tracking-wider text-ink-subtle">
        {humanise(node.type)}
      </span>
      {href ? (
        <Link href={`${href}/${node.id}`} className="text-sm text-ink hover:text-accent">
          {node.label}
        </Link>
      ) : (
        <span className="text-sm text-ink">{node.label}</span>
      )}
    </span>
  );
}

export function DiscoveryChainView({ paths }: { paths: Path[] }) {
  if (paths.length === 0) {
    return (
      <p className="text-sm text-ink-subtle">
        No chain reaches this Asset. That is a defect rather than an absence — an
        Asset nobody can explain is exactly what the discovery chain exists to
        prevent.
      </p>
    );
  }

  return (
    <ol className="space-y-4">
      {paths.map((path, index) => (
        <li key={index} className="rounded-panel border border-border bg-surface p-3">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <NodeLink node={path.start} />
            {(path.steps ?? []).map((step, position) => (
              <span key={position} className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="text-[0.5625rem] uppercase tracking-wider text-accent-muted"
                  title={step.rationale ?? undefined}
                >
                  → {humanise(step.relationship_type)} →
                </span>
                <NodeLink node={step.to} />
              </span>
            ))}
          </div>

          <p className="mt-2 text-xs text-ink-subtle">
            {path.depth} hop{path.depth === 1 ? "" : "s"} · weakest edge{" "}
            <span className="font-mono">{path.weight.toFixed(2)}</span>
            {/* A chain is only as good as its weakest edge: a strong Process
                joined to a tenuous Capability link is a tenuous case. */}
          </p>

          {(path.steps ?? []).some((step) => step.rationale) ? (
            <ul className="mt-2 space-y-0.5 text-xs text-ink-muted">
              {path.steps?.map((step, position) =>
                step.rationale ? (
                  <li key={position}>
                    <span className="text-ink-subtle">
                      {humanise(step.relationship_type)}:
                    </span>{" "}
                    {step.rationale}
                  </li>
                ) : null,
              )}
            </ul>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
