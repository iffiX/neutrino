import { useCallback, useRef } from "react";

/**
 * When a polled payload is allowed to take over a form.
 *
 * A panel that polls seeds its draft from what the box holds, and a payload
 * landing under a form somebody is filling in must not carry their edit away.
 * A draft still reading the same as the payload it was seeded from holds
 * nothing of theirs, and neither does one that already reads the same as what
 * just arrived; anything else waits for Apply or Reset.
 *
 * Comparing against the seed and not only against the newest payload is what
 * keeps an untouched form following the box: a value changed somewhere else
 * lands in it, rather than leaving it lit and claiming an edit nobody made.
 */

/**
 * Follow one panel's draft against what the box holds.
 *
 * Args:
 *   draftPayload: The draft as it stands, serialized; null where the panel
 *     holds none yet.
 *   appliedPayload: The same fields as the box holds them, serialized; null
 *     before anything has loaded.
 *
 * Returns:
 *   What the seeding effect asks about the payload that just arrived: whether
 *   seeding the form from it loses nothing anybody typed.
 */
export function useDraftSeeding(
  draftPayload: string | null,
  appliedPayload: string | null,
): (freshPayload: string) => boolean {
  const draftRef = useRef<string | null>(null);
  const seedRef = useRef<string | null>(null);
  draftRef.current = draftPayload;
  // A draft reading the same as the box agrees with it — an apply landed, or
  // Reset was pressed — and the next payload seeds the form like any other.
  if (appliedPayload !== null && draftPayload === appliedPayload) {
    seedRef.current = appliedPayload;
  }

  return useCallback(
    (freshPayload: string) =>
      draftRef.current === null ||
      draftRef.current === seedRef.current ||
      draftRef.current === freshPayload,
    [],
  );
}
