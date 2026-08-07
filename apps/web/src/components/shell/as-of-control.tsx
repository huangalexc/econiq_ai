"use client";

import { Clock, X } from "lucide-react";
import { useId } from "react";

import { useAsOf } from "@/lib/as-of";

/**
 * The point-in-time control (ui_concept §2.3, §32).
 *
 * Lives in the header rather than on a Process screen because the cut-off
 * applies to everything at once, and a control that appeared only where it was
 * implemented would leave the user unsure whether the other screens had moved
 * with it.
 *
 * When a cut-off is set the whole header changes colour. Reading a
 * reconstructed view while believing it is the current one is the worst
 * available outcome here — worse than not having the feature — so the signal is
 * ambient rather than a badge somebody has to notice.
 */
export function AsOfControl() {
  const { asOf, setAsOf, isHistorical } = useAsOf();
  const inputId = useId();

  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor={inputId}
        className="flex items-center gap-1.5 text-xs text-ink-muted"
      >
        <Clock aria-hidden className="size-3.5" />
        <span>As of</span>
      </label>
      <input
        id={inputId}
        type="datetime-local"
        // `datetime-local` has no zone; the value is read as UTC on the way out
        // so a cut-off means the same instant wherever it is opened.
        value={asOf ? asOf.slice(0, 16) : ""}
        onChange={(event) =>
          setAsOf(event.target.value ? `${event.target.value}:00Z` : null)
        }
        className="rounded border border-border bg-surface-raised px-2 py-1 text-xs text-ink"
        aria-describedby={isHistorical ? `${inputId}-state` : undefined}
      />
      {isHistorical ? (
        <>
          <span id={`${inputId}-state`} className="sr-only">
            Showing what the system believed at this instant, not the current state.
          </span>
          <button
            type="button"
            onClick={() => setAsOf(null)}
            className="flex items-center gap-1 rounded border border-border-strong px-1.5 py-1 text-xs text-ink-muted hover:text-ink"
          >
            <X aria-hidden className="size-3" />
            Return to now
          </button>
        </>
      ) : (
        <span className="text-xs text-ink-subtle">now</span>
      )}
    </div>
  );
}
