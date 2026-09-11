import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { StatusDot } from "./status_dot";
import { ApiError, apiGet, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
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

/** The label shown where a product reports no id. */
const NO_ID = "—";

/** The products' own names, which are the same in every language. */
const PRODUCT_LABELS: Record<string, string> = {
  anydesk: "AnyDesk",
  teamviewer: "TeamViewer",
};

const RUSTDESK_NAME = "RustDesk";

/** A product that could not be asked, worded by the reason it gave. */
const UNREACHABLE_KEYS: Record<string, string> = {
  agent_offline: "ui.remote_desktop.not_asked_agent_offline",
  stream_unknown: "ui.remote_desktop.not_asked_stream_unknown",
  agent_never_reported: "ui.remote_desktop.not_asked_agent_never_reported",
};

const ATTENTION_KEYS: Record<string, string> = {
  rdp_nobody_seated: "code.rdp_nobody_seated",
  rdp_screen_not_allowed: "code.rdp_screen_not_allowed",
};

/** One count worded, so no sentence is assembled from fragments. */
function viewerWords(count: number): string {
  return count === 1
    ? t("ui.remote_desktop.viewer_one")
    : t("ui.remote_desktop.viewers", { count });
}

/** Wording for a refused reset, with the coded refusals spelled out. */
function describeResetError(cause: unknown): string {
  if (cause instanceof ApiError && cause.code === "agent_offline") {
    return t("ui.remote_desktop.reset_agent_offline");
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
      title: t("ui.remote_desktop.reset_title"),
      body: t("ui.remote_desktop.reset_body"),
      confirmLabel: t("ui.remote_desktop.reset_confirm"),
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
      <div className="section_label">{t("ui.remote_desktop.title")}</div>
      {error !== null && <span className="field_error">{error}</span>}
      {status === null ? (
        <span className="field_hint">{t("ui.remote_desktop.reading")}</span>
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
          <span className="remote_desktop_card_name">{RUSTDESK_NAME}</span>
          <StatusDot tone="idle" label={t("state.not_sharing")} />
        </div>
        <span className="field_hint">
          {t("ui.remote_desktop.not_in_package")}
        </span>
      </div>
    );
  }

  return (
    <div className="remote_desktop_card">
      <div className="remote_desktop_card_head">
        <span className="remote_desktop_card_name">{RUSTDESK_NAME}</span>
        <StatusDot
          tone={isShared ? "ok" : "idle"}
          label={t(isShared ? "state.shared" : "state.not_sharing")}
        />
      </div>

      {isReported ? (
        <div className="remote_desktop_id_row">
          <span className="remote_desktop_id_label">
            {t("ui.remote_desktop.id_label")}
          </span>
          <span className="remote_desktop_id">{sessionId}</span>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => void copyText(sessionId)}
            title={t("ui.remote_desktop.copy_id")}
          >
            <Icon name="link" size={12} />
          </button>
        </div>
      ) : (
        <span className="field_hint">
          {t("ui.remote_desktop.not_reported")}
        </span>
      )}

      {isShared && rdp !== null ? (
        <>
          <span className="muted">
            {t("ui.remote_desktop.shared_by", { account: rdp.account })}{" "}
            {viewerWords(rdp.connected_count)}
          </span>
          <span className="field_hint">
            {t("ui.remote_desktop.direct_port", { port: rdp.port })}
          </span>
        </>
      ) : (
        <span className="field_hint">{t("ui.remote_desktop.start_hint")}</span>
      )}

      {attention.length > 0 && (
        <span className="field_error">{describeAttention(attention)}</span>
      )}

      <button
        type="button"
        className="button button--ghost button--small remote_desktop_action"
        disabled={!isShared}
        onClick={onResetSeatPassword}
      >
        {t("ui.remote_desktop.reset")}
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
              ? t("state.not_reached")
              : !status.is_installed
                ? t("state.not_installed")
                : status.is_running
                  ? t("state.running")
                  : t("state.stopped")
          }
        />
      </div>

      {status.is_installed ? (
        <>
          <div className="remote_desktop_id_row">
            <span className="remote_desktop_id_label">
              {t("ui.remote_desktop.id_label")}
            </span>
            <span className="remote_desktop_id">
              {status.session_id ?? NO_ID}
            </span>
            {status.session_id !== null && (
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => void copyText(status.session_id ?? "")}
                title={t("ui.remote_desktop.copy_id")}
              >
                <Icon name="link" size={12} />
              </button>
            )}
          </div>
          {status.session_id === null && (
            <span className="field_hint">
              {t("ui.remote_desktop.no_id_yet", { product: label })}
            </span>
          )}
          {status.can_set_password ? (
            <div className="remote_desktop_pw">
              <PasswordInput
                value={password}
                placeholder={t("ui.remote_desktop.set_password")}
                onChange={setPassword}
              />
              <button
                type="button"
                className="button button--small"
                disabled={isBusy || password.length === 0}
                onClick={() => onRun(`${base}/password`, { password })}
              >
                {t("ui.remote_desktop.set")}
              </button>
            </div>
          ) : (
            <span className="field_hint">
              {t("ui.remote_desktop.password_on_device", { product: label })}
            </span>
          )}
        </>
      ) : status.unreachable.length > 0 ? (
        <span className="field_hint">
          {describeUnreachable(status.unreachable)}
        </span>
      ) : (
        <span className="field_hint">
          {t("ui.remote_desktop.not_on_device")}
        </span>
      )}
    </div>
  );
}

/** Why a product could not be asked, or the bare reason where none is worded. */
function describeUnreachable(reason: string): string {
  const key = UNREACHABLE_KEYS[reason];
  return key === undefined
    ? t("ui.remote_desktop.not_asked", { reason })
    : t(key);
}

/** What the machine needs a person to do at its own screen. */
function describeAttention(attention: string): string {
  const key = ATTENTION_KEYS[attention];
  return key === undefined ? attention : t(key);
}
