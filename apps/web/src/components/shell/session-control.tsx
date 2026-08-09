"use client";

/**
 * Sign-in state in the header (issue #19).
 *
 * Signed out is a normal, useful state here rather than a wall — the research
 * graph is public by design (PRD §23) — so this is a quiet control rather than
 * a call to action. What signing in adds is a watchlist, and the copy says
 * exactly that instead of implying the terminal is locked.
 */

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";

export function SessionControl() {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) return null;

  if (!isSignedIn) {
    return (
      <SignInButton mode="modal">
        <button
          type="button"
          className="rounded border border-border px-2 py-1 text-xs text-ink-muted hover:text-ink"
          title="Signing in adds a watchlist. Everything else is readable without one."
        >
          Sign in
        </button>
      </SignInButton>
    );
  }

  return <UserButton />;
}
