import { apiGet } from "./api_client";
import type { AuthState } from "./api_types";

/**
 * Reloading the app when the panel behind it has restarted.
 *
 * A restart signs every session out and usually ships a new bundle, so a page
 * built by the old process must not keep running against the new one. Every
 * open tab probes `/api/auth/session` — it answers without a session and
 * carries `panel_started_at`, a constant per server process. The first
 * successful read is remembered; a later read with a different value reloads
 * the page, which lands on login with the new bundle. A read that fails means
 * the backend is unreachable, and says nothing about identity: the probe just
 * keeps asking, and the same value answering again is a network blip the open
 * sockets recover from on their own.
 */

const PANEL_IDENTITY_PROBE_INTERVAL_MS = 3000;

let probeHandle: number | null = null;
let knownStartedAt: string | null = null;
let isReloading = false;

/**
 * Start the identity probe for the life of the page.
 *
 * Idempotent: the first call arms one interval, later calls are no-ops. There
 * is no stop — the reset is the reload itself.
 */
export function startPanelIdentityWatch() {
  if (probeHandle !== null) {
    return;
  }
  probeHandle = window.setInterval(
    () => void probePanelIdentity(),
    PANEL_IDENTITY_PROBE_INTERVAL_MS,
  );
}

async function probePanelIdentity() {
  if (isReloading) {
    return;
  }
  let state: AuthState;
  try {
    state = await apiGet<AuthState>("/auth/session");
  } catch {
    return;
  }
  if (knownStartedAt === null) {
    knownStartedAt = state.panel_started_at;
    return;
  }
  if (state.panel_started_at !== knownStartedAt) {
    isReloading = true;
    window.location.reload();
  }
}
