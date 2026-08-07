"use client";

/**
 * The point-in-time cut-off, held for the whole application (ui_concept §2.3).
 *
 * "Temporal state is first-class" is a product principle, not a feature of one
 * screen. If each screen kept its own cut-off, moving from a Process to the
 * Asset it implies would silently jump back to the present, and the user would
 * be reading a July thesis against today's evidence without being told.
 *
 * Kept in the URL rather than in React state alone. A reconstructed view is
 * something people send to each other — "look at what it believed before the
 * announcement" — and a cut-off that cannot be linked to is a cut-off that gets
 * screenshotted instead.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useMemo } from "react";

export interface AsOfState {
  /** ISO instant, or null for "now". */
  asOf: string | null;
  setAsOf: (value: string | null) => void;
  isHistorical: boolean;
}

const AsOfContext = createContext<AsOfState | null>(null);

export const AS_OF_PARAM = "as_of";

export function AsOfProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get(AS_OF_PARAM);

  // An unparseable cut-off is treated as absent rather than passed through. The
  // API would reject it, but every screen would report the error separately and
  // none of them would say the reason was a malformed URL.
  const asOf = useMemo(() => {
    if (!raw) return null;
    return Number.isNaN(Date.parse(raw)) ? null : raw;
  }, [raw]);

  const setAsOf = useCallback(
    (value: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(AS_OF_PARAM, value);
      else next.delete(AS_OF_PARAM);
      const query = next.toString();
      router.push(query ? `?${query}` : "?", { scroll: false });
    },
    [params, router],
  );

  const value = useMemo(
    () => ({ asOf, setAsOf, isHistorical: asOf !== null }),
    [asOf, setAsOf],
  );

  return <AsOfContext.Provider value={value}>{children}</AsOfContext.Provider>;
}

export function useAsOf(): AsOfState {
  const context = useContext(AsOfContext);
  if (!context) {
    throw new Error("useAsOf must be used inside AsOfProvider");
  }
  return context;
}
