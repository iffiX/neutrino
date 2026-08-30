import { useCallback, useRef, useState } from "react";

import { useReconnectingSocket } from "./use_reconnecting_socket";
import type { SocketStatus } from "./use_reconnecting_socket";
import type { DnsLogEntry } from "./api_types";

/**
 * The `/ws/dns_log` feed, kept newest-first and capped.
 *
 * dnsmasq on a busy LAN emits far more queries than anyone reads, so the hook
 * holds only the most recent slice. That cap is what keeps the dashboard list
 * cheap without needing a virtualised scroller.
 *
 * The two kinds of frame the backend sends are ordered differently and have
 * to be treated differently. On connect it sends the log tail already
 * newest-first, which is the authoritative view and replaces whatever the
 * hook held. Every later frame is the incremental follow, oldest-first, and is
 * reversed onto the front. Getting this wrong is invisible in the types and
 * shows up only as a list that reads backwards, so it is handled explicitly.
 */

const DNS_LOG_PATH = "/ws/dns_log";
const DEFAULT_ENTRY_LIMIT = 200;

export interface DnsLogSocketState {
  entries: DnsLogEntry[];
  status: SocketStatus;
}

/**
 * Subscribe to the live DNS query feed.
 *
 * Args:
 *   entryLimit: How many entries to retain, newest first.
 *
 * Returns:
 *   The retained entries newest-first and the socket status.
 */
export function useDnsLogSocket(
  entryLimit: number = DEFAULT_ENTRY_LIMIT,
): DnsLogSocketState {
  const [entries, setEntries] = useState<DnsLogEntry[]>([]);
  const isBacklogPendingRef = useRef(true);

  const handleOpen = useCallback(() => {
    isBacklogPendingRef.current = true;
  }, []);

  const handleMessage = useCallback(
    (message: unknown) => {
      const incoming = readEntries(message);
      if (incoming.length === 0) {
        return;
      }
      const isBacklog = isBacklogPendingRef.current;
      isBacklogPendingRef.current = false;
      const newestFirst = isBacklog ? incoming : [...incoming].reverse();

      setEntries((previous) =>
        isBacklog
          ? newestFirst.slice(0, entryLimit)
          : newestFirst.concat(previous).slice(0, entryLimit),
      );
    },
    [entryLimit],
  );

  const status = useReconnectingSocket(DNS_LOG_PATH, handleMessage, handleOpen);

  return { entries, status };
}

function readEntries(message: unknown): DnsLogEntry[] {
  if (typeof message !== "object" || message === null) {
    return [];
  }
  const frame = message as Record<string, unknown>;
  if (!Array.isArray(frame.entries)) {
    return [];
  }
  return frame.entries.filter(isDnsLogEntry);
}

function isDnsLogEntry(value: unknown): value is DnsLogEntry {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.timestamp === "string" &&
    typeof entry.domain === "string" &&
    typeof entry.client === "string"
  );
}
