"use client";

/**
 * Attaching the session to API calls (issue #19).
 *
 * The token is fetched per request rather than held in a module variable.
 * Clerk's session tokens are short-lived and refresh in the background; a cached
 * one would work for a minute and then start failing in a way that looks like an
 * API outage.
 *
 * Reads of the graph work without a token, so a failure to get one is not an
 * error — it means signed out, and the request goes anyway (PRD §23).
 */

import { useAuth } from "@clerk/nextjs";
import { useCallback } from "react";

import { setTokenSource } from "./client";

export function useAttachSession() {
  const { getToken, isLoaded } = useAuth();

  return useCallback(() => {
    if (!isLoaded) return;
    setTokenSource(async () => {
      try {
        return await getToken();
      } catch {
        return null;
      }
    });
  }, [getToken, isLoaded]);
}
