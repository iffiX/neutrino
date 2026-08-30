import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  apiGet,
  apiPost,
  describeError,
  setUnauthorizedHandler,
} from "./api_client";
import { AuthContext } from "./auth_context";
import type { AuthContextValue } from "./auth_context";
import type { AuthState } from "./api_types";

/**
 * Owns the session and turns any 401 anywhere in the app into a logout.
 *
 * The panel has exactly one credential, so there is no user object to hold —
 * only whether the cookie the backend set is still good. Registering the
 * unauthorized handler here means a session that expires while the dashboard
 * sits open drops straight back to the login card instead of filling the page
 * with failed requests.
 */

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isChecking, setIsChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => setIsAuthenticated(false));
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    let isCancelled = false;
    apiGet<AuthState>("/auth/session")
      .then((state) => {
        if (!isCancelled) {
          setIsAuthenticated(state.is_authenticated);
          setError(null);
        }
      })
      .catch((cause: unknown) => {
        if (!isCancelled) {
          setIsAuthenticated(false);
          setError(describeError(cause));
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setIsChecking(false);
        }
      });
    return () => {
      isCancelled = true;
    };
  }, []);

  const login = useCallback(async (password: string) => {
    const state = await apiPost<AuthState>("/auth/login", { password });
    if (state.is_authenticated) {
      setIsAuthenticated(true);
      setError(null);
    }
    return state;
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiPost<AuthState>("/auth/logout");
    } finally {
      setIsAuthenticated(false);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ isAuthenticated, isChecking, error, login, logout }),
    [isAuthenticated, isChecking, error, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
