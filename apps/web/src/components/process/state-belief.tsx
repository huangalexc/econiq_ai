"use client";

/**
 * Model belief about the next State (ui_concept §6.3, ontology §35).
 *
 * §6.3 asks for a State distribution "where probabilistic/state-distribution
 * modeling is available", and is explicit that until the model is calibrated it
 * must be labelled "State distribution", "State confidence" or "model belief"
 * rather than implying calibrated probabilities.
 *
 * It is not available. The system computes no distribution over the *current*
 * State — it commits to one State with a confidence. What it does produce is
 * `transition_beliefs`: how likely the model thinks each next State is. So that
 * is what this renders, under that name.
 *
 * The distinction matters more than it looks. A bar chart headed "State
 * distribution" showing 68% against Infrastructure Expansion says the Process
 * is *probably* in that State. These numbers say something else — that it is in
 * a known State and may move to another. Rendering the second under the first's
 * heading would be a claim the system never made, which is exactly the
 * substitution §6.3 was written to prevent.
 *
 * The numbers are never shown as percentages. Percent signs imply a normalised
 * distribution, and these beliefs neither sum to one nor have been calibrated.
 */

import type { ProcessState } from "@/lib/api/client";
import { humanise } from "@/lib/utils";

export function StateBelief({ state }: { state: ProcessState }) {
  const beliefs = Object.entries(state.transition_beliefs ?? {}).sort(
    (a, b) => b[1] - a[1],
  );

  return (
    <section>
      <h3 className="text-sm font-medium text-ink">Transition belief</h3>
      <p className="mt-1 text-xs text-ink-muted">
        Where the model thinks this Process moves next. Model belief, not
        calibrated probability — these are uncalibrated until the calibration
        framework validates them (ontology §35), so they are not shown as
        percentages and do not sum to one.
      </p>

      {beliefs.length === 0 ? (
        <p className="mt-3 text-sm text-ink-subtle">
          No transition belief was recorded for this State observation.
        </p>
      ) : (
        <dl className="mt-3 space-y-2">
          {beliefs.map(([label, value]) => (
            <div key={label} className="grid grid-cols-[10rem_1fr_3rem] items-center gap-3">
              <dt className="truncate text-xs text-ink-muted">{humanise(label)}</dt>
              <dd className="h-1.5 rounded-full bg-surface-raised">
                <div
                  className="h-1.5 rounded-full bg-estimated"
                  style={{ width: `${Math.min(value, 1) * 100}%` }}
                />
              </dd>
              <dd className="text-right font-mono text-xs text-ink">
                {value.toFixed(2)}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {(state.transition_indicators ?? []).length > 0 ? (
        <Indicators
          heading="What would confirm a move"
          items={state.transition_indicators ?? []}
        />
      ) : null}
      {(state.reversal_indicators ?? []).length > 0 ? (
        <Indicators
          heading="What would reverse it"
          items={state.reversal_indicators ?? []}
        />
      ) : null}
    </section>
  );
}

/**
 * Indicators are the falsifiable part of a State estimate — the observations
 * that would confirm or overturn it — so they sit next to the belief rather
 * than in a details panel.
 */
function Indicators({ heading, items }: { heading: string; items: string[] }) {
  return (
    <div className="mt-4">
      <h4 className="text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
        {heading}
      </h4>
      <ul className="mt-1 space-y-0.5 text-xs text-ink-muted">
        {items.map((item) => (
          <li key={item}>• {item}</li>
        ))}
      </ul>
    </div>
  );
}
