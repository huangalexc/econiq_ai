"use client";

/**
 * State history on the archetype's machine (ui_concept §6.2).
 *
 * §6.2 draws the machine vertically with the current State marked, and asks
 * that "the date and confidence associated with each transition" be recorded.
 * The machine comes from the API so this component never owns the ordering.
 *
 * The append-only history is the record (ui_concept §32): a State the Process
 * passed through and left is still shown, with the date it was observed. States
 * it has not reached are drawn faintly — they are the machine's shape, not
 * claims about where it will go. That distinction is the reason this is not a
 * progress bar.
 */

import type { ProcessState, StateNode } from "@/lib/api/client";
import { cn, confidenceClass, humanise } from "@/lib/utils";

export function StateMachineTrack({
  states,
  history,
  current,
}: {
  states: StateNode[];
  history: ProcessState[];
  current: string | null;
}) {
  // Earliest observation per State: when the Process first arrived there.
  const arrivals = new Map<string, ProcessState>();
  for (const observation of [...history].sort(
    (a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at),
  )) {
    if (!arrivals.has(observation.categorical_state)) {
      arrivals.set(observation.categorical_state, observation);
    }
  }

  return (
    <ol className="space-y-0">
      {states.map((node, index) => {
        const arrival = arrivals.get(node.state);
        const isCurrent = node.state === current;
        const visited = arrival !== undefined;

        return (
          <li key={node.state} className="relative flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  "mt-1 size-2.5 shrink-0 rounded-full border",
                  isCurrent
                    ? "border-accent bg-accent"
                    : visited
                      ? "border-ink-muted bg-ink-muted"
                      : "border-border bg-transparent",
                )}
                aria-hidden
              />
              {index < states.length - 1 ? (
                <span
                  className={cn(
                    "w-px flex-1",
                    visited ? "bg-ink-subtle" : "bg-border",
                  )}
                  aria-hidden
                />
              ) : null}
            </div>

            <div className={cn("pb-4", index === states.length - 1 && "pb-0")}>
              <p
                className={cn(
                  "text-sm",
                  isCurrent
                    ? "font-medium text-ink"
                    : visited
                      ? "text-ink-muted"
                      : "text-ink-subtle",
                )}
              >
                {humanise(node.state)}
                {isCurrent ? (
                  <span className="ml-2 text-xs uppercase tracking-wider text-accent">
                    current
                  </span>
                ) : null}
                {node.is_terminal && !isCurrent ? (
                  <span className="ml-2 text-[0.625rem] uppercase tracking-wider text-ink-subtle">
                    terminal
                  </span>
                ) : null}
              </p>
              {arrival ? (
                <p className="mt-0.5 text-xs text-ink-subtle">
                  <time dateTime={arrival.observed_at}>
                    {arrival.observed_at.slice(0, 10)}
                  </time>
                  {" · confidence "}
                  <span className={confidenceClass(arrival.state_confidence)}>
                    {arrival.state_confidence.toFixed(2)}
                  </span>
                </p>
              ) : (
                <p className="mt-0.5 text-xs text-ink-subtle">
                  not reached
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
