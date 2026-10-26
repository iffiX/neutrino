import { useEffect, useRef } from "react";

/**
 * Escape closes the topmost modal, and only it.
 *
 * Every modal joins one stack while it is mounted; one listener hands
 * Escape to the modal mounted last, so a confirmation or a path window over
 * a dialog closes alone and the dialog underneath stays. An open picker
 * takes Escape before any modal does (`picker.tsx`).
 */

const layers: Array<{ current: () => void }> = [];

if (typeof document !== "undefined") {
  document.addEventListener("keydown", takeEscape, true);
}

function takeEscape(event: KeyboardEvent): void {
  const layer = layers.at(-1);
  if (event.key !== "Escape" || layer === undefined) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  layer.current();
}

/**
 * Join the stack of modals for as long as the caller is mounted.
 *
 * Args:
 *   onEscape: What Escape does while this modal is the topmost one; null
 *     for a modal whose keyboard belongs to what it holds.
 */
export function useEscapeLayer(onEscape: (() => void) | null): void {
  const handler = useRef<() => void>(() => undefined);
  handler.current = onEscape ?? (() => undefined);
  const isTaken = onEscape !== null;

  useEffect(() => {
    if (!isTaken) {
      return;
    }
    const layer = handler;
    layers.push(layer);
    return () => {
      const index = layers.lastIndexOf(layer);
      if (index >= 0) {
        layers.splice(index, 1);
      }
    };
  }, [isTaken]);
}
