/** Validating and normalising the MAC addresses the panel accepts. */

const MAC_PATTERN = /^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i;
const MAC_SEPARATORS = /[-.\s]/g;

/** Whether a string is a colon-separated 48-bit MAC address. */
export function isMacAddress(value: string): boolean {
  return MAC_PATTERN.test(normaliseMac(value));
}

/**
 * Normalise a MAC address to lowercase colon-separated form.
 *
 * Args:
 *   value: A MAC written with colons, dashes, dots or spaces.
 *
 * Returns:
 *   The lowercase colon-separated form. Input that is not a MAC comes back
 *   trimmed and lowercased so the caller can still show what was typed.
 */
export function normaliseMac(value: string): string {
  return value.trim().toLowerCase().replace(MAC_SEPARATORS, ":");
}

/** The OUI portion of a MAC, used as a stable colour seed for device tiles. */
export function macSeed(value: string): number {
  let seed = 0;
  for (const character of normaliseMac(value)) {
    seed = (seed * 31 + character.charCodeAt(0)) >>> 0;
  }
  return seed;
}
