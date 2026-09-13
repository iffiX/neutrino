/** The theme the document carries, read from its tokens. */

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
