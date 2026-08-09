"use client";

/**
 * Standalone dependency graph (issue #26).
 *
 * The same explorer the Process screen embeds, seeded from `?node=`. Kept as a
 * route because a graph is a thing people send each other, and a view that only
 * exists inside a tab cannot be linked to.
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { GraphExplorer } from "@/components/graph/graph-explorer";
import { ProvenanceInspector } from "@/components/process/provenance-inspector";
import { cn } from "@/lib/utils";

export default function GraphPage() {
  return (
    <Suspense fallback={null}>
      <GraphRoute />
    </Suspense>
  );
}

function GraphRoute() {
  const params = useSearchParams();
  const seed = params.get("node");
  const [inspecting, setInspecting] = useState<{ id: string; title: string } | null>(
    null,
  );

  if (!seed) {
    return (
      <div className="mx-auto max-w-2xl px-8 py-16">
        <h1 className="text-lg font-semibold text-ink">Dependency graph</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Open this from a Process, a Bottleneck or an Asset. The graph is
          explored outward from something — rendering all of it at once produces
          a hairball in which the confluence worth seeing is exactly what is
          hidden (ui_concept §9).
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-8 py-8">
      <h1 className="text-lg font-semibold text-ink">Dependency graph</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Typed edges from the ontology, one hop at a time. Columns are ontology
        layers, so several Processes converging on one Capability read as
        confluence rather than as crossing lines.
      </p>
      <div
        className={cn(
          "mt-6 grid gap-6",
          inspecting ? "lg:grid-cols-[1fr_24rem]" : "grid-cols-1",
        )}
      >
        <GraphExplorer
          seedId={seed}
          selectedId={inspecting?.id ?? null}
          onSelect={(node) => setInspecting({ id: node.id, title: node.label })}
        />
        {inspecting ? (
          <div className="lg:max-h-[36rem]">
            <ProvenanceInspector
              nodeId={inspecting.id}
              title={inspecting.title}
              onClose={() => setInspecting(null)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
