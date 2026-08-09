"use client";

/**
 * TanStack Query setup.
 *
 * The one non-default decision: `as_of` is part of every query key. Two reads
 * of the same Process at different cut-offs are different data, and a cache
 * that treated them as one would serve a July belief as today's — the exact
 * confusion the temporal model exists to prevent. Putting it in the key rather
 * than remembering to invalidate makes that structural.
 */

import { QueryClient } from "@tanstack/react-query";
import type { RequestOptions } from "./api/client";
import { ApiError } from "./api/client";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // The graph changes when the pipeline runs, not when the user clicks.
        staleTime: 30_000,
        retry: (failureCount, error) => {
          // A 404 is an answer. Retrying it three times delays the empty state
          // and tells the user nothing new.
          if (error instanceof ApiError && error.status < 500) return false;
          return failureCount < 2;
        },
      },
    },
  });
}

/** Query key that carries the cut-off, so history and now never share a cache entry. */
export function keyFor(
  parts: readonly (string | number | undefined)[],
  options?: Pick<RequestOptions, "asOf" | "query">,
) {
  return [...parts, options?.asOf ?? "now", options?.query ?? null] as const;
}
