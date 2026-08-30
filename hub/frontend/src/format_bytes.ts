/** Rendering byte counts and byte rates the way a network panel wants them. */

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"] as const;
const BYTE_STEP = 1024;

/**
 * Format a byte count with a binary-step unit.
 *
 * Args:
 *   bytes: The count. Negative and non-finite inputs collapse to zero, since
 *     they only ever come from a counter reset.
 *
 * Returns:
 *   A short string such as `1.4 GB`.
 */
export function formatBytes(bytes: number): string {
  const safe = Number.isFinite(bytes) && bytes > 0 ? bytes : 0;
  let value = safe;
  let unitIndex = 0;
  while (value >= BYTE_STEP && unitIndex < BYTE_UNITS.length - 1) {
    value /= BYTE_STEP;
    unitIndex += 1;
  }
  const unit = BYTE_UNITS[unitIndex] ?? "B";
  const decimals = value < 10 && unitIndex > 0 ? 1 : 0;
  return `${value.toFixed(decimals)} ${unit}`;
}

/** Format a byte-per-second rate, for the live traffic readouts. */
export function formatByteRate(bytesPerSecond: number): string {
  return `${formatBytes(bytesPerSecond)}/s`;
}

/** Split a byte count into its number and unit, for tiles that style them. */
export function splitBytes(bytes: number): { value: string; unit: string } {
  const parts = formatBytes(bytes).split(" ");
  return { value: parts[0] ?? "0", unit: parts[1] ?? "B" };
}
