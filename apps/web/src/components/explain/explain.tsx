"use client";

/**
 * [Explain] as a universal primitive (issue #25, ui_concept §23).
 *
 * §23 requires the same affordance on scores, State assignments, Asset
 * rankings, relationships, analogue matches, alerts and recommendations, and
 * requires every explanation to carry the same seven things: conclusion,
 * supporting factors, contradictory factors, source evidence, model version,
 * timestamp, confidence.
 *
 * So this takes a normalised `Explanation` and nothing else. Each call site
 * maps its own domain object into that shape, which is deliberately the
 * awkward-feeling arrangement: a component that accepted a Scorecard *or* a
 * ProcessState *or* a rank would grow a branch per object, and the branches
 * would stop matching each other within a month. One shape means an explanation
 * looks and behaves identically wherever it appears, which is the point of
 * calling it a primitive.
 *
 * The contradictory list is never empty-by-omission. If nothing contradicts,
 * that is stated — "no contradicting evidence recorded" is a finding, and
 * silently dropping the section makes an unchallenged thesis look the same as a
 * thoroughly challenged one that survived.
 */

import { ChevronRight } from "lucide-react";
import { useId, useState } from "react";

import type { Provenance } from "@/lib/api/client";
import { cn, confidenceClass } from "@/lib/utils";

export interface Factor {
  label: string;
  /** The measurement, where there is one. Rendered verbatim, never rescaled. */
  value?: string;
  detail?: string;
}

export interface Explanation {
  /** What is being explained, in the units it is expressed in. */
  conclusion: string;
  value?: string;
  /** 0–1 model confidence, where the object carries one. */
  confidence?: number | null;
  supporting: Factor[];
  contradicting: Factor[];
  /** Free-text reasoning the producing agent supplied. */
  rationale?: string | null;
  provenance?: Provenance | null;
  /** Where to go to read the underlying evidence. */
  evidenceHref?: string;
}

export function Explain({
  explanation,
  label = "Explain",
  defaultOpen = false,
}: {
  explanation: Explanation;
  label?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex items-center gap-1 text-xs text-accent hover:underline"
      >
        <ChevronRight
          aria-hidden
          className={cn("size-3 transition-transform", open && "rotate-90")}
        />
        {label}
      </button>

      {open ? (
        <div
          id={panelId}
          className="mt-2 rounded-panel border border-border bg-surface-raised p-3"
        >
          <ExplanationBody explanation={explanation} />
        </div>
      ) : null}
    </div>
  );
}

export function ExplanationBody({ explanation }: { explanation: Explanation }) {
  return (
    <div className="space-y-3 text-xs">
      <div>
        <p className="text-ink">
          {explanation.conclusion}
          {explanation.value ? (
            <span className="ml-2 font-mono text-ink">{explanation.value}</span>
          ) : null}
        </p>
        {explanation.confidence != null ? (
          <p className="mt-0.5">
            <span className="text-ink-subtle">Confidence </span>
            <span className={confidenceClass(explanation.confidence)}>
              {explanation.confidence.toFixed(2)}
            </span>
            <span className="text-ink-subtle">
              {" "}
              — model belief, not a calibrated probability
            </span>
          </p>
        ) : null}
      </div>

      {explanation.rationale ? (
        <p className="text-ink-muted">{explanation.rationale}</p>
      ) : null}

      <FactorList
        heading="Supporting"
        factors={explanation.supporting}
        empty="No supporting factor was recorded."
        tone="supports"
      />
      <FactorList
        heading="Contradicting"
        factors={explanation.contradicting}
        empty="No contradicting evidence recorded."
        tone="contradicts"
      />

      {explanation.provenance ? (
        <ProvenanceLine provenance={explanation.provenance} />
      ) : (
        <p className="border-t border-border pt-2 text-ink-subtle">
          No agent run is recorded against this, so it cannot be attributed to a
          model or prompt.
        </p>
      )}

      {explanation.evidenceHref ? (
        <a
          href={explanation.evidenceHref}
          className="inline-block text-accent underline underline-offset-2"
        >
          View evidence
        </a>
      ) : null}
    </div>
  );
}

function FactorList({
  heading,
  factors,
  empty,
  tone,
}: {
  heading: string;
  factors: Factor[];
  empty: string;
  tone: "supports" | "contradicts";
}) {
  return (
    <div>
      <h4 className="text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
        {heading}
      </h4>
      {factors.length === 0 ? (
        <p className="mt-0.5 text-ink-subtle">{empty}</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {factors.map((factor) => (
            <li key={factor.label} className="flex gap-2">
              <span
                aria-hidden
                className={tone === "supports" ? "text-supports" : "text-contradicts"}
              >
                {tone === "supports" ? "+" : "−"}
              </span>
              <span className="min-w-0 flex-1 text-ink-muted">
                {factor.label}
                {factor.detail ? (
                  <span className="block text-ink-subtle">{factor.detail}</span>
                ) : null}
              </span>
              {factor.value ? (
                <span className="shrink-0 font-mono text-ink">{factor.value}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * §23's model version and timestamp, plus whether the deterministic checks
 * accepted the output. The last one is not in §23's list and belongs there: an
 * explanation from a run whose evaluation raised advisories is a weaker
 * explanation, and the reader cannot tell from the number alone.
 */
export function ProvenanceLine({ provenance }: { provenance: Provenance }) {
  return (
    <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1 border-t border-border pt-2 text-[0.6875rem]">
      <dt className="text-ink-subtle">Agent</dt>
      <dd className="text-ink-muted">
        {provenance.agent_name} v{provenance.agent_version}
      </dd>

      <dt className="text-ink-subtle">Model</dt>
      <dd className="text-ink-muted">
        {provenance.model ?? "not recorded"}
        {provenance.provider ? (
          <span className="text-ink-subtle"> · {provenance.provider}</span>
        ) : null}
      </dd>

      {provenance.prompt_version ? (
        <>
          <dt className="text-ink-subtle">Prompt</dt>
          <dd className="text-ink-muted">
            {provenance.prompt_name}@{provenance.prompt_version}
            <span className="ml-1 font-mono text-ink-subtle">
              {provenance.prompt_content_hash}
            </span>
          </dd>
        </>
      ) : null}

      <dt className="text-ink-subtle">As of</dt>
      <dd className="text-ink-muted" title="The cut-off this agent was given">
        {provenance.as_of.slice(0, 19).replace("T", " ")}
      </dd>

      <dt className="text-ink-subtle">Recorded</dt>
      <dd className="text-ink-muted">
        {provenance.recorded_at.slice(0, 19).replace("T", " ")}
      </dd>

      {provenance.evaluation_passed === false ||
      (provenance.advisories?.length ?? 0) > 0 ? (
        <>
          <dt className="text-ink-subtle">Checks</dt>
          <dd
            className={
              provenance.evaluation_passed === false
                ? "text-contradicts"
                : "text-needs-review"
            }
          >
            {provenance.evaluation_passed === false
              ? "rejected by evaluation"
              : `passed with ${provenance.advisories?.length} advisory note(s)`}
          </dd>
        </>
      ) : null}
    </dl>
  );
}
