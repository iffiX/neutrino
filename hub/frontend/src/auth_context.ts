import { createContext } from "react";

import type { AuthState } from "./api_types";

/**
 * The session state shared by the whole panel.
 *
 * The context lives in its own module so the provider component and the
 * `useAuth` hook can each be the single export of their own file, and so a
 * fast-refresh reload of either does not tear down the context identity.
 */

export interface AuthContextValue {
  /** Whether the browser currently holds a valid session cookie. */
  isAuthenticated: boolean;
  /** True while the initial session probe is still in flight. */
  isChecking: boolean;
  /** Why the session probe failed, when the API could not be reached. */
  error: string | null;
  /**
   * Exchange a password for a session. Resolves with the state either way,
   * so the login page can tell a wrong password from a lockout; rejects only
   * when the gateway cannot be reached.
   */
  login: (password: string) => Promise<AuthState>;
  /** Drop the session on both sides. */
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
