import { createContext, useCallback, useMemo, useRef, useState } from "react";

/**
 * The rows typed into one frame's list editors and not added yet.
 *
 * Each `StringListEditor` holds its typed row here while its input is not
 * blank, and the frame's `ApplyBar` reads it: a typed row lights the bar,
 * Apply adds every row first as Add does, and Reset empties the inputs.
 */

/** One editor's typed row: its add, as Add makes it, and its emptying. */
export interface UnaddedRow {
  add: () => void;
  clear: () => void;
}

export interface UnaddedRows {
  /** Whether an editor of the frame holds a typed row. */
  hasRows: boolean;
  /** Keep an editor's typed row by the editor's id; null drops it. */
  hold: (id: string, row: UnaddedRow | null) => void;
  /** Add every typed row to its list. */
  addAll: () => void;
  /** Empty every editor's input. */
  clearAll: () => void;
}

/** The frame's record; null outside a frame, where a typed row is no change. */
export const UnaddedRowsContext = createContext<UnaddedRows | null>(null);

/**
 * Hold the typed rows of one frame.
 *
 * Returns:
 *   The record a frame hands its editors and its bar through
 *   `UnaddedRowsContext`.
 */
export function useUnaddedRows(): UnaddedRows {
  const held = useRef(new Map<string, UnaddedRow>());
  const [count, setCount] = useState(0);

  const hold = useCallback((id: string, row: UnaddedRow | null) => {
    if (row === null) {
      held.current.delete(id);
    } else {
      held.current.set(id, row);
    }
    setCount(held.current.size);
  }, []);

  const addAll = useCallback(() => {
    for (const row of [...held.current.values()]) {
      row.add();
    }
  }, []);

  const clearAll = useCallback(() => {
    for (const row of [...held.current.values()]) {
      row.clear();
    }
  }, []);

  return useMemo(
    () => ({ hasRows: count > 0, hold, addAll, clearAll }),
    [count, hold, addAll, clearAll],
  );
}
