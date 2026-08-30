import { useContext } from "react";

import { StatsContext } from "./stats_context";
import type { StatsSocketState } from "./use_stats_socket";

const EMPTY_STATS: StatsSocketState = {
  frames: [],
  latestFrame: null,
  status: "closed",
};

/**
 * Read the shared live stats feed.
 *
 * Returns:
 *   The frames published by the app shell, or an empty closed feed when read
 *   outside it — the login screen renders without a stats socket, and should
 *   not crash for wanting one.
 */
export function useLiveStats(): StatsSocketState {
  return useContext(StatsContext) ?? EMPTY_STATS;
}
