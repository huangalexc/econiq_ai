"use client";

/**
 * Thesis Quality scorecard (issue #25, ui_concept §8; PRD §10).
 *
 * §8 shows six dimensions and no headline number, and PRD §10 requires the
 * dimensions always be preserved rather than reduced to one opaque score. So
 * the composite is shown *only if the producing agent recorded one*, and never
 * synthesised here — averaging six axes on the client would be exactly the
 * unexplained black box this screen exists to remove, and it would be an
 * average nobody chose the weights for.
 *
 * Each dimension opens into its own explanation: the inputs it was computed
 * from, the agent's rationale, and the run that produced it.
 *
 * §8 lists six dimensions; the ontology defines nine and Phase 0 writes one
 * (`contradiction`, from the Process Critic). The rest arrive with the Thesis
 * Scoring agent (#65) and the Counterfactual agent (#66). Dimensions the
 * ontology defines but nothing has written are listed as awaited rather than
 * hidden, because a scorecard showing one axis looks like a thesis measured on
 * one axis, and it is not — it is a thesis mostly unmeasured.
 */

import type { Scorecard, ScoreDimension } from "@/lib/api/client";
import { cn, humanise } from "@/lib/utils";

import { Explain, type Explanation } from "./explain";

/** Ontology §17's Thesis Quality axes, in the order ui_concept §8 lists them. */
const THESIS_DIMENSIONS = [
  "logical_coherence",
  "accumulated_evidence",
  "state_confidence",
  "historical_precedent",
  "counterfactual_robustness",
  "evidence_independence",
  "causal_coherence",
  "contradiction",
  "uncertainty",
] as const;

/** Why an axis has no value yet. Named so the gap is legible on the screen. */
const AWAITING: Record<string, string> = {
  logical_coherence: "Thesis Scoring agent (#65)",
  accumulated_evidence: "Thesis Scoring agent (#65)",
  state_confidence: "Thesis Scoring agent (#65)",
  historical_precedent: "Historical engine (Phase 2)",
  counterfactual_robustness: "Counterfactual agent (#66)",
  evidence_independence: "Evidence Independence agent (#67)",
  causal_coherence: "Thesis Scoring agent (#65)",
  uncertainty: "Thesis Scoring agent (#65)",
};

export function ThesisScorecard({
  scorecard,
  evidenceHref,
}: {
  scorecard: Scorecard | undefined;
  evidenceHref?: string;
}) {
  const scored = new Map(
    (scorecard?.dimensions ?? []).map((d) => [d.dimension, d] as const),
  );

  return (
    <section>
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-ink">Thesis quality</h2>
        {/* Never blended with Asset or Trade quality (ontology §17), and never
            averaged on the client. */}
        {scorecard?.composite != null ? (
          <p className="font-mono text-sm text-ink">
            {scorecard.composite.toFixed(1)}
            <span className="text-ink-subtle"> / 10</span>
          </p>
        ) : (
          <p className="text-xs text-ink-subtle">
            no composite recorded — dimensions are not averaged here
          </p>
        )}
      </div>

      <ul className="mt-3 divide-y divide-border rounded-panel border border-border bg-surface">
        {THESIS_DIMENSIONS.map((name) => {
          const dimension = scored.get(name);
          return (
            <li key={name} className="px-3 py-2">
              <div className="flex items-baseline justify-between gap-4">
                <span
                  className={cn(
                    "text-sm",
                    dimension ? "text-ink" : "text-ink-subtle",
                  )}
                >
                  {humanise(name)}
                </span>
                {dimension ? (
                  <span className="font-mono text-sm text-ink">
                    {dimension.value.toFixed(1)}
                  </span>
                ) : (
                  <span className="text-xs text-ink-subtle">
                    awaiting {AWAITING[name] ?? "its agent"}
                  </span>
                )}
              </div>
              {dimension ? (
                <div className="mt-1">
                  <Explain
                    explanation={toExplanation(dimension, scorecard, evidenceHref)}
                  />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * A dimension mapped into the universal explanation shape.
 *
 * `inputs` is what the value was computed from, and it is split by sign rather
 * than listed flat: a reader scanning an explanation wants to know what pushed
 * the number up and what pushed it down, and an undifferentiated list of six
 * numbers makes them work that out themselves.
 */
export function toExplanation(
  dimension: ScoreDimension,
  scorecard?: Scorecard,
  evidenceHref?: string,
): Explanation {
  const inputs = Object.entries(dimension.inputs ?? {});
  return {
    conclusion: humanise(dimension.dimension),
    value: `${dimension.value.toFixed(1)} / 10`,
    confidence: dimension.confidence,
    rationale: dimension.rationale,
    // Contradiction is the one dimension where a *high* number is bad, so its
    // inputs are not re-signed here — they are shown as the agent recorded them
    // and the rationale carries the direction.
    supporting: inputs
      .filter(([, value]) => value >= 0)
      .map(([label, value]) => ({ label: humanise(label), value: format(value) })),
    contradicting: inputs
      .filter(([, value]) => value < 0)
      .map(([label, value]) => ({ label: humanise(label), value: format(value) })),
    provenance: scorecard?.provenance ?? null,
    evidenceHref,
  };
}

function format(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}
