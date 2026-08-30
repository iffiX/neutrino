import { useContext } from "react";

import { AuthContext } from "./auth_context";
import type { AuthContextValue } from "./auth_context";

/**
 * Read the session state.
 *
 * Returns:
 *   The auth context value.
 *
 * Raises:
 *   Error: When called outside `AuthProvider`, which is always a wiring bug
 *     rather than a runtime condition worth rendering around.
 */
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}
