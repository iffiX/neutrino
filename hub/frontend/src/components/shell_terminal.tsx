import { useEffect, useRef } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";

import { TERMINAL_THEME } from "../terminal_theme";
import { websocketUrl } from "../api_client";

import "@xterm/xterm/css/xterm.css";
import "./shell_terminal.css";

/**
 * A terminal wired to a shell over a websocket.
 *
 * The one terminal in the panel. Both places that need one — an SSH session to
 * a device, and a shell on the gateway itself — differ only in which socket
 * they open and what surrounds them, so they differ only in props here. The
 * wiring underneath is identical, and having it in one place is what stops the
 * two drifting apart: the line-buffering bug that once made the device
 * terminal swallow keystrokes until Enter would have had to be found twice.
 *
 * xterm.js owns the DOM inside the surface, so this is imperative and lives in
 * one effect: build the terminal, wire the socket both ways, tear both down
 * together.
 */

export type TerminalState = "connecting" | "open" | "closed";

// Lines kept above the top of the window. A terminal that keeps everything is
// a terminal that grows without limit, and on a box being watched for hours
// that is memory nothing ever reclaims. Deep enough to scroll back through a
// long build, shallow enough to forget.
const TERMINAL_SCROLLBACK_LINES = 5000;

interface ShellTerminalProps {
  /** The websocket path to open, e.g. `/ws/terminal`. */
  socketPath: string;
  /**
   * False keeps the terminal mounted but out of sight. Unmounting would close
   * the socket and kill the shell, so a tabbed terminal has to hide rather
   * than remove the tabs it is not showing.
   */
  isVisible?: boolean;
  /** Called when the shell itself ends, by `exit` or Ctrl-D. */
  onExit?: (code: number | null) => void;
  onStateChange?: (state: TerminalState) => void;
}

export function ShellTerminal({
  socketPath,
  isVisible = true,
  onExit,
  onStateChange,
}: ShellTerminalProps) {
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  // The one way to remeasure, shared with the visibility effect below so a tab
  // coming back into view goes through the same guard as every other resize.
  const remeasureRef = useRef<() => void>(() => {});
  // Held in refs so the socket effect, which runs once, always calls the
  // current handlers rather than stale copies from the first render.
  const onExitRef = useRef(onExit);
  onExitRef.current = onExit;
  const onStateChangeRef = useRef(onStateChange);
  onStateChangeRef.current = onStateChange;

  useEffect(() => {
    const surface = surfaceRef.current;
    if (surface === null) {
      return;
    }

    const terminal = new Terminal({
      fontFamily: '"JetBrains Mono", ui-monospace, monospace',
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      // No convertEol: the far end allocates a pty, so its output already ends
      // lines with CRLF. Converting again would double-space everything.
      theme: TERMINAL_THEME,
      scrollback: TERMINAL_SCROLLBACK_LINES,
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(surface);
    fitAddon.fit();

    const socket = new WebSocket(websocketUrl(socketPath));

    const sendResize = () => {
      if (socket.readyState !== WebSocket.OPEN) {
        return;
      }
      socket.send(
        JSON.stringify({
          type: "resize",
          cols: terminal.cols,
          rows: terminal.rows,
        }),
      );
    };

    const handleResize = () => {
      // A hidden pane measures zero, and fitting to that throws the layout away.
      if (surface.clientWidth === 0) {
        return;
      }
      // Only resize when the answer actually changed. Fitting redraws the
      // terminal, redrawing changes its height by a rounding step, and the
      // observer that noticed brings us straight back here — so an
      // unconditional fit grows the terminal by a row every time output
      // arrives, and keeps growing for as long as the tab is open.
      const proposed = fitAddon.proposeDimensions();
      if (
        proposed === undefined ||
        (proposed.cols === terminal.cols && proposed.rows === terminal.rows)
      ) {
        return;
      }
      fitAddon.fit();
      sendResize();
    };
    remeasureRef.current = handleResize;

    socket.onopen = () => {
      onStateChangeRef.current?.("open");
      sendResize();
      terminal.focus();
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
      if (typeof parsed !== "object" || parsed === null) {
        return;
      }
      const message = parsed as Record<string, unknown>;
      if (message.type === "output" && typeof message.data === "string") {
        terminal.write(message.data);
        return;
      }
      if (message.type === "exit") {
        onExitRef.current?.(
          typeof message.code === "number" ? message.code : null,
        );
      }
    };

    socket.onclose = () => {
      onStateChangeRef.current?.("closed");
    };

    socket.onerror = () => {
      onStateChangeRef.current?.("closed");
    };

    const dataSubscription = terminal.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "input", data }));
      }
    });

    const observer = new ResizeObserver(handleResize);
    observer.observe(surface);
    window.addEventListener("resize", handleResize);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", handleResize);
      dataSubscription.dispose();
      socket.close();
      terminal.dispose();
      remeasureRef.current = () => {};
    };
  }, [socketPath]);

  // Becoming visible again means the surface has a size for the first time
  // since it was hidden, so it has to be measured before it draws.
  useEffect(() => {
    if (!isVisible) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      remeasureRef.current();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isVisible]);

  return (
    <div
      className={`shell_terminal ${isVisible ? "" : "shell_terminal--hidden"}`}
      ref={surfaceRef}
    />
  );
}
