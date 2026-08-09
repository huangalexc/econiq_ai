"use client";

/**
 * Screener filters (ui_concept §25).
 *
 * State lives in the URL, like `as_of` does. A screen someone tuned for twenty
 * minutes is the thing they most want to send to a colleague, and §25 calls the
 * screener "likely to become one of the highest-value discovery tools" — a
 * high-value tool whose output cannot be linked to gets screenshotted instead.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { humanise } from "@/lib/utils";

export const ARCHETYPES = [
  "infrastructure_s_curve",
  "commodity_supply_cycle",
  "industrial_bottleneck",
  "regulatory_implementation",
  "business_model_disruption",
] as const;

export interface ScreenerFilters {
  archetype: string | null;
  minStateConfidence: number | null;
  minAssets: number | null;
  minCapabilities: number | null;
  acceleratingOnly: boolean;
}

const KEYS = {
  archetype: "archetype",
  minStateConfidence: "min_state_confidence",
  minAssets: "min_assets",
  minCapabilities: "min_capabilities",
  acceleratingOnly: "accelerating_only",
} as const;

export function useScreener(): [ScreenerFilters, (next: Partial<ScreenerFilters>) => void] {
  const router = useRouter();
  const params = useSearchParams();

  const filters: ScreenerFilters = {
    archetype: params.get(KEYS.archetype),
    minStateConfidence: numberOrNull(params.get(KEYS.minStateConfidence)),
    minAssets: numberOrNull(params.get(KEYS.minAssets)),
    minCapabilities: numberOrNull(params.get(KEYS.minCapabilities)),
    acceleratingOnly: params.get(KEYS.acceleratingOnly) === "true",
  };

  const update = useCallback(
    (next: Partial<ScreenerFilters>) => {
      const search = new URLSearchParams(params.toString());
      for (const [field, value] of Object.entries(next)) {
        const key = KEYS[field as keyof ScreenerFilters];
        // `false` and `null` both mean "no filter" and are removed rather than
        // written, so a default-state screener has a clean URL.
        if (value === null || value === "" || value === false) search.delete(key);
        else search.set(key, String(value));
      }
      router.replace(`?${search.toString()}`, { scroll: false });
    },
    [params, router],
  );

  return [filters, update];
}

function numberOrNull(value: string | null): number | null {
  if (value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function Screener() {
  const [filters, update] = useScreener();
  const active =
    filters.archetype !== null ||
    filters.minStateConfidence !== null ||
    filters.minAssets !== null ||
    filters.minCapabilities !== null ||
    filters.acceleratingOnly;

  return (
    <div className="flex flex-wrap items-end gap-4 rounded-panel border border-border bg-surface px-4 py-3">
      <Field label="Archetype">
        <select
          value={filters.archetype ?? ""}
          onChange={(event) => update({ archetype: event.target.value || null })}
          className="rounded border border-border bg-surface-raised px-2 py-1 text-sm text-ink"
        >
          <option value="">Any</option>
          {ARCHETYPES.map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Min confidence">
        <input
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={filters.minStateConfidence ?? ""}
          onChange={(event) =>
            update({ minStateConfidence: numberOrNull(event.target.value) })
          }
          className="w-20 rounded border border-border bg-surface-raised px-2 py-1 text-sm text-ink"
        />
      </Field>

      <Field label="Min Assets">
        <input
          type="number"
          min={0}
          value={filters.minAssets ?? ""}
          onChange={(event) => update({ minAssets: numberOrNull(event.target.value) })}
          className="w-20 rounded border border-border bg-surface-raised px-2 py-1 text-sm text-ink"
        />
      </Field>

      <Field label="Min Capabilities">
        <input
          type="number"
          min={0}
          value={filters.minCapabilities ?? ""}
          onChange={(event) =>
            update({ minCapabilities: numberOrNull(event.target.value) })
          }
          className="w-20 rounded border border-border bg-surface-raised px-2 py-1 text-sm text-ink"
        />
      </Field>

      <label className="flex items-center gap-2 pb-1 text-sm text-ink-muted">
        <input
          type="checkbox"
          checked={filters.acceleratingOnly}
          onChange={(event) => update({ acceleratingOnly: event.target.checked })}
        />
        Accelerating only
      </label>

      {active ? (
        <button
          type="button"
          onClick={() =>
            update({
              archetype: null,
              minStateConfidence: null,
              minAssets: null,
              minCapabilities: null,
              acceleratingOnly: false,
            })
          }
          className="ml-auto pb-1 text-sm text-ink-subtle underline underline-offset-2 hover:text-ink"
        >
          Clear
        </button>
      ) : null}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-subtle">
      <span className="uppercase tracking-wider">{label}</span>
      {children}
    </label>
  );
}
