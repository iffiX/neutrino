import { useCallback, useEffect, useState } from "react";

import { apiGet, describeError } from "./api_client";

/**
 * Load one GET endpoint into component state.
 *
 * Every page uses this so a backend that is down degrades to a readable inline
 * error with a retry, never to a blank screen. Keeping the error as a string
 * rather than the thrown value means the render path cannot itself throw.
 */

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
 *
 * Returns:
 *   The loaded value, a load error, the in-flight flag, a reload trigger, and
 *   a setter so a page can fold a mutation response back in without refetching.
 */
export function useApiResource<T>(path: string | null): ApiResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(path !== null);
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
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
        setData(value);
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

  return { data, error, isLoading, reload, setData };
}
