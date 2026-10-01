import { useState } from "react";
import type { SetStateAction } from "react";

/**
 * One panel's draft of what the box holds.
 *
 * The draft follows the saved value while it reads the same as the saved value
 * it was last compared with. Once the person changes it, a refresh leaves it
 * alone until Apply makes the saved value read the same, or Reset puts it back.
 */

export interface Draft<D> {
  /** The draft as it stands; null until the saved value first arrives. */
  draft: D | null;
  setDraft: (next: SetStateAction<D>) => void;
  /** Whether the draft reads differently from the saved value. */
  isDirty: boolean;
  /** Return the draft to the saved value. */
  reset: () => void;
}

interface DraftState<D> {
  draft: D | null;
  /** The saved value as a draft, serialized; null before it first arrives. */
  snapshot: string | null;
}

/**
 * Hold a draft seeded from a saved value.
 *
 * Args:
 *   saved: The saved value as the gateway holds it; null before it loads.
 *   draftOf: The draft fields of a saved value.
 *
 * Returns:
 *   The draft, its setter, whether it differs from the saved value, and the
 *   reset that returns it to the saved value.
 */
export function useDraft<S, D>(
  saved: S | null,
  draftOf: (saved: S) => D,
): Draft<D> {
  const savedDraft = saved === null ? null : draftOf(saved);
  const savedSnapshot = savedDraft === null ? null : JSON.stringify(savedDraft);
  const [state, setState] = useState<DraftState<D>>({
    draft: savedDraft,
    snapshot: savedSnapshot,
  });

  let current = state;
  if (savedSnapshot !== null && savedSnapshot !== state.snapshot) {
    current = {
      draft: isDraftDirty(state) ? state.draft : savedDraft,
      snapshot: savedSnapshot,
    };
    setState(current);
  }

  const setDraft = (next: SetStateAction<D>) => {
    setState((held) => {
      if (!(next instanceof Function)) {
        return { ...held, draft: next };
      }
      return held.draft === null ? held : { ...held, draft: next(held.draft) };
    });
  };

  const reset = () => {
    setState({ draft: savedDraft, snapshot: savedSnapshot });
  };

  return {
    draft: current.draft,
    setDraft,
    isDirty: isDraftDirty(current),
    reset,
  };
}

function isDraftDirty<D>(state: DraftState<D>): boolean {
  return state.draft !== null && JSON.stringify(state.draft) !== state.snapshot;
}
