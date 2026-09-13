/**
 * The palette every page is drawn in, and the tokens it resolves to.
 *
 * A theme is one file of colour tokens under `[data-theme="<name>"]`, and the
 * choice between them is panel-wide and lives on the box: the page reads it
 * from `/api/theme` before its first render and `setThemeChoice` moves every
 * open screen at once. The `system` choice follows the browser's scheme, and
 * follows it again each time the browser changes it.
 */

import { useSyncExternalStore } from "react";

/** The choices this panel offers. Anything else reads as the default. */
export const THEMES = ["system", "dark", "light"] as const;

export type Theme = (typeof THEMES)[number];

/** The palettes a page is drawn in once `system` has been answered. */
export type ResolvedTheme = "dark" | "light";

export const THEME_DEFAULT: Theme = "dark";

const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";

const listeners = new Set<() => void>();

let currentChoice: Theme = THEME_DEFAULT;
let currentTheme: ResolvedTheme = "dark";

/** The choice the box holds, which may be `system`. */
export function getThemeChoice(): Theme {
  return currentChoice;
}

/** The palette every page is drawn in right now. */
export function resolvedTheme(): ResolvedTheme {
  return currentTheme;
}

/**
 * Draw every open screen in this theme.
 *
 * A theme this panel does not have is the default, so a stored value from
 * another build cannot leave the page unstyled.
 */
export function setThemeChoice(choice: string): void {
  currentChoice = asTheme(choice);
  applyTheme();
}

/** The theme this name is, or the default where the panel has no such one. */
export function asTheme(theme: string): Theme {
  return (THEMES as readonly string[]).includes(theme)
    ? (theme as Theme)
    : THEME_DEFAULT;
}

/** The resolved theme, re-rendering the component when it changes. */
export function useTheme(): ResolvedTheme {
  return useSyncExternalStore(subscribe, resolvedTheme, resolvedTheme);
}

/**
 * Resolve one custom property on the document root.
 *
 * Args:
 *   name: The property, written with its leading dashes.
 *
 * Returns:
 *   The value the active theme gives it, or an empty string when no theme
 *   defines it.
 */
export function themeToken(name: string): string {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
}

window.matchMedia(DARK_SCHEME_QUERY).addEventListener("change", () => {
  if (currentChoice === "system") {
    applyTheme();
  }
});

function applyTheme(): void {
  const next: ResolvedTheme =
    currentChoice === "system" ? systemTheme() : currentChoice;
  document.documentElement.dataset.theme = next;
  // Read after the attribute, or the browser chrome takes the colour of the
  // theme the page is leaving.
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", themeToken("--color-bg"));
  if (next === currentTheme) {
    return;
  }
  currentTheme = next;
  for (const listener of listeners) {
    listener();
  }
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia(DARK_SCHEME_QUERY).matches ? "dark" : "light";
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}
