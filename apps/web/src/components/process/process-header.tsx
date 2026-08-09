"use client";

/**
 * Process header (ui_concept §6.1).
 *
 * §6.1 shows six measures. Four have data; two do not, and they are rendered as
 * explicitly unavailable rather than omitted or blank:
 *
 * * **Historical precedent** needs the historical retrieval engine (Phase 2,
 *   #35-#46). A blank row here reads as a Process with no precedent, which is a
 *   finding rather than an absence.
 * * **Counterfactual robustness** is a real Thesis Quality dimension in the
 *   ontology, but no Phase 0 agent writes it — the Process Critic writes
 *   `contradiction` only. This is the same class of gap as PRD §28.7 and is
 *   worth seeing on the screen rather than discovering later.
 *
 * Showing an empty slot with a reason is the honest option: the reader learns
 * both what the system knows and what it has not been built to know yet.
 */

import { SignInButton, useAuth } from "@clerk/nextjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { api } from "@/lib/api/client";
import type { ProcessDetail, Scorecard } from "@/lib/api/client";
import { cn, confidenceClass, humanise } from "@/lib/utils";

export function ProcessHeader({
  process,
  scorecards,
  evidenceDelta,
}: {
  process: ProcessDetail;
  scorecards: Scorecard[];
  evidenceDelta: number | null;
}) {
  const thesis = scorecards.find((card) => card.family === "thesis_quality");
  const dimension = (name: string) =>
    (thesis?.dimensions ?? []).find((d) => d.dimension === name);
  const contradiction = dimension("contradiction");

  return (
    <header className="border-b border-border pb-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink">{process.name}</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {process.archetype
              ? humanise(process.archetype)
              : "Archetype not classified"}
            {process.archetype_confidence != null ? (
              <span className="text-ink-subtle">
                {" "}
                · classification confidence{" "}
                {process.archetype_confidence.toFixed(2)}
              </span>
            ) : null}
          </p>
          <p className="mt-2 max-w-3xl text-sm text-ink-muted">
            {process.description}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <TrackButton processId={process.id} />
          <Link
            href={`/graph?node=${process.id}`}
            className="rounded border border-border px-3 py-1.5 text-sm text-ink-muted hover:text-ink"
          >
            View graph
          </Link>
        </div>
      </div>

      {process.requires_review ? (
        <p className="mt-4 rounded border border-needs-review bg-needs-review/10 px-3 py-2 text-xs text-ink">
          Flagged for human review. A false Process contaminates everything
          downstream of it, so creation is a review point (agent doc §23).
        </p>
      ) : null}

      <dl className="mt-5 grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
        <Measure label="Current State">
          <span className="text-ink">
            {process.state ? humanise(process.state.categorical_state) : "—"}
          </span>
        </Measure>

        <Measure label="State confidence">
          {process.state ? (
            <span className={confidenceClass(process.state.state_confidence)}>
              {process.state.state_confidence.toFixed(2)}
            </span>
          ) : (
            <span className="text-ink-subtle">—</span>
          )}
        </Measure>

        <Measure label="Evidence momentum">
          {evidenceDelta === null ? (
            <span className="text-ink-subtle">—</span>
          ) : (
            <span
              className={cn(
                evidenceDelta > 0
                  ? "text-supports"
                  : evidenceDelta < 0
                    ? "text-contradicts"
                    : "text-ink-muted",
              )}
            >
              {evidenceDelta > 2 ? "↑↑" : evidenceDelta > 0 ? "↑" : evidenceDelta < 0 ? "↓" : "→"}{" "}
              <span className="text-ink-subtle">
                ({evidenceDelta > 0 ? "+" : ""}
                {evidenceDelta} in 30d)
              </span>
            </span>
          )}
        </Measure>

        <Measure label="Evidence balance">
          <span className="text-supports">{process.evidence_event_count}</span>
          <span className="text-ink-subtle"> for · </span>
          <span className="text-contradicts">
            {process.contradicting_event_count}
          </span>
          <span className="text-ink-subtle"> against</span>
        </Measure>

        {contradiction ? (
          <Measure label="Falsification risk">
            <span className="text-ink">{contradiction.value.toFixed(1)}</span>
            <span className="text-ink-subtle"> / 10</span>
          </Measure>
        ) : null}

        <Unavailable
          label="Historical precedent"
          reason="Needs the historical retrieval engine (Phase 2, #35-#46)."
        />
        <Unavailable
          label="Counterfactual robustness"
          reason="A Thesis Quality dimension no Phase 0 agent writes yet."
        />
      </dl>
    </header>
  );
}

function Measure({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
        {label}
      </dt>
      <dd className="mt-1 text-sm">{children}</dd>
    </div>
  );
}

/** A measure §6.1 asks for that this deployment cannot produce, and why. */
function Unavailable({ label, reason }: { label: string; reason: string }) {
  return (
    <div>
      <dt className="text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
        {label}
      </dt>
      <dd className="mt-1 text-sm text-ink-subtle" title={reason}>
        not yet measured
      </dd>
    </div>
  );
}


/**
 * Track (issues #19, #32).
 *
 * Signed out this is a sign-in prompt rather than a disabled button: the reader
 * cannot act, but the reason is a session rather than a missing feature, and
 * those look identical when a control is merely greyed out.
 */
function TrackButton({ processId }: { processId: string }) {
  const { isSignedIn } = useAuth();
  const queryClient = useQueryClient();
  const watchlist = useQuery({
    queryKey: ["watchlist", "now", null],
    queryFn: ({ signal }) => api.workspace.watchlist({ signal }),
    enabled: Boolean(isSignedIn),
  });

  const watched = (watchlist.data ?? []).some((item) => item.node.id === processId);
  const toggle = useMutation({
    mutationFn: () =>
      watched
        ? api.workspace.unwatch(processId)
        : api.workspace.watch(processId).then(() => null),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });

  if (!isSignedIn) {
    return (
      <SignInButton mode="modal">
        <button
          type="button"
          className="rounded border border-border px-3 py-1.5 text-sm text-ink-muted hover:text-ink"
        >
          Sign in to track
        </button>
      </SignInButton>
    );
  }

  return (
    <button
      type="button"
      onClick={() => toggle.mutate()}
      disabled={toggle.isPending}
      className={cn(
        "rounded border px-3 py-1.5 text-sm",
        watched
          ? "border-accent text-accent"
          : "border-border text-ink-muted hover:text-ink",
      )}
    >
      {watched ? "Tracking" : "Track"}
    </button>
  );
}
