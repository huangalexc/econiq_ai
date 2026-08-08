"use client";

import { useAsOf } from "@/lib/as-of";
import { useLiveUpdates } from "@/lib/live";
import { cn } from "@/lib/utils";

import { SessionControl } from "./session-control";

import { AsOfControl } from "./as-of-control";
import { SearchBar } from "./search-bar";
import { Sidebar } from "./sidebar";
import { ThemeToggle } from "./theme-toggle";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { isHistorical, asOf } = useAsOf();
  // One subscription for the whole app rather than one per screen (#34).
  useLiveUpdates();

  return (
    <div className="flex h-dvh flex-col">
      <header
        className={cn(
          "flex items-center gap-4 border-b px-4 py-2.5 transition-colors",
          // Ambient rather than a badge: mistaking a reconstruction for the
          // present is worse than not having the feature at all (§2.3).
          isHistorical
            ? "border-estimated bg-estimated/10"
            : "border-border bg-surface",
        )}
      >
        <span className="font-mono text-sm font-semibold tracking-tight text-ink">
          econiq
        </span>
        <div className="flex flex-1 justify-center">
          <SearchBar />
        </div>
        <AsOfControl />
        <ThemeToggle />
        <SessionControl />
      </header>

      {isHistorical ? (
        <div
          role="status"
          className="border-b border-estimated bg-estimated/10 px-4 py-1.5 text-center text-xs text-ink"
        >
          Reconstructed view — showing what the system believed at{" "}
          <time dateTime={asOf ?? undefined} className="font-medium">
            {asOf}
          </time>
          . Evidence recorded after this instant is excluded.
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
