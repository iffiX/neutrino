import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { StatusDot } from "./status_dot";
import { apiGet, apiPost, describeError } from "../api_client";
import { stripAnsi } from "../strip_ansi";
import { useTaskStream } from "../use_task_stream";
import type {
  DeviceView,
  RemoteDesktopStatus,
  RemoteDesktopView,
  DeviceActionResult,
} from "../api_types";

import "./remote_desktop_panel.css";

/**
 * Remote-desktop status and management for one device.
 *
 * A device that already runs AnyDesk or TeamViewer shows the id someone
 * connects to, whether or not this hub put it there, and takes an unattended
 * password. Both are user-tier modules the person installs themselves, so
 * this panel only reads and manages what is already on the machine.
 */

const PRODUCT_LABELS: Record<string, string> = {
  anydesk: "AnyDesk",
  teamviewer: "TeamViewer",
};

interface RemoteDesktopPanelProps {
  device: DeviceView;
  /**
   * Changes whenever a module order on this device moves. Installing the
   * software happens on the Modules rows, a path this panel starts nothing
   * on and would otherwise never hear about — leaving it saying "not
   * installed" beside a row that says installed.
   */
  moduleRevision: string;
}

export function RemoteDesktopPanel({
  device,
  moduleRevision,
}: RemoteDesktopPanelProps) {
  const [status, setStatus] = useState<RemoteDesktopView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const task = useTaskStream(taskId);

  const loadStatus = async () => {
    setError(null);
    try {
      setStatus(
        await apiGet<RemoteDesktopView>(
          `/devices/${device.mac_address}/remote_desktop`,
        ),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device.mac_address, moduleRevision]);

  // When an install or password task finishes, re-read the status so a freshly
  // installed product shows its id without a manual refresh.
  useEffect(() => {
    if (taskId !== null && !task.isRunning && task.exitCode !== null) {
      void loadStatus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task.isRunning, task.exitCode]);

  const runTask = async (path: string, body?: unknown) => {
    setError(null);
    setTaskId(null);
    try {
      const result = await apiPost<DeviceActionResult>(path, body);
      setTaskId(result.task_id);
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  return (
    <div className="remote_desktop">
      <div className="section_label">Remote desktop</div>
      {error !== null && <span className="field_error">{error}</span>}
      {status === null ? (
        <span className="field_hint">Reading status…</span>
      ) : (
        <div className="remote_desktop_grid">
          <RustdeskCard sessionId={status.rustdesk_id} />
          <ProductCard
            status={status.anydesk}
            macAddress={device.mac_address}
            isBusy={task.isRunning}
            onRun={runTask}
          />
          <ProductCard
            status={status.teamviewer}
            macAddress={device.mac_address}
            isBusy={task.isRunning}
            onRun={runTask}
          />
        </div>
      )}

      {(taskId !== null || task.lines.length > 0) && (
        <pre className="remote_desktop_log">
          {stripAnsi(task.lines.join("\n"))}
        </pre>
      )}
    </div>
  );
}

interface RustdeskCardProps {
  sessionId: string;
}

/**
 * RustDesk's id, as the machine's own module report carries it.
 *
 * Installing and removing it happens on the Modules rows like any other
 * hub-tier module, and the machine's own page is where a person shares the
 * desktop — this card only shows what to connect to.
 */
function RustdeskCard({ sessionId }: RustdeskCardProps) {
  const isReported = sessionId !== "";
  return (
    <div className="remote_desktop_card">
      <div className="remote_desktop_card_head">
        <span className="remote_desktop_card_name">RustDesk</span>
        <StatusDot
          tone={isReported ? "ok" : "idle"}
          label={isReported ? "installed" : "not installed"}
        />
      </div>
      {isReported ? (
        <div className="remote_desktop_id_row">
          <span className="remote_desktop_id_label">ID</span>
          <span className="remote_desktop_id">{sessionId}</span>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => void copyText(sessionId)}
            title="Copy ID"
          >
            <Icon name="link" size={12} />
          </button>
        </div>
      ) : (
        <span className="field_hint">
          Not reported by this machine. Install it from Modules above; sharing
          the desktop is done on the machine itself.
        </span>
      )}
    </div>
  );
}

interface ProductCardProps {
  status: RemoteDesktopStatus;
  macAddress: string;
  isBusy: boolean;
  onRun: (path: string, body?: unknown) => void;
}

function ProductCard({ status, macAddress, isBusy, onRun }: ProductCardProps) {
  const [password, setPassword] = useState("");
  const label = PRODUCT_LABELS[status.product] ?? status.product;
  const base = `/devices/${macAddress}/remote_desktop/${status.product}`;

  return (
    <div className="remote_desktop_card">
      <div className="remote_desktop_card_head">
        <span className="remote_desktop_card_name">{label}</span>
        <StatusDot
          tone={
            status.unreachable.length > 0
              ? "warn"
              : !status.is_installed
                ? "idle"
                : status.is_running
                  ? "ok"
                  : "warn"
          }
          label={
            status.unreachable.length > 0
              ? "not reached"
              : !status.is_installed
                ? "not installed"
                : status.is_running
                  ? "running"
                  : "stopped"
          }
        />
      </div>

      {status.is_installed ? (
        <>
          <div className="remote_desktop_id_row">
            <span className="remote_desktop_id_label">ID</span>
            <span className="remote_desktop_id">
              {status.session_id ?? "—"}
            </span>
            {status.session_id !== null && (
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => void copyText(status.session_id ?? "")}
                title="Copy ID"
              >
                <Icon name="link" size={12} />
              </button>
            )}
          </div>
          {status.session_id === null && (
            <span className="field_hint">
              {`No id yet; assigned once the device connects to ${label}.`}
            </span>
          )}
          {status.can_set_password ? (
            <div className="remote_desktop_pw">
              <PasswordInput
                value={password}
                placeholder="Set unattended password"
                onChange={setPassword}
              />
              <button
                type="button"
                className="button button--small"
                disabled={isBusy || password.length === 0}
                onClick={() => onRun(`${base}/password`, { password })}
              >
                Set
              </button>
            </div>
          ) : (
            <span className="field_hint">
              Set the password in the {label} app on the device.
            </span>
          )}
        </>
      ) : status.unreachable.length > 0 ? (
        <span className="field_hint">
          This device could not be asked, so what it is running is unknown:{" "}
          {status.unreachable}
        </span>
      ) : (
        <span className="field_hint">
          Not on this device. Install it from Modules above.
        </span>
      )}
    </div>
  );
}
