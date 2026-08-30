import { useEffect, useRef, useState } from "react";

import { websocketUrl } from "./api_client";

/**
 * A websocket that reopens itself, shared by every live feed in the panel.
 *
 * The gateway restarts xray and dnsmasq while the panel is open, so a dropped
 * socket is normal operation rather than an error. This hook backs off between
 * attempts and reports the connection state so the UI can show a stale badge
 * instead of silently freezing.
 */

const RETRY_BASE_MS = 1000;
const RETRY_CEILING_MS = 15000;

export type SocketStatus = "connecting" | "open" | "closed";

/**
 * Subscribe to a websocket path, reconnecting for as long as the hook is
 * mounted.
 *
 * Args:
 *   path: An origin-relative websocket path such as `/ws/stats`. Passing null
 *     keeps the socket closed, which is how callers gate on a missing id.
 *   onMessage: Called with each parsed JSON frame. The latest callback is
 *     always used, so an inline arrow does not force a reconnect.
 *   onOpen: Called the moment the socket connects, before any frame reaches
 *     `onMessage`. Feeds that send a backlog first need this to tell that
 *     backlog apart from the incremental frames that follow it.
 *
 * Returns:
 *   The current connection status.
 */
export function useReconnectingSocket(
  path: string | null,
  onMessage: (message: unknown) => void,
  onOpen?: () => void,
): SocketStatus {
  const [status, setStatus] = useState<SocketStatus>("connecting");
  const messageHandlerRef = useRef(onMessage);
  const openHandlerRef = useRef(onOpen);

  useEffect(() => {
    messageHandlerRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    openHandlerRef.current = onOpen;
  }, [onOpen]);

  useEffect(() => {
    if (path === null) {
      setStatus("closed");
      return;
    }

    let socket: WebSocket | null = null;
    let retryTimer = 0;
    let attempt = 0;
    let isCancelled = false;

    const connect = () => {
      setStatus("connecting");
      socket = new WebSocket(websocketUrl(path));

      socket.onopen = () => {
        attempt = 0;
        openHandlerRef.current?.();
        setStatus("open");
      };

      socket.onmessage = (event: MessageEvent<unknown>) => {
        if (typeof event.data !== "string") {
          return;
        }
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data);
        } catch {
          return;
        }
        messageHandlerRef.current(parsed);
      };

      socket.onerror = () => {
        socket?.close();
      };

      socket.onclose = () => {
        if (isCancelled) {
          return;
        }
        setStatus("closed");
        attempt += 1;
        retryTimer = window.setTimeout(connect, retryDelayMs(attempt));
      };
    };

    connect();

    return () => {
      isCancelled = true;
      window.clearTimeout(retryTimer);
      if (socket !== null) {
        socket.onclose = null;
        socket.onerror = null;
        socket.close();
      }
    };
  }, [path]);

  return status;
}

function retryDelayMs(attempt: number): number {
  return Math.min(RETRY_BASE_MS * 2 ** (attempt - 1), RETRY_CEILING_MS);
}
