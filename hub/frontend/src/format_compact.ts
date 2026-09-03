/** Rendering large plain counts the way the usage widgets want them. */

const COMPACT_UNITS = ["", "K", "M", "B", "T"] as const;
const COMPACT_STEP = 1000;

/**
 * Format a count with a thousands-step unit: `985`, `38.5K`, `5.20B`.
 *
 * Args:
 *   value: The count. Negative and non-finite inputs collapse to zero, since
 *     they only ever come from a counter reset.
 *
 * Returns:
 *   A short string holding three significant digits above one thousand.
 */
export function formatCompact(value: number): string {
  const safe = Number.isFinite(value) && value > 0 ? value : 0;
  let scaled = safe;
  let unitIndex = 0;
  while (scaled >= COMPACT_STEP && unitIndex < COMPACT_UNITS.length - 1) {
    scaled /= COMPACT_STEP;
    unitIndex += 1;
  }
  if (unitIndex === 0) {
    return String(Math.round(scaled));
  }
  const decimals = scaled < 10 ? 2 : scaled < 100 ? 1 : 0;
  return `${scaled.toFixed(decimals)}${COMPACT_UNITS[unitIndex]}`;
}

/** Format a rate that sits near 1: `3.82`, `41.6`, then compact above 100. */
export function formatSmallRate(value: number): string {
  const safe = Number.isFinite(value) && value > 0 ? value : 0;
  if (safe < 10) {
    return safe.toFixed(2);
  }
  if (safe < 100) {
    return safe.toFixed(1);
  }
  return formatCompact(safe);
}
