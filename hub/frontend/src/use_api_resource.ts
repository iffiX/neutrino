import { useCallback, useEffect, useRef, useState } from "react";

import { apiGet, describeError } from "./api_client";
import { useHubEvents } from "./use_hub_events";
import type { HubEventMatch } from "./use_hub_events";

/**
 * Load one GET endpoint into component state.
 *
 * Every page uses this so a backend that is down degrades to a readable inline
 * error with a retry, never to a blank screen. Keeping the error as a string
 * rather than the thrown value means the render path cannot itself throw.
 *
 * A fetch bringing back what the page already holds is dropped: the value
 * keeps its identity, so nothing keyed on it re-runs and a form seeded from it
 * is left alone. An event that fires often therefore costs a request and
 * nothing else.
 */

export interface ApiResourceOptions {
  /**
   * Refetch when one of these hub events arrives. A match with no key takes
   * every key of its type.
   */
  invalidateOn?: HubEventMatch[];
}

export interface ApiResource<T> {
  data: T | null;
  error: string | null;
  isLoading: boolean;
  reload: () => void;
  setData: (value: T) => void;
}

/**
 * Fetch and hold one API resource.
 *
 * Args:
 *   path: The API path below `/api`, including any query string. Passing null
 *     skips the request, which is how a drawer defers loading until it opens.
 *   options: `invalidateOn` names the hub events that make this refetch.
 *
 * Returns:
 *   The loaded value, a load error, the in-flight flag, a reload trigger, and
 *   a setter so a page can fold a mutation response back in without refetching.
 */
export function useApiResource<T>(
  path: string | null,
  options: ApiResourceOptions = {},
): ApiResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(path !== null);
  const [reloadNonce, setReloadNonce] = useState(0);
  // What is on screen, serialized. A fetch compares against this rather than
  // against its own last answer, so a value the page folded in itself — a
  // mutation response — counts as held too.
  const heldPayloadRef = useRef<string | null>(null);
  const heldPathRef = useRef<string | null>(path);

  useEffect(() => {
    if (heldPathRef.current !== path) {
      heldPathRef.current = path;
      heldPayloadRef.current = null;
    }
    if (path === null) {
      setIsLoading(false);
      return;
    }
    let isCancelled = false;
    setIsLoading(true);

    apiGet<T>(path)
      .then((value) => {
        if (isCancelled) {
          return;
        }
        const payload = JSON.stringify(value);
        if (payload !== heldPayloadRef.current) {
          heldPayloadRef.current = payload;
          setData(value);
        }
        setError(null);
      })
      .catch((cause: unknown) => {
        if (isCancelled) {
          return;
        }
        setError(describeError(cause));
      })
      .finally(() => {
        if (!isCancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [path, reloadNonce]);

  const reload = useCallback(() => {
    setReloadNonce((nonce) => nonce + 1);
  }, []);

  const replaceData = useCallback((value: T) => {
    heldPayloadRef.current = JSON.stringify(value);
    setData(value);
  }, []);

  useHubEvents(options.invalidateOn ?? [], reload);

  return { data, error, isLoading, reload, setData: replaceData };
}
