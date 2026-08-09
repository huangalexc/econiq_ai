"use client";

import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/lib/theme";

export function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const next = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className="rounded border border-border p-1.5 text-ink-muted hover:text-ink"
      aria-label={`Switch to ${next} theme`}
      // The pre-paint script may have set light before React hydrates, so the
      // icon legitimately differs between server and client markup.
      suppressHydrationWarning
    >
      {theme === "dark" ? (
        <Sun aria-hidden className="size-4" />
      ) : (
        <Moon aria-hidden className="size-4" />
      )}
    </button>
  );
}
