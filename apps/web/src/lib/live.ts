"use client";

/**
 * Live updates (issue #34, ui_concept §31).
 *
 * Subscribes to the API's SSE stream and invalidates the matching TanStack
 * Query caches. The stream carries *what changed*, never the changed rows —
 * pushing data would give two paths to every value, and they diverge the first
 * time one is read at a different `as_of`. An invalidation cannot go stale.
 *
 * **Historical views are not invalidated.** When a cut-off is set the screen is
 * a reconstruction of a past instant, and by definition nothing happening now
 * changes it. Refetching would be wrong as well as wasteful: the reader would
 * watch a "what did we believe in July" view move.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { API_BASE_URL } from "./api/client";
import { useAsOf } from "./as-of";

interface ChangeEvent {
  name: string;
  subject_id: string | null;
  invalidates: string[];
  at: string;
}

export function useLiveUpdates() {
  const queryClient = useQueryClient();
  const { isHistorical } = useAsOf();

  useEffect(() => {
    if (isHistorical) return;
    if (typeof window === "undefined" || !("EventSource" in window)) return;

    // No credentials: the stream carries no workspace data, only the names of
    // things that changed in a graph that is public anyway (PRD §23). That is
    // also why it needs no token — EventSource cannot send one.
    const source = new EventSource(`${API_BASE_URL}/api/stream`);

    source.addEventListener("change", (message) => {
      let change: ChangeEvent;
      try {
        change = JSON.parse((message as MessageEvent<string>).data);
      } catch {
        return;
      }
      for (const key of change.invalidates) {
        // Prefix match: `["process", id, …]` and `["process", id, "timeline"]`
        // are both stale when a Process moves, and enumerating every suffix
        // here would mean a new query silently stops updating.
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
    });

    // EventSource reconnects on its own with Last-Event-ID, so an error is
    // usually a blip. Logging every one would be noise; failing loudly would be
    // wrong for a feature the page works without.
    source.onerror = () => {};

    return () => source.close();
  }, [queryClient, isHistorical]);
}
