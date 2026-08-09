"use client";

import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "econiq-theme";

/**
 * Theme as an external store rather than component state.
 *
 * The DOM is already the source of truth here: `THEME_INIT_SCRIPT` sets
 * `data-theme` before first paint so there is no flash of the wrong theme, and
 * the CSS tokens key off that attribute. Mirroring it into React state would
 * mean reading the DOM in an effect and calling `setState`, which renders the
 * wrong icon for one frame and is exactly the cascade the react-hooks rule
 * warns about. `useSyncExternalStore` reads the real value on both server and
 * client instead.
 */

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

/** The server renders dark, which is what the pre-paint script also defaults to. */
function getServerSnapshot(): Theme {
  return "dark";
}

export function setTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Private browsing and blocked storage: the theme still applies for this
    // session, it just will not be remembered. Not worth surfacing.
  }
  for (const listener of listeners) listener();
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return [theme, setTheme];
}

/**
 * Runs before first paint, inlined into the document head. Reading the stored
 * theme in a React effect instead would paint dark first and then correct
 * itself, which is the flash this exists to prevent.
 */
export const THEME_INIT_SCRIPT = `
try {
  var t = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
  document.documentElement.dataset.theme = t === "light" ? "light" : "dark";
} catch (e) {
  document.documentElement.dataset.theme = "dark";
}
`.trim();
