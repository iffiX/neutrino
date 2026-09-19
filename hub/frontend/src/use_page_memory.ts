import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

/**
 * State a page keeps between visits.
 *
 * A routed page is unmounted while another page shows and mounted again on
 * the way back, so its own `useState` starts over each time. What a person
 * was looking at, the machine picked, the tab open, the directory browsed,
 * is kept here instead: one map that lives as long as the loaded panel and
 * is empty again after a reload. Nothing is written to the browser's
 * storage, so a reload is the clean start it reads as.
 */

const memory = new Map<string, unknown>();

/**
 * `useState` whose value is read back on the next mount under the same key.
 *
 * Args:
 *   key: What the value is, unique across the panel: `files.device`,
 *     `modules.tab`.
 *   initial: The value on the first mount since the panel loaded.
 */
export function usePageMemory<T>(
  key: string,
  initial: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() =>
    memory.has(key) ? (memory.get(key) as T) : initial,
  );
  useEffect(() => {
    memory.set(key, value);
  }, [key, value]);
  return [value, setValue];
}
