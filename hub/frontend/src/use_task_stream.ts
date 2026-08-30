import { useEffect, useState } from "react";

import { websocketUrl } from "./api_client";
import type { StreamServerMessage } from "./api_types";

/**
 * Follow one device action to completion over `/ws/task/{task_id}`.
 *
 * Unlike the dashboard feeds this socket must not reconnect: a task id is
 * consumed once, so reopening after the `done` frame would only produce a
 * stream of failed handshakes. The hook therefore opens exactly one socket per
 * task and keeps the output after it closes, which is what lets the drawer
 * show the log of a finished install.
 */

const MAX_LOG_LINES = 2000;

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

  useEffect(() => {
    setLines([]);
    setExitCode(null);
    setError(null);
    if (taskId === null) {
      setIsRunning(false);
      return;
    }

    setIsRunning(true);
    let isFinished = false;
    const socket = new WebSocket(websocketUrl(`/ws/task/${taskId}`));

    socket.onmessage = (event: MessageEvent<unknown>) => {
      if (typeof event.data !== "string") {
        return;
      }
      const message = parseStreamMessage(event.data);
      if (message === null) {
        return;
      }
      if (message.type === "output") {
        setLines((previous) =>
          [...previous, ...splitLines(message.data)].slice(-MAX_LOG_LINES),
        );
        return;
      }
      isFinished = true;
      setExitCode(message.type === "done" ? message.exit_code : message.code);
      setIsRunning(false);
      socket.close();
    };

    socket.onclose = () => {
      setIsRunning(false);
      if (!isFinished) {
        setError("The task stream closed before the task reported a result");
      }
    };

    return () => {
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

function splitLines(chunk: string): string[] {
  return chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
}
