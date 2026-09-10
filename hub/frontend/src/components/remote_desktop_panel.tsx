import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { StatusDot } from "./status_dot";
import { ApiError, apiGet, apiPost, describeError } from "../api_client";
import { stripAnsi } from "../strip_ansi";
import { useConfirm } from "../use_confirm";
import { useTaskStream } from "../use_task_stream";
import type {
  DeviceRdp,
  DeviceView,
  RemoteDesktopStatus,
  RemoteDesktopView,
  TaskStarted,
} from "../api_types";

import "./remote_desktop_panel.css";

/**
 * Remote-desktop status and management for one device.
 *
 * A device that already runs AnyDesk or TeamViewer shows the id someone
 * connects to, whether or not this hub put it there, and takes an unattended
 * password. Both are user-tier modules the person installs themselves, so
 * this panel only reads and manages what is already on the machine. RustDesk
 * rides in every agent package instead, and its card reads the machine's own
 * report.
 */

const WORDING = {
  title: "Remote desktop",
  reading: "Reading status…",
  idLabel: "ID",
  copyId: "Copy ID",
  noId: "—",
  notReached: "not reached",
  notInstalled: "not installed",
  running: "running",
  stopped: "stopped",
  noIdYet: "No id yet; assigned once the device connects to {product}.",
  setPassword: "Set unattended password", // scan: allow
  set: "Set",
  passwordOnDevice: "Set the password in the {product} app on the device.", // scan: allow
  notAsked:
    "This device could not be asked, so what it is running is unknown: {reason}",
  notOnDevice: "Not on this device.",
};

const UNREACHABLE_WORDS: Record<string, string> = {
  agent_offline: "the agent is offline",
  stream_unknown: "this agent cannot answer",
  agent_never_reported: "the agent did not answer in time",
};

const PRODUCT_LABELS: Record<string, string> = {
  anydesk: "AnyDesk",
  teamviewer: "TeamViewer",
};

const RUSTDESK_WORDING = {
  name: "RustDesk",
  shared: "shared",
  notSharing: "not sharing",
  idLabel: "ID",
  copyId: "Copy ID",
  sharedBy: "Shared by {account}.",
  oneViewer: "1 viewer",
  viewers: "{count} viewers",
  directPort: "Direct port {port}",
  startHint: "Run sudo nagent rdp start on the machine to share its desktop.",
  notReported: "Not reported by this machine.",
  notInPackage: "Not in this agent's package.",
  reset: "Reset seat password",
  resetTitle: "Reset the seat password",
  resetBody:
    "The machine is given a new password at once. Every viewer connected now must connect again.",
  resetConfirm: "Reset",
};

// The {code, params} a reset is refused with, worded.
const RESET_ERROR_WORDING: Record<string, string> = {
  agent_offline: "The machine is not answering, so its password is unchanged.",
};

const ATTENTION_WORDS: Record<string, string> = {
  rdp_nobody_seated: "Nobody is signed in at that machine's screen.",
  rdp_screen_not_allowed:
    "Allow screen sharing once at that machine's own screen.",
};

/** One count worded, so no sentence is assembled from fragments. */
function viewerWords(count: number): string {
  return count === 1
    ? RUSTDESK_WORDING.oneViewer
    : RUSTDESK_WORDING.viewers.replace("{count}", String(count));
}

/** Wording for a refused reset, with the coded refusals spelled out. */
function describeResetError(cause: unknown): string {
  if (cause instanceof ApiError) {
    const wording = RESET_ERROR_WORDING[cause.code];
    if (wording !== undefined) {
      return wording;
    }
  }
  return describeError(cause);
}

interface RemoteDesktopPanelProps {
  device: DeviceView;
  /**
   * Changes whenever a module order on this device moves. Installing the
   * software happens elsewhere, a path this panel starts nothing on and
   * would otherwise never hear about — leaving it saying "not installed"
   * beside software that is there.
   */
  moduleRevision: string;
}

export function RemoteDesktopPanel({
  device,
  moduleRevision,
}: RemoteDesktopPanelProps) {
  const confirm = useConfirm();
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
      const result = await apiPost<TaskStarted>(path, body);
      setTaskId(result.task_id);
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  const resetSeatPassword = () => {
    confirm.ask({
      title: RUSTDESK_WORDING.resetTitle,
      body: RUSTDESK_WORDING.resetBody,
      confirmLabel: RUSTDESK_WORDING.resetConfirm,
      onConfirm: () => {
        setError(null);
        void apiPost(`/devices/${device.mac_address}/rdp/seat_password`).catch(
          (cause: unknown) => setError(describeResetError(cause)),
        );
      },
    });
  };

  return (
    <div className="remote_desktop">
      <div className="section_label">{WORDING.title}</div>
      {error !== null && <span className="field_error">{error}</span>}
      {status === null ? (
        <span className="field_hint">{WORDING.reading}</span>
      ) : (
        <div className="remote_desktop_grid">
          <RustdeskCard
            sessionId={status.rustdesk_id}
            rdp={device.client?.rdp ?? null}
            onResetSeatPassword={resetSeatPassword}
          />
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
      {confirm.modal}
    </div>
  );
}

interface RustdeskCardProps {
  sessionId: string;
  rdp: DeviceRdp | null;
  onResetSeatPassword: () => void;
}

/**
 * RustDesk as the machine's own report carries it: its id, and whether the
 * desktop is shared right now.
 *
 * Every agent package carries the host, so there is nothing to install here
 * and nothing here asks a machine to share — that is one command on the
 * machine itself. The seat password is the hub's, generated and never shown,
 * and resetting it is the one action this card has.
 */
function RustdeskCard({
  sessionId,
  rdp,
  onResetSeatPassword,
}: RustdeskCardProps) {
  const isReported = sessionId !== "";
  const isShared = rdp?.is_shared ?? false;
  const attention = rdp?.attention ?? "";

  if (rdp !== null && !rdp.is_available) {
    return (
      <div className="remote_desktop_card">
        <div className="remote_desktop_card_head">
          <span className="remote_desktop_card_name">
            {RUSTDESK_WORDING.name}
          </span>
          <StatusDot tone="idle" label={RUSTDESK_WORDING.notSharing} />
        </div>
        <span className="field_hint">{RUSTDESK_WORDING.notInPackage}</span>
      </div>
    );
  }

  return (
    <div className="remote_desktop_card">
      <div className="remote_desktop_card_head">
        <span className="remote_desktop_card_name">
          {RUSTDESK_WORDING.name}
        </span>
        <StatusDot
          tone={isShared ? "ok" : "idle"}
          label={
            isShared ? RUSTDESK_WORDING.shared : RUSTDESK_WORDING.notSharing
          }
        />
      </div>

      {isReported ? (
        <div className="remote_desktop_id_row">
          <span className="remote_desktop_id_label">
            {RUSTDESK_WORDING.idLabel}
          </span>
          <span className="remote_desktop_id">{sessionId}</span>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => void copyText(sessionId)}
            title={RUSTDESK_WORDING.copyId}
          >
            <Icon name="link" size={12} />
          </button>
        </div>
      ) : (
        <span className="field_hint">{RUSTDESK_WORDING.notReported}</span>
      )}

      {isShared && rdp !== null ? (
        <>
          <span className="muted">
            {RUSTDESK_WORDING.sharedBy.replace("{account}", rdp.account)}{" "}
            {viewerWords(rdp.connected_count)}
          </span>
          <span className="field_hint">
            {RUSTDESK_WORDING.directPort.replace("{port}", String(rdp.port))}
          </span>
        </>
      ) : (
        <span className="field_hint">{RUSTDESK_WORDING.startHint}</span>
      )}

      {attention.length > 0 && (
        <span className="field_error">
          {ATTENTION_WORDS[attention] ?? attention}
        </span>
      )}

      <button
        type="button"
        className="button button--ghost button--small remote_desktop_action"
        disabled={!isShared}
        onClick={onResetSeatPassword}
      >
        {RUSTDESK_WORDING.reset}
      </button>
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
              ? WORDING.notReached
              : !status.is_installed
                ? WORDING.notInstalled
                : status.is_running
                  ? WORDING.running
                  : WORDING.stopped
          }
        />
      </div>

      {status.is_installed ? (
        <>
          <div className="remote_desktop_id_row">
            <span className="remote_desktop_id_label">{WORDING.idLabel}</span>
            <span className="remote_desktop_id">
              {status.session_id ?? WORDING.noId}
            </span>
            {status.session_id !== null && (
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => void copyText(status.session_id ?? "")}
                title={WORDING.copyId}
              >
                <Icon name="link" size={12} />
              </button>
            )}
          </div>
          {status.session_id === null && (
            <span className="field_hint">
              {WORDING.noIdYet.replace("{product}", label)}
            </span>
          )}
          {status.can_set_password ? (
            <div className="remote_desktop_pw">
              <PasswordInput
                value={password}
                placeholder={WORDING.setPassword}
                onChange={setPassword}
              />
              <button
                type="button"
                className="button button--small"
                disabled={isBusy || password.length === 0}
                onClick={() => onRun(`${base}/password`, { password })}
              >
                {WORDING.set}
              </button>
            </div>
          ) : (
            <span className="field_hint">
              {WORDING.passwordOnDevice.replace("{product}", label)}
            </span>
          )}
        </>
      ) : status.unreachable.length > 0 ? (
        <span className="field_hint">
          {WORDING.notAsked.replace(
            "{reason}",
            UNREACHABLE_WORDS[status.unreachable] ?? status.unreachable,
          )}
        </span>
      ) : (
        <span className="field_hint">{WORDING.notOnDevice}</span>
      )}
    </div>
  );
}
