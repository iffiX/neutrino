import { apiGet } from "./api_client";
import type { AuthState } from "./api_types";

/**
 * Reloading the app when the panel behind it has restarted.
 *
 * A restart signs every session out and usually ships a new bundle, so a page
 * built by the old process must not keep running against the new one.
 * `/api/hub/auth/session` answers without a session and carries
 * `panel_started_at`, a constant per server process. The first value read is
 * remembered; a later one that differs reloads the page onto the new bundle.
 *
 * It is read at the moments a restart can have happened unseen: each time the
 * event socket opens, since a restart always drops it; when the tab comes
 * back to the front; when the login page loads; and after a login, before the
 * page moves on. A read that fails says nothing about identity.
 */

let knownStartedAt: string | null = null;
let isReloading = false;
let isWatching = false;

/**
 * Probe once when the tab comes back to the front, for the life of the page.
 *
 * Idempotent: the first call adds the listener, later calls are no-ops.
 */
export function startPanelIdentityWatch() {
  if (isWatching) {
    return;
  }
  isWatching = true;
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      void probePanelIdentity();
    }
  });
}

/**
 * Read the panel's identity once, and reload when it changed.
 *
 * Returns:
 *   True when the page is reloading onto a restarted panel.
 */
export async function probePanelIdentity(): Promise<boolean> {
  if (isReloading) {
    return true;
  }
  let state: AuthState;
  try {
    state = await apiGet<AuthState>("/hub/auth/session");
  } catch {
    return false;
  }
  return notePanelIdentity(state);
}

/**
 * Hold a session answer read elsewhere against the identity remembered.
 *
 * Args:
 *   state: An answer of `/api/hub/auth/session`.
 *
 * Returns:
 *   True when the page is reloading onto a restarted panel.
 */
export function notePanelIdentity(state: AuthState): boolean {
  if (isReloading) {
    return true;
  }
  if (knownStartedAt === null) {
    knownStartedAt = state.panel_started_at;
    return false;
  }
  if (state.panel_started_at !== knownStartedAt) {
    isReloading = true;
    window.location.reload();
    return true;
  }
  return false;
}
