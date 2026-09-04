import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import { ShellTerminal } from "./shell_terminal";
import type { TerminalState } from "./shell_terminal";
import { StatusDot } from "./status_dot";
import type { DeviceView } from "../api_types";

import "./terminal_modal.css";

/**
 * A full SSH session to one device, in a window of its own.
 *
 * Only the window is here. The terminal inside it is the same one the gateway's
 * own shell uses — same wiring, same protocol, same bugs found once rather than
 * twice — differing only in which socket it opens.
 */

const WORDING = {
  close: "Close",
  keystrokes:
    "Keystrokes go straight to the device. Press Escape to close the window.",
  lost: "Session closed. The gateway may have no SSH credentials for this device.",
  ended: (code: number) => `Session ended with exit code ${code}.`,
} as const;

interface TerminalModalProps {
  device: DeviceView;
  onClose: () => void;
}

export function TerminalModal({ device, onClose }: TerminalModalProps) {
  const [state, setState] = useState<TerminalState>("connecting");
  const [exitCode, setExitCode] = useState<number | null>(null);

  // The window says Escape closes it, so Escape closes it. Capturing takes the
  // key before the drawer underneath sees it: the topmost layer is the one
  // that goes, and the drawer stays where it was.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [onClose]);

  const target =
    device.ssh === null
      ? device.ipv4_address
      : `${device.ssh.username}@${device.ssh.host}:${device.ssh.port}`;

  // A portal, so no ancestor's transform or scroll container can capture
  // the fixed backdrop.
  return createPortal(
    <div className="terminal_modal_backdrop" role="dialog" aria-modal="true">
      <div className="terminal_modal">
        <div className="terminal_modal_head">
          <div className="terminal_modal_title">
            <Icon name="terminal" size={15} />
            <span className="terminal_modal_target">{target}</span>
          </div>
          <div className="terminal_modal_actions">
            <StatusDot
              tone={
                state === "open"
                  ? "ok"
                  : state === "connecting"
                    ? "warn"
                    : "error"
              }
              label={state}
            />
            <button
              type="button"
              className="button button--small"
              onClick={onClose}
            >
              <Icon name="close" size={13} />
              {WORDING.close}
            </button>
          </div>
        </div>
        <div className="terminal_modal_surface">
          <ShellTerminal
            socketPath={`/ws/ssh/${device.mac_address}`}
            onStateChange={setState}
            onExit={(code) => {
              // The remote shell exited. Close the window outright rather than
              // leaving a dead terminal that still looks usable.
              setExitCode(code);
              onClose();
            }}
          />
        </div>
        <div className="terminal_modal_status">
          {state === "closed"
            ? exitCode === null
              ? WORDING.lost
              : WORDING.ended(exitCode)
            : WORDING.keystrokes}
        </div>
      </div>
    </div>,
    document.body,
  );
}
