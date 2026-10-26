import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { AgentLinkModal } from "../components/agent_link_modal";
import { DeviceGauge } from "../components/device_gauge";
import { DeviceIconPicker } from "../components/device_icon_picker";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { InstallAgentModal } from "../components/install_agent_modal";
import { StatusDot } from "../components/status_dot";
import type { IconName } from "../components/icon";
import { ApiError, apiPost, describeCode, describeError } from "../api_client";
import { toDeviceIconName } from "../device_icon";
import { toDeviceLabel } from "../device_level";
import { toDeviceMetrics, withDeviceMetrics } from "../device_metrics";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import {
  HUB_EVENT_DEVICE_REPORT,
  HUB_EVENT_DEVICES,
  HUB_EVENT_METRICS,
  useHubEvents,
} from "../use_hub_events";
import type { HubEvent } from "../use_hub_events";
import { useTaskStream } from "../use_task_stream";
import type {
  DeviceAnnotation,
  DeviceMetricsView,
  DeviceRequest,
  DevicesResponse,
  DeviceView,
  DeviceWolResult,
  TaskStarted,
} from "../api_types";

import "./devices_page.css";

/**
 * The **Agents** page: one table of the managed machines, one row each.
 *
 * A row's icon is a button that writes a pick at once; its name links to
 * the machine page. The status cell is five rings that move on the
 * `metrics` event: CPU, memory, disk, the busiest GPU and the temperature,
 * or how long ago an offline machine was seen. The row's actions sit at its
 * right; Rename turns the name into an input and leaves Save and Cancel
 * alone. The header adds a machine through two dialogs, by link or over
 * SSH. What a press started reads on the row's own line under it.
 */

// What moves this list: a machine's session opening or ending, a machine
// named, forgotten or added, and a report saying something new about one.
const INVALIDATE_ON = [
  { type: HUB_EVENT_DEVICES },
  { type: HUB_EVENT_DEVICE_REPORT },
];

const DEVICES_PATH = "/hub/device";

// The {code, params} an action is refused with, worded.
const ACTION_ERROR_KEYS: Record<string, string> = {
  agent_offline: "ui.devices.agent_offline",
};

/** The presses that start a task on the machine, and the route of each. */
type PowerAction = "reboot" | "shutdown";

const POWER_PATHS: Record<PowerAction, string> = {
  reboot: "/hub/device/reboot",
  shutdown: "/hub/device/shutdown",
};

const POWER_LABEL_KEYS: Record<PowerAction, string> = {
  reboot: "ui.devices.reboot",
  shutdown: "ui.devices.shutdown",
};

/** The temperature ring's thresholds, in °C. */
const TEMPERATURE_WARN_C = 70;
const TEMPERATURE_ERROR_C = 85;

/** What a cell shows for a reading nobody has reported. */
const NOTHING = "—";

/** The columns the rename input takes: the name, the address and the MAC,
 * so the name fits while it is typed. */
const RENAME_COLUMN_SPAN = 3;

/** How many skeleton rows stand in for the first load. */
const SKELETON_ROWS = 3;

/** What a press on one row said: a line under that row. */
interface RowOutcome {
  deviceId: string;
  /** The press's own words, for a task's state line. */
  label: string;
  taskId: string | null;
  notice: string | null;
  error: string | null;
}

export function DevicesPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<DevicesResponse>(DEVICES_PATH, {
    invalidateOn: INVALIDATE_ON,
  });
  const confirm = useConfirm();
  const [devices, setDevices] = useState<DeviceView[]>([]);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<RowOutcome | null>(null);
  const [isLinkOpen, setIsLinkOpen] = useState(false);
  const [isSshOpen, setIsSshOpen] = useState(false);

  useEffect(() => {
    if (resource.data !== null) {
      setDevices(resource.data.devices);
    }
  }, [resource.data]);

  // Readings ride their own event, so a report lands on the rings without
  // the list being asked for again.
  const handleMetrics = (event: HubEvent) => {
    const metrics = toDeviceMetrics(event);
    if (metrics === null) {
      return;
    }
    setDevices((current) =>
      withDeviceMetrics(current, event.key, metrics, event.at),
    );
  };
  useHubEvents([{ type: HUB_EVENT_METRICS }], handleMetrics);

  const write = async (annotation: DeviceAnnotation): Promise<boolean> => {
    setBusyId(annotation.device_id);
    setOutcome(null);
    try {
      resource.setData(
        await apiPost<DevicesResponse>(`${DEVICES_PATH}/set`, annotation),
      );
      return true;
    } catch (cause: unknown) {
      setOutcome({
        deviceId: annotation.device_id,
        label: "",
        taskId: null,
        notice: null,
        error: describeActionError(cause),
      });
      return false;
    } finally {
      setBusyId(null);
    }
  };

  const startRename = (device: DeviceView) => {
    setRenamingId(device.id);
    setNewName(device.name ?? "");
  };

  const saveRename = async (device: DeviceView) => {
    const wanted = newName.trim();
    if (wanted.length === 0 || wanted === device.name) {
      setRenamingId(null);
      return;
    }
    if (await write({ device_id: device.id, name: wanted })) {
      setRenamingId(null);
    }
  };

  const wake = async (device: DeviceView) => {
    setBusyId(device.id);
    setOutcome(null);
    const request: DeviceRequest = { device_id: device.id };
    try {
      const result = await apiPost<DeviceWolResult>(
        `${DEVICES_PATH}/wake`,
        request,
      );
      setOutcome({
        deviceId: device.id,
        label: "",
        taskId: null,
        notice: result.is_sent ? describeCode(result) : null,
        error: result.is_sent ? null : describeCode(result),
      });
    } catch (cause: unknown) {
      setOutcome({
        deviceId: device.id,
        label: "",
        taskId: null,
        notice: null,
        error: describeActionError(cause),
      });
    } finally {
      setBusyId(null);
    }
  };

  const runPower = async (device: DeviceView, action: PowerAction) => {
    setBusyId(device.id);
    setOutcome(null);
    const request: DeviceRequest = { device_id: device.id };
    const label = t(POWER_LABEL_KEYS[action]);
    try {
      const started = await apiPost<TaskStarted>(POWER_PATHS[action], request);
      setOutcome({
        deviceId: device.id,
        label,
        taskId: started.task_id,
        notice: null,
        error: null,
      });
    } catch (cause: unknown) {
      setOutcome({
        deviceId: device.id,
        label,
        taskId: null,
        notice: null,
        error: describeActionError(cause),
      });
    } finally {
      setBusyId(null);
    }
  };

  const askPower = (device: DeviceView, action: PowerAction) =>
    confirm.ask({
      title: t(
        action === "reboot"
          ? "ui.devices.reboot_title"
          : "ui.devices.shutdown_title",
        { name: toDeviceLabel(device) },
      ),
      body: t(
        action === "reboot"
          ? "ui.devices.reboot_body"
          : "ui.devices.shutdown_body",
      ),
      confirmLabel: t(POWER_LABEL_KEYS[action]),
      onConfirm: () => void runPower(device, action),
    });

  const forget = async (device: DeviceView) => {
    setBusyId(device.id);
    setOutcome(null);
    const request: DeviceRequest = { device_id: device.id };
    try {
      await apiPost(`${DEVICES_PATH}/remove`, request);
      setDevices((current) => current.filter((held) => held.id !== device.id));
      resource.reload();
    } catch (cause: unknown) {
      setOutcome({
        deviceId: device.id,
        label: "",
        taskId: null,
        notice: null,
        error: describeActionError(cause),
      });
    } finally {
      setBusyId(null);
    }
  };

  const askForget = (device: DeviceView) =>
    confirm.ask({
      title: t("ui.devices.forget_title", { name: toDeviceLabel(device) }),
      body: t("ui.devices.forget_body"),
      confirmLabel: t("ui.devices.forget"),
      onConfirm: () => void forget(device),
    });

  if (resource.error !== null && resource.data === null) {
    return (
      <div className="page">
        <h1>{t("ui.devices.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  const count = resource.data?.count ?? null;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <div className="page_title_row">
            <h1>{t("ui.devices.title")}</h1>
            {count !== null && (
              <span className="badge">
                {t("ui.devices.badge", {
                  total: count.total,
                  online: count.online,
                })}
              </span>
            )}
          </div>
        </div>
        <div className="page_actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => setIsLinkOpen(true)}
          >
            <Icon name="link" size={14} />
            {t("ui.devices.add_by_link")}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => setIsSshOpen(true)}
          >
            <Icon name="terminal" size={14} />
            {t("ui.devices.add_by_ssh")}
          </button>
        </div>
      </div>

      {resource.data === null ? (
        <div className="card devices_table_scroll">
          {Array.from({ length: SKELETON_ROWS }, (_, index) => (
            <div key={index} className="skeleton devices_skeleton_row" />
          ))}
        </div>
      ) : devices.length === 0 ? (
        <div className="placeholder">
          <span>{t("ui.devices.empty")}</span>
          <span className="faint">{t("ui.devices.empty_hint")}</span>
        </div>
      ) : (
        <div className="card devices_table_scroll">
          <table className="devices_table">
            <colgroup>
              <col />
              <col className="devices_col--address" />
              <col className="devices_col--mac" />
              <col className="devices_col--status" />
              <col className="devices_col--version" />
              <col className="devices_col--seen" />
              <col className="devices_col--actions" />
            </colgroup>
            <thead>
              <tr>
                <th>{t("ui.devices.header_name")}</th>
                <th>{t("ui.devices.header_address")}</th>
                <th>{t("ui.devices.header_mac")}</th>
                <th>{t("ui.devices.header_status")}</th>
                <th>{t("ui.devices.header_version")}</th>
                <th>{t("ui.devices.header_last_seen")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => (
                <DeviceRow
                  key={device.id}
                  device={device}
                  isBusy={busyId === device.id}
                  isRenaming={renamingId === device.id}
                  newName={newName}
                  outcome={outcome?.deviceId === device.id ? outcome : null}
                  onNewName={setNewName}
                  onRename={() => startRename(device)}
                  onRenameSave={() => void saveRename(device)}
                  onRenameCancel={() => setRenamingId(null)}
                  onIcon={(icon) => void write({ device_id: device.id, icon })}
                  onWake={() => void wake(device)}
                  onPower={(action) => askPower(device, action)}
                  onForget={() => askForget(device)}
                  onOutcomeEnded={resource.reload}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isLinkOpen && <AgentLinkModal onClose={() => setIsLinkOpen(false)} />}
      {isSshOpen && (
        <InstallAgentModal
          device={null}
          onClose={() => setIsSshOpen(false)}
          onFinished={resource.reload}
        />
      )}
      {confirm.modal}
    </div>
  );
}

interface DeviceRowProps {
  device: DeviceView;
  isBusy: boolean;
  /** Whether the name cell holds the rename input. */
  isRenaming: boolean;
  newName: string;
  /** What the last press on this row said, if it was this row's. */
  outcome: RowOutcome | null;
  onNewName: (name: string) => void;
  onRename: () => void;
  onRenameSave: () => void;
  onRenameCancel: () => void;
  onIcon: (icon: IconName) => void;
  onWake: () => void;
  onPower: (action: PowerAction) => void;
  onForget: () => void;
  /** Called once a task the row started ends. */
  onOutcomeEnded: () => void;
}

function DeviceRow({
  device,
  isBusy,
  isRenaming,
  newName,
  outcome,
  onNewName,
  onRename,
  onRenameSave,
  onRenameCancel,
  onIcon,
  onWake,
  onPower,
  onForget,
  onOutcomeEnded,
}: DeviceRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const client = device.client;
  const isOnline = device.is_agent_online;
  const icon = toDeviceIconName(device.icon, client?.platform_os ?? null);
  return (
    <>
      <tr className={`devices_row ${isRenaming ? "devices_row--editing" : ""}`}>
        <td colSpan={isRenaming ? RENAME_COLUMN_SPAN : undefined}>
          <div className="devices_name">
            <DeviceIconPicker
              icon={icon}
              isDisabled={isBusy || isRenaming}
              onPick={onIcon}
            />
            <StatusDot tone={isOnline ? "ok" : "idle"} isPulsing={isOnline} />
            {isRenaming ? (
              <input
                className="input devices_rename_input"
                value={newName}
                aria-label={t("ui.devices.header_name")}
                autoFocus
                onChange={(event) => onNewName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    onRenameSave();
                  } else if (event.key === "Escape") {
                    onRenameCancel();
                  }
                }}
              />
            ) : (
              <Link
                to={`/agents/${encodeURIComponent(device.id)}`}
                className="devices_name_link"
              >
                {toDeviceLabel(device)}
              </Link>
            )}
          </div>
        </td>
        {!isRenaming && (
          <>
            <td className="mono">{device.ipv4_address || NOTHING}</td>
            <td className="mono devices_mac">{device.link_mac || NOTHING}</td>
          </>
        )}
        <td>
          <StatusCell device={device} />
        </td>
        <td className="mono">
          {client?.version == null ? (
            NOTHING
          ) : client.is_version_mismatched ? (
            <span
              className="devices_version--old"
              title={t("ui.devices.version_mismatched")}
            >
              {client.version}
            </span>
          ) : (
            client.version
          )}
        </td>
        <td className="mono">
          {isOnline ? t("state.online") : formatTimeAgo(lastSeen(device))}
        </td>
        <td>
          <div className="devices_actions">
            {isRenaming ? (
              <>
                <button
                  type="button"
                  className="button button--small button--primary"
                  disabled={isBusy || newName.trim().length === 0}
                  onClick={onRenameSave}
                >
                  <Icon name="check" size={13} />
                  {t("ui.devices.save")}
                </button>
                <button
                  type="button"
                  className="button button--small button--ghost"
                  onClick={onRenameCancel}
                >
                  {t("ui.devices.cancel")}
                </button>
              </>
            ) : (
              <>
                <Link
                  to={`/agents/${encodeURIComponent(device.id)}`}
                  className="button button--small button--ghost"
                >
                  {t("ui.devices.manage")}
                </Link>
                <button
                  type="button"
                  className="button button--small button--ghost"
                  disabled={isBusy}
                  onClick={onRename}
                >
                  {t("ui.devices.rename")}
                </button>
                <button
                  type="button"
                  className="button button--small button--ghost"
                  disabled={isBusy}
                  onClick={onWake}
                >
                  {t("ui.devices.wake")}
                </button>
                {(["reboot", "shutdown"] as PowerAction[]).map((action) => (
                  <button
                    key={action}
                    type="button"
                    className="button button--small button--ghost"
                    disabled={isBusy || !isOnline}
                    onClick={() => onPower(action)}
                  >
                    {t(POWER_LABEL_KEYS[action])}
                  </button>
                ))}
                <button
                  type="button"
                  className="button button--small button--ghost button--danger"
                  disabled={isBusy}
                  onClick={onForget}
                >
                  {t("ui.devices.forget")}
                </button>
              </>
            )}
          </div>
        </td>
      </tr>
      {outcome !== null && (
        <tr className="devices_outcome_row">
          <td colSpan={7}>
            <RowOutcomeLine outcome={outcome} onEnded={onOutcomeEnded} />
          </td>
        </tr>
      )}
    </>
  );
}

interface StatusCellProps {
  device: DeviceView;
}

/** Five rings for a machine that reports, or how long ago it was seen. */
function StatusCell({ device }: StatusCellProps) {
  if (!device.is_agent_online) {
    return (
      <span className="devices_offline">
        {t("ui.devices.offline_ago", {
          ago: formatTimeAgo(lastSeen(device)),
        })}
      </span>
    );
  }
  const metrics = device.client?.metrics ?? null;
  if (metrics === null) {
    return (
      <span className="devices_offline">{t("ui.device_monitor.waiting")}</span>
    );
  }
  const gpu = busiestGpu(metrics);
  return (
    <div className="devices_rings">
      <DeviceGauge
        label={t("ui.devices.ring_cpu")}
        reading={metrics.cpu_percent}
      />
      <DeviceGauge
        label={t("ui.devices.ring_memory")}
        reading={metrics.memory_percent}
      />
      <DeviceGauge
        label={t("ui.devices.ring_disk")}
        reading={metrics.disk_percent}
      />
      {gpu !== null && (
        <DeviceGauge
          label={t("ui.devices.ring_gpu")}
          reading={gpu}
          count={metrics.gpus.length}
        />
      )}
      <DeviceGauge
        label={t("ui.devices.ring_temperature")}
        reading={metrics.temperature_c}
        warnAt={TEMPERATURE_WARN_C}
        errorAt={TEMPERATURE_ERROR_C}
      />
    </div>
  );
}

interface RowOutcomeLineProps {
  outcome: RowOutcome;
  onEnded: () => void;
}

/** What a press said: a sent packet, a refusal, or a task's state. */
function RowOutcomeLine({ outcome, onEnded }: RowOutcomeLineProps) {
  const task = useTaskStream(outcome.taskId);
  const wasRunning = useRef(false);

  useEffect(() => {
    if (task.isRunning) {
      wasRunning.current = true;
      return;
    }
    if (wasRunning.current) {
      wasRunning.current = false;
      onEnded();
    }
  }, [task.isRunning, onEnded]);

  if (outcome.error !== null) {
    return <span className="field_error">{outcome.error}</span>;
  }
  if (outcome.notice !== null) {
    return <span className="field_hint">{outcome.notice}</span>;
  }
  const lastLine = task.lines.at(-1) ?? "";
  return (
    <span className="devices_outcome">
      <StatusDot
        tone={
          task.isRunning
            ? "warn"
            : task.exitCode === 0
              ? "ok"
              : task.exitCode === null
                ? "idle"
                : "error"
        }
        isPulsing={task.isRunning}
        label={
          task.isRunning
            ? t("ui.devices.task_running", { action: outcome.label })
            : task.exitCode === null
              ? outcome.label
              : t("ui.devices.task_finished", {
                  action: outcome.label,
                  code: task.exitCode,
                })
        }
      />
      {lastLine !== "" && <span className="mono faint">{lastLine}</span>}
    </span>
  );
}

/** The busiest card's use, or null on a machine with none. */
function busiestGpu(metrics: DeviceMetricsView): number | null {
  const readings = metrics.gpus
    .map((gpu) => gpu.utilization_percent)
    .filter((reading): reading is number => reading !== null);
  if (metrics.gpus.length === 0) {
    return null;
  }
  return readings.length === 0 ? null : Math.max(...readings);
}

/** When the machine was last seen: its session's end, else its last report. */
function lastSeen(device: DeviceView): string | null {
  return device.client?.last_seen ?? device.client?.last_report_at ?? null;
}

/** Wording for a refused press, with the coded refusals spelled out. */
function describeActionError(cause: unknown): string {
  if (cause instanceof ApiError) {
    const key = ACTION_ERROR_KEYS[cause.code];
    if (key !== undefined) {
      return t(key);
    }
  }
  return describeError(cause);
}
