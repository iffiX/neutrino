import { createContext } from "react";

import type { StatsSocketState } from "./use_stats_socket";

/**
 * The single live stats feed, shared by the shell and every page.
 *
 * The top bar and the dashboard both want the same frames. Publishing one
 * socket through context keeps the gateway serving a single `/ws/stats`
 * connection per open tab instead of one per interested component.
 */
export const StatsContext = createContext<StatsSocketState | null>(null);
