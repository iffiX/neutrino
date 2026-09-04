import { useEffect, useRef } from "react";

import { apiGet } from "./api_client";
import { useApiResource } from "./use_api_resource";
import type { ApiResource } from "./use_api_resource";

/**
 * A GET resource that refreshes itself on a fixed interval.
 *
 * Sections showing live state poll quietly instead of carrying a reload
 * button. A failed tick keeps the last good value on screen and the next
 * tick tries again, so a restarting backend flickers nothing.
 *
 * A tick bringing back what the page already holds is dropped: the value keeps
 * its identity, so nothing keyed on it re-runs and a form seeded from it is
 * left alone. A box where nothing is happening therefore renders nothing.
 *
 * A hidden tab stops asking and catches up when it comes back, so a panel
 * left open in a background tab costs the gateway nothing.
 */

export const DEFAULT_POLL_INTERVAL_MS = 15000;

/**
 * Fetch one API resource and keep it fresh.
 *
 * Args:
 *   path: The API path below `/api`; null skips fetching and polling.
 *   intervalMs: How often to refresh.
 *
 * Returns:
 *   The same shape `useApiResource` returns.
 */
export function usePolledResource<T>(
  path: string | null,
  intervalMs: number = DEFAULT_POLL_INTERVAL_MS,
): ApiResource<T> {
  const resource = useApiResource<T>(path);
  const { data, setData } = resource;
  // What is on screen, serialized. A tick compares against this rather than
  // against its own last answer, so a value the page folded in itself — a
  // mutation response — counts as held too.
  const heldPayloadRef = useRef<string | null>(null);

  useEffect(() => {
    heldPayloadRef.current = data === null ? null : JSON.stringify(data);
  }, [data]);

  useEffect(() => {
    if (path === null) {
      return;
    }
    let isCancelled = false;
    const tick = async () => {
      try {
        const fresh = await apiGet<T>(path);
        if (isCancelled) {
          return;
        }
        const payload = JSON.stringify(fresh);
        if (payload === heldPayloadRef.current) {
          return;
        }
        heldPayloadRef.current = payload;
        setData(fresh);
      } catch {
        // A transient failure keeps the last reading; the next tick retries.
      }
    };
    const tickWhenVisible = () => {
      if (!document.hidden) {
        void tick();
      }
    };
    const handle = window.setInterval(tickWhenVisible, intervalMs);
    // A tab that has been hidden is showing a stale reading; catch it up the
    // moment it is looked at again rather than a whole interval later.
    document.addEventListener("visibilitychange", tickWhenVisible);
    return () => {
      isCancelled = true;
      window.clearInterval(handle);
      document.removeEventListener("visibilitychange", tickWhenVisible);
    };
  }, [path, intervalMs, setData]);

  return resource;
}
