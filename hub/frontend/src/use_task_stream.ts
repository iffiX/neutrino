import { useEffect, useRef, useState } from "react";

import { websocketUrl } from "./api_client";
import type { StreamServerMessage } from "./api_types";

/**
 * Follow one device action to completion over `/ws/task/{task_id}`.
 *
 * A socket that closes without a result is not a finished task: the panel
 * restarting drops every socket it holds while the jobs behind them carry on.
 * The stream replays a job's whole log to whoever subscribes, so the hook
 * reopens once and starts the log again from the replay. A second close with
 * no result is reported, and the task is left in a state the page can close.
 *
 * It never reconnects after a result: the job is over, and reopening would
 * only redraw a log the person has already read.
 */

const MAX_LOG_LINES = 2000;
const RECONNECT_LIMIT = 1;
// A panel that is restarting accepts the TCP connection but never finishes the
// websocket handshake, and the browser's socket has no timeout of its own: it
// sits in CONNECTING forever. That is a task the page must be able to leave, so
// a socket that has not opened in this long is treated as a close.
const OPEN_TIMEOUT_MS = 8000;

export interface TaskStreamState {
  lines: string[];
  isRunning: boolean;
  exitCode: number | null;
  error: string | null;
}

/**
 * Stream a task's output.
 *
 * Args:
 *   taskId: The id returned by the device action endpoint, or null when no
 *     action is in flight.
 *
 * Returns:
 *   The output lines so far, whether the task is still running, its exit code
 *   once it finishes, and a transport error when the socket dies early.
 */
export function useTaskStream(taskId: string | null): TaskStreamState {
  const [lines, setLines] = useState<string[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The completed lines, and the partial last line a chunk may end mid-way
  // through. Each output chunk already carries its own newlines, so lines are
  // assembled from the running text rather than split per chunk — splitting a
  // "foo\n" chunk on its own leaves a trailing empty that doubles the spacing.
  const done = useRef<string[]>([]);
  const pending = useRef("");

  useEffect(() => {
    const clear = () => {
      done.current = [];
      pending.current = "";
      setLines([]);
    };
    clear();
    setExitCode(null);
    setError(null);
    if (taskId === null) {
      setIsRunning(false);
      return;
    }

    setIsRunning(true);
    let isFinished = false;
    let isDisposed = false;
    let reconnectsLeft = RECONNECT_LIMIT;
    let socket: WebSocket;
    let openTimer = 0;

    const ingest = (chunk: string) => {
      const parts = normalizeNewlines(pending.current + chunk).split("\n");
      pending.current = parts.pop() ?? "";
      done.current = [...done.current, ...parts].slice(-MAX_LOG_LINES);
      const shown =
        pending.current.length > 0
          ? [...done.current, pending.current]
          : done.current;
      setLines(shown.slice(-MAX_LOG_LINES));
    };

    const open = () => {
      const thisSocket = new WebSocket(websocketUrl(`/ws/task/${taskId}`));
      socket = thisSocket;
      let isSettled = false;

      const handleClose = () => {
        if (isSettled) {
          return;
        }
        isSettled = true;
        window.clearTimeout(openTimer);
        if (isDisposed || isFinished) {
          setIsRunning(false);
          return;
        }
        if (reconnectsLeft > 0) {
          reconnectsLeft -= 1;
          // The new subscription replays the job from its first line, so what
          // is on screen goes rather than being written twice.
          clear();
          open();
          return;
        }
        setIsRunning(false);
        setError("The task stream closed before the task reported a result");
      };

      openTimer = window.setTimeout(() => {
        thisSocket.onclose = null;
        thisSocket.close();
        handleClose();
      }, OPEN_TIMEOUT_MS);

      thisSocket.onopen = () => window.clearTimeout(openTimer);

      thisSocket.onmessage = (event: MessageEvent<unknown>) => {
        if (typeof event.data !== "string") {
          return;
        }
        const message = parseStreamMessage(event.data);
        if (message === null) {
          return;
        }
        if (message.type === "output") {
          ingest(message.data);
          return;
        }
        isFinished = true;
        window.clearTimeout(openTimer);
        setExitCode(message.type === "done" ? message.exit_code : message.code);
        setIsRunning(false);
        thisSocket.close();
      };

      thisSocket.onclose = () => handleClose();
    };

    open();

    return () => {
      isDisposed = true;
      window.clearTimeout(openTimer);
      socket.onclose = null;
      socket.close();
    };
  }, [taskId]);

  return { lines, isRunning, exitCode, error };
}

function parseStreamMessage(raw: string): StreamServerMessage | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) {
    return null;
  }
  const message = parsed as Record<string, unknown>;
  if (message.type === "output" && typeof message.data === "string") {
    return { type: "output", data: message.data };
  }
  if (message.type === "done" && typeof message.exit_code === "number") {
    return { type: "done", exit_code: message.exit_code };
  }
  if (message.type === "exit" && typeof message.code === "number") {
    return { type: "exit", code: message.code };
  }
  return null;
}

function normalizeNewlines(chunk: string): string {
  return chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}
