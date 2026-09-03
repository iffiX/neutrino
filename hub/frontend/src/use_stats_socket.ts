import { useCallback, useState } from "react";

import { useReconnectingSocket } from "./use_reconnecting_socket";
import type { SocketStatus } from "./use_reconnecting_socket";
import type { StatsFrame } from "./api_types";

/**
 * The `/ws/stats` feed, kept as a rolling window of frames.
 *
 * The backend pushes a frame every second, so the default window of 120
 * frames is the last two minutes the dashboard chart draws.
 */

const STATS_PATH = "/ws/stats";
const DEFAULT_FRAME_LIMIT = 120;

export interface StatsSocketState {
  frames: StatsFrame[];
  latestFrame: StatsFrame | null;
  status: SocketStatus;
}

/**
 * Subscribe to the live stats feed.
 *
 * Args:
 *   frameLimit: How many frames to keep. Older frames fall off the front.
 *
 * Returns:
 *   The retained frames oldest-first, the newest frame on its own, and the
 *   socket status.
 */
export function useStatsSocket(
  frameLimit: number = DEFAULT_FRAME_LIMIT,
): StatsSocketState {
  const [frames, setFrames] = useState<StatsFrame[]>([]);

  const handleMessage = useCallback(
    (message: unknown) => {
      if (!isStatsFrame(message)) {
        return;
      }
      setFrames((previous) => [...previous, message].slice(-frameLimit));
    },
    [frameLimit],
  );

  const status = useReconnectingSocket(STATS_PATH, handleMessage);
  const latestFrame =
    frames.length > 0 ? (frames[frames.length - 1] ?? null) : null;

  return { frames, latestFrame, status };
}

function isStatsFrame(value: unknown): value is StatsFrame {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const frame = value as Record<string, unknown>;
  return (
    typeof frame.timestamp === "string" &&
    typeof frame.cpu_percent === "number" &&
    typeof frame.memory_percent === "number" &&
    Array.isArray(frame.outbounds) &&
    Array.isArray(frame.nodes)
  );
}
