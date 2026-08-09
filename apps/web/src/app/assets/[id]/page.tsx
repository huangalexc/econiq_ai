"use client";

/**
 * Asset page and underwriting case (issues #28, #30; ui_concept §12, §14).
 *
 * One screen, three questions, in §14's order: why this Asset, why now, why
 * not. The third is not optional — §14.3 says the interface "must explicitly
 * surface disconfirming evidence" — so it renders whether or not there is
 * anything in it, and says which when there is not.
 *
 * "Why not" is fed by the Counterfactual agent (#66), whose output schema has
 * no field in which to conclude the thesis is safe. That is what stops this
 * panel drifting into a section that reassures.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { DiscoveryChainView } from "@/components/asset/discovery-chain";
import { Explain } from "@/components/explain/explain";
import { ApiError, api } from "@/lib/api/client";
import type { CounterfactualView } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

export default function AssetPage() {
  const { id } = useParams<{ id: string }>();
  const { asOf } = useAsOf();

  const asset = useQuery({
    queryKey: keyFor(["asset", id], { asOf }),
    queryFn: ({ signal }) => api.assets.get(id, { asOf, signal }),
  });
  const chain = useQuery({
    queryKey: keyFor(["chain", id], { asOf }),
    queryFn: ({ signal }) => api.discoveryChain(id, { asOf, signal }),
  });
  const scores = useQuery({
    queryKey: keyFor(["scores", id], { asOf }),
    queryFn: ({ signal }) => api.scores(id, { asOf, signal }),
  });

  // The Processes this Asset hangs off, taken from the chain rather than from a
  // stored list: the chain is the reason it is here, so it is also the correct
  // source for which theses it serves.
  const processIds = [
    ...new Set(
      (chain.data ?? [])
        .filter((path) => path.start.type === "process")
        .map((path) => path.start.id),
    ),
  ];

  const counterfactuals = useQuery({
    queryKey: keyFor(["counterfactuals", ...processIds], { asOf }),
    queryFn: async ({ signal }) => {
      const sets = await Promise.all(
        processIds.map((pid) => api.counterfactuals(pid, { asOf, signal })),
      );
      return sets.flat();
    },
    enabled: processIds.length > 0,
  });

  if (asset.isPending) {
    return <p className="px-8 py-10 text-sm text-ink-muted">Loading…</p>;
  }
  if (asset.isError) {
    return (
      <div className="mx-auto max-w-2xl px-8 py-16">
        <h1 className="text-lg font-semibold text-ink">Could not load</h1>
        <p className="mt-2 text-sm text-ink-muted">
          {asset.error instanceof ApiError
            ? `${asset.error.status}: ${asset.error.detail}`
            : "No response from the API."}
        </p>
      </div>
    );
  }

  const row = asset.data;
  const quality = (scores.data ?? []).find((c) => c.family === "asset_quality");
  const capability = (chain.data ?? [])
    .flatMap((path) => path.steps ?? [])
    .map((step) => step.to)
    .find((node) => node.type === "capability");

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <p className="text-xs uppercase tracking-wider text-ink-subtle">
        {humanise(row.asset_class)}
      </p>
      <h1 className="mt-1 text-2xl font-semibold text-ink">
        {row.name}
        {row.identifiers?.ticker ? (
          <span className="ml-2 font-mono text-lg text-ink-muted">
            {row.identifiers.ticker}
          </span>
        ) : null}
      </h1>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-ink-muted">
        {row.identifiers?.commodity_code ? (
          <span>commodity {row.identifiers.commodity_code}</span>
        ) : null}
        {row.identifiers?.benchmark ? <span>{row.identifiers.benchmark}</span> : null}
        {row.currency ? <span>{row.currency}</span> : null}
        <Link href={`/graph?node=${row.id}`} className="text-accent hover:underline">
          View in graph
        </Link>
        {capability ? (
          <Link
            href={`/comparison?capability=${capability.id}`}
            className="text-accent hover:underline"
          >
            Compare against peers
          </Link>
        ) : null}
      </div>

      {/* ---------------------------------------------------------------- */}
      <Section title="Why this Asset" note="ui_concept §14.1">
        <h3 className="text-xs uppercase tracking-wider text-ink-subtle">
          Discovery chain
        </h3>
        <div className="mt-2">
          {chain.isPending ? (
            <p className="text-sm text-ink-muted">Tracing…</p>
          ) : (
            <DiscoveryChainView paths={chain.data ?? []} />
          )}
        </div>

        {(row.exposures ?? []).length > 0 ? (
          <>
            <h3 className="mt-6 text-xs uppercase tracking-wider text-ink-subtle">
              Recorded exposures
            </h3>
            <ul className="mt-2 space-y-2">
              {row.exposures?.map((exposure, index) => (
                <li key={index} className="rounded-panel border border-border bg-surface p-3">
                  <p className="text-sm text-ink">
                    {humanise(exposure.exposure_kind)}{" "}
                    <span className="text-ink-subtle">({exposure.directness})</span>
                    <span className="ml-2 font-mono text-ink-muted">
                      {exposure.magnitude.toFixed(1)}
                    </span>
                  </p>
                  <p className="mt-1 text-xs text-ink-muted">{exposure.rationale}</p>
                </li>
              ))}
            </ul>
          </>
        ) : null}

        {quality ? (
          <>
            <h3 className="mt-6 text-xs uppercase tracking-wider text-ink-subtle">
              Expression quality
            </h3>
            <ul className="mt-2 divide-y divide-border rounded-panel border border-border bg-surface">
              {(quality.dimensions ?? []).map((dimension) => (
                <li key={dimension.dimension} className="px-3 py-2">
                  <div className="flex items-baseline justify-between">
                    <span className="text-sm text-ink">
                      {humanise(dimension.dimension)}
                    </span>
                    <span className="font-mono text-sm text-ink">
                      {dimension.value.toFixed(1)}
                    </span>
                  </div>
                  <div className="mt-1">
                    <Explain
                      explanation={{
                        conclusion: humanise(dimension.dimension),
                        value: `${dimension.value.toFixed(1)} / 10`,
                        confidence: dimension.confidence,
                        rationale: dimension.rationale,
                        supporting: Object.entries(dimension.inputs ?? {}).map(
                          ([label, value]) => ({
                            label: humanise(label),
                            value: String(value),
                          }),
                        ),
                        contradicting: [],
                        provenance: quality.provenance ?? null,
                      }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-6 text-sm text-ink-subtle">
            No Asset Quality scorecard yet. It is written by the Quant and
            Quality agents once this Capability is scored.
          </p>
        )}
      </Section>

      {/* ---------------------------------------------------------------- */}
      <Section title="Why now" note="ui_concept §14.2">
        {processIds.length === 0 ? (
          <p className="text-sm text-ink-subtle">
            No Process reaches this Asset, so there is no timing argument to
            make.
          </p>
        ) : (
          <ul className="space-y-2">
            {processIds.map((pid) => (
              <li key={pid} className="rounded-panel border border-border bg-surface p-3">
                <WhyNow processId={pid} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* ---------------------------------------------------------------- */}
      <Section title="Why not" note="ui_concept §14.3 — mandatory">
        {/* Rendered whether or not it has content. §14.3 says the interface
            *must* surface disconfirming evidence, and a panel that disappears
            when empty makes an unexamined thesis look like a clean one. */}
        {processIds.length === 0 ? (
          <p className="text-sm text-ink-subtle">
            No Process reaches this Asset, so nothing has been argued against.
          </p>
        ) : counterfactuals.isPending ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : (counterfactuals.data ?? []).length === 0 ? (
          <p className="text-sm text-needs-review">
            No counterfactuals have been constructed for the upstream
            Process(es). This is an untested thesis, not a robust one — the
            Counterfactual agent has not run.
          </p>
        ) : (
          <ol className="space-y-3">
            {counterfactuals.data?.map((row) => (
              <Counterfactual key={row.id} row={row} />
            ))}
          </ol>
        )}
      </Section>

      <Section title="Historical precedent" note="Phase 2">
        <p className="text-sm text-ink-subtle">
          Historical analogues need the retrieval engine (#35–#46). Shown as a
          slot rather than omitted, because an underwriting case with no
          precedent section reads as a case with no precedent.
        </p>
      </Section>
    </div>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-10 border-t border-border pt-6">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-medium text-ink">{title}</h2>
        <span className="text-[0.625rem] uppercase tracking-wider text-ink-subtle">
          {note}
        </span>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** State movement and evidence momentum for one upstream Process (§14.2). */
function WhyNow({ processId }: { processId: string }) {
  const { asOf } = useAsOf();
  const process = useQuery({
    queryKey: keyFor(["process", processId], { asOf }),
    queryFn: ({ signal }) => api.processes.get(processId, { asOf, signal }),
  });

  if (process.isPending) return <p className="text-sm text-ink-muted">Loading…</p>;
  if (process.isError) return <p className="text-sm text-contradicts">Unavailable.</p>;

  const row = process.data;
  return (
    <>
      <Link
        href={`/processes/${row.id}`}
        className="text-sm text-ink hover:text-accent"
      >
        {row.name}
      </Link>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <dt className="text-ink-subtle">State</dt>
        <dd className="text-ink">
          {row.state ? humanise(row.state.categorical_state) : "—"}
        </dd>
        <dt className="text-ink-subtle">Confidence</dt>
        <dd className="text-ink">
          {row.state ? row.state.state_confidence.toFixed(2) : "—"}
        </dd>
        <dt className="text-ink-subtle">Evidence for</dt>
        <dd className="text-supports">{row.evidence_event_count}</dd>
        <dt className="text-ink-subtle">Against</dt>
        <dd className={row.contradicting_event_count > 0 ? "text-contradicts" : "text-ink-muted"}>
          {row.contradicting_event_count}
        </dd>
      </dl>
      {row.state?.transition_indicators?.length ? (
        <p className="mt-2 text-xs text-ink-muted">
          Watch for: {row.state.transition_indicators.join("; ")}
        </p>
      ) : null}
    </>
  );
}

function Counterfactual({ row }: { row: CounterfactualView }) {
  const threat = (row.plausibility / 10) * (row.severity_if_true / 10);
  return (
    <li
      className={cn(
        "rounded-panel border bg-surface p-3",
        row.is_most_dangerous ? "border-contradicts" : "border-border",
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm text-ink">{row.challenged_assumption}</p>
        {row.is_most_dangerous ? (
          <span className="shrink-0 text-[0.625rem] uppercase tracking-wider text-contradicts">
            most dangerous
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-ink-muted">{row.alternative_world}</p>
      <p className="mt-1.5 font-mono text-[0.6875rem] text-ink-subtle">
        plausibility {row.plausibility.toFixed(1)} · severity{" "}
        {row.severity_if_true.toFixed(1)} · threat {threat.toFixed(2)}
      </p>
      {(row.observable_indicators ?? []).length > 0 ? (
        <div className="mt-2">
          {/* The falsifiable half. A world nobody could detect is not a research
              finding, which is why the agent's schema requires at least one. */}
          <p className="text-[0.625rem] uppercase tracking-wider text-ink-subtle">
            What would reveal it
          </p>
          <ul className="mt-0.5 space-y-0.5 text-xs text-ink-muted">
            {row.observable_indicators?.map((indicator) => (
              <li key={indicator}>• {indicator}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </li>
  );
}
