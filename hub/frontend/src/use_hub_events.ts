import { useEffect, useRef } from "react";

import { useReconnectingSocket } from "./use_reconnecting_socket";
import type { SocketStatus } from "./use_reconnecting_socket";

/**
 * The panel's one event socket, and how a component listens on it.
 *
 * The hub pushes a hint whenever something a page draws has moved, and the
 * page asks for that resource again. Nothing in the panel polls: the shell
 * opens this socket once and every component subscribes to the types it
 * cares about. A reading redrawn several times a minute rides the event as
 * `data` instead, so `metrics` needs no request at all.
 *
 * A reconnection means whatever moved while the socket was down went unheard,
 * so it is delivered as `HUB_EVENT_ANY`, which every listener takes.
 */

/** What the hub says moved, and the reading it carries where it carries one. */
export interface HubEvent {
  type: string;
  key: string;
  at: string;
  data?: unknown;
}

/** Which events a listener wants: a type, and one key of it where it cares. */
export interface HubEventMatch {
  type: string;
  key?: string;
}

/** The frame the socket opens with. */
export const HUB_EVENT_HELLO = "hello";

/** The device list moved: a machine came or went, was named, forgotten, or
 * had an action started on it. */
export const HUB_EVENT_DEVICES = "devices";

/** One machine's report says something new about what it runs. Keyed by MAC. */
export const HUB_EVENT_DEVICE_REPORT = "device_report";

/** An install or uninstall on one machine changed state. Keyed by MAC. */
export const HUB_EVENT_MODULE_ORDER = "module_order";

/** The published service list composes differently. */
export const HUB_EVENT_SERVICES = "services";

/** One file under `config/` was written. Keyed by its path below `config/`. */
export const HUB_EVENT_CONFIG = "config";

/** A background job started or finished. Keyed by its task id. */
export const HUB_EVENT_TASK = "task";

/** One machine's vitals, on every heartbeat. Keyed by MAC, and the only type
 * that carries its reading in `data`. */
export const HUB_EVENT_METRICS = "metrics";

/** An interface's carrier, address or radio reading moved. */
export const HUB_EVENT_LINKS = "links";

/** An exit node's latency or traffic reading moved. */
export const HUB_EVENT_NODES = "nodes";

/** The AI gateway's counters or served model list moved. */
export const HUB_EVENT_AI_USAGE = "ai_usage";

/** The type every listener takes, delivered after a reconnection. */
export const HUB_EVENT_ANY = "*";

const listeners = new Set<(event: HubEvent) => void>();

let isGreeted = false;

/**
 * Open the panel's one event socket. The shell calls this, and nothing else.
 *
 * Returns:
 *   The connection status, for a strip that shows it.
 */
export function useHubEventChannel(): SocketStatus {
  useEffect(() => {
    isGreeted = false;
    return () => {
      isGreeted = false;
    };
  }, []);
  return useReconnectingSocket("/ws/events", receive);
}

/**
 * Call a handler whenever one of the wanted events arrives.
 *
 * Args:
 *   matches: The types to listen for. A match with no key takes every key
 *     of its type.
 *   onEvent: Called with each matching event. The latest handler is always
 *     used, so an inline arrow costs nothing.
 */
export function useHubEvents(
  matches: HubEventMatch[],
  onEvent: (event: HubEvent) => void,
): void {
  const matchesRef = useRef(matches);
  const handlerRef = useRef(onEvent);

  useEffect(() => {
    matchesRef.current = matches;
  }, [matches]);

  useEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    const listener = (event: HubEvent) => {
      if (isWanted(matchesRef.current, event)) {
        handlerRef.current(event);
      }
    };
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
}

/** Route one frame from the socket to whoever asked for it. */
function receive(message: unknown): void {
  const event = toHubEvent(message);
  if (event === null) {
    return;
  }
  if (event.type !== HUB_EVENT_HELLO) {
    deliver(event);
    return;
  }
  if (!isGreeted) {
    isGreeted = true;
    return;
  }
  deliver({ type: HUB_EVENT_ANY, key: "", at: event.at });
}

function deliver(event: HubEvent): void {
  for (const listener of [...listeners]) {
    listener(event);
  }
}

function isWanted(matches: HubEventMatch[], event: HubEvent): boolean {
  if (event.type === HUB_EVENT_ANY) {
    return matches.length > 0;
  }
  return matches.some(
    (match) =>
      match.type === event.type &&
      (match.key === undefined || match.key === event.key),
  );
}

function toHubEvent(message: unknown): HubEvent | null {
  if (typeof message !== "object" || message === null) {
    return null;
  }
  const frame = message as Partial<HubEvent>;
  if (typeof frame.type !== "string") {
    return null;
  }
  return {
    type: frame.type,
    key: typeof frame.key === "string" ? frame.key : "",
    at: typeof frame.at === "string" ? frame.at : "",
    data: frame.data,
  };
}
