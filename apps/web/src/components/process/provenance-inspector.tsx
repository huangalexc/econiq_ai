"use client";

/**
 * Provenance inspector (issue #24, ui_concept §29).
 *
 * §29 calls evidence provenance "a core trust mechanism" and requires that
 * every generated statement can display its evidence, its Event clusters, its
 * extraction timestamp, the model, and the confidence — and that the user can
 * reach the original document. It ends with the line this component is built
 * around: *evidence should never be represented merely as an undifferentiated
 * "AI summary."*
 *
 * So the panel shows Claims, not a count of Claims, and each Claim shows the
 * quoted span with its character offsets into the parsed document. Offsets look
 * like clutter until you need them: they are what makes the citation checkable
 * rather than merely present, and code verified them at write time (an
 * unlocatable quote was dropped, not stored).
 *
 * Independent source count is shown against document count on purpose. Where
 * they differ, syndication was collapsed, and the reader is looking at fewer
 * real sources than documents — which is the single most misleading thing about
 * an evidence list that does not say so.
 */

import { X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { ProvenanceLine } from "@/components/explain/explain";
import { ApiError, api } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { humanise } from "@/lib/utils";

export function ProvenanceInspector({
  nodeId,
  title,
  onClose,
}: {
  nodeId: string;
  title: string;
  onClose: () => void;
}) {
  const { asOf } = useAsOf();
  const inspection = useQuery({
    queryKey: keyFor(["inspect", nodeId], { asOf }),
    queryFn: ({ signal }) => api.inspect(nodeId, { asOf, signal }),
  });

  const documents = new Map(
    (inspection.data?.documents ?? []).map((doc) => [doc.id, doc] as const),
  );

  return (
    <aside
      className="flex h-full flex-col border-l border-border bg-surface"
      aria-label={`Provenance for ${title}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
            Provenance
          </p>
          <h2 className="truncate text-sm text-ink">{title}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close provenance"
          className="shrink-0 rounded border border-border p-1 text-ink-muted hover:text-ink"
        >
          <X aria-hidden className="size-3.5" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {inspection.isPending ? (
          <p className="text-sm text-ink-muted">Tracing…</p>
        ) : inspection.isError ? (
          <p className="text-sm text-contradicts">
            {inspection.error instanceof ApiError
              ? `${inspection.error.status}: ${inspection.error.detail}`
              : "Could not trace this."}
          </p>
        ) : (
          <div className="space-y-5">
            <SourceCount
              independent={inspection.data.independent_source_count}
              documents={inspection.data.documents?.length ?? 0}
              events={inspection.data.supporting_events?.length ?? 0}
              contradicting={inspection.data.contradicting_events?.length ?? 0}
            />

            <section>
              <h3 className="text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
                Claims
              </h3>
              {(inspection.data.claims?.length ?? 0) === 0 ? (
                <p className="mt-1 text-sm text-ink-subtle">
                  No Claim is recorded behind this. That is a gap in the chain,
                  not an absence of opinion.
                </p>
              ) : (
                <ul className="mt-2 space-y-4">
                  {inspection.data.claims?.map((claim) => {
                    const document = documents.get(claim.document_id);
                    const location = claim.source_location as {
                      quote?: string;
                      char_start?: number;
                      char_end?: number;
                      section?: string;
                    };
                    return (
                      <li key={claim.id} className="border-b border-border pb-4 last:border-0">
                        <p className="text-sm text-ink">{claim.text}</p>

                        {location.quote ? (
                          <blockquote className="mt-2 border-l-2 border-accent-muted pl-3 text-xs text-ink-muted">
                            &ldquo;{location.quote}&rdquo;
                            <span className="mt-0.5 block font-mono text-[0.625rem] text-ink-subtle">
                              {location.section ? `${location.section} · ` : ""}
                              chars {location.char_start}–{location.char_end}
                            </span>
                          </blockquote>
                        ) : null}

                        <dl className="mt-2 grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1 text-[0.6875rem]">
                          <dt className="text-ink-subtle">Type</dt>
                          <dd className="text-ink-muted">
                            {humanise(claim.claim_type)}
                            {claim.assertion_source ? (
                              <span className="text-ink-subtle">
                                {" "}
                                · {humanise(claim.assertion_source)}
                              </span>
                            ) : null}
                          </dd>

                          {claim.attributed_to ? (
                            <>
                              <dt className="text-ink-subtle">Attributed to</dt>
                              <dd className="text-ink-muted">{claim.attributed_to}</dd>
                            </>
                          ) : null}

                          <dt className="text-ink-subtle">Extraction</dt>
                          <dd className="text-ink-muted">
                            confidence {claim.extraction_confidence.toFixed(2)}
                          </dd>

                          {document ? (
                            <>
                              <dt className="text-ink-subtle">Source</dt>
                              <dd className="text-ink-muted">
                                {document.publisher ?? document.source}
                                <span className="text-ink-subtle">
                                  {" "}
                                  · {document.publication_time.slice(0, 10)}
                                </span>
                                {document.url ? (
                                  <a
                                    href={document.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="ml-2 text-accent underline underline-offset-2"
                                  >
                                    original
                                  </a>
                                ) : null}
                              </dd>
                            </>
                          ) : null}
                        </dl>

                        {claim.provenance ? (
                          <div className="mt-2">
                            <ProvenanceLine provenance={claim.provenance} />
                          </div>
                        ) : (
                          <p className="mt-2 text-[0.6875rem] text-ink-subtle">
                            No extraction run recorded — this Claim cannot be
                            attributed to a model.
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </aside>
  );
}

function SourceCount({
  independent,
  documents,
  events,
  contradicting,
}: {
  independent: number;
  documents: number;
  events: number;
  contradicting: number;
}) {
  const collapsed = documents - independent;
  return (
    <section>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-ink-subtle">Event clusters</dt>
        <dd className="text-ink">
          <span className="text-supports">{events}</span>
          {contradicting > 0 ? (
            <>
              <span className="text-ink-subtle"> for · </span>
              <span className="text-contradicts">{contradicting}</span>
              <span className="text-ink-subtle"> against</span>
            </>
          ) : null}
        </dd>

        <dt className="text-ink-subtle">Independent sources</dt>
        <dd className="text-ink">{independent}</dd>

        <dt className="text-ink-subtle">Documents</dt>
        <dd className="text-ink">{documents}</dd>
      </dl>
      {collapsed > 0 ? (
        <p className="mt-2 text-[0.6875rem] text-ink-muted">
          {collapsed} document{collapsed === 1 ? "" : "s"} added no independent
          source — syndicated copy, collapsed so repetition does not read as
          corroboration.
        </p>
      ) : null}
    </section>
  );
}
