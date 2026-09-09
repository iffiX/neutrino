import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";

import { Icon } from "./icon";
import type { IconName } from "./icon";
import { DeviceEnrollmentNotice } from "./device_enrollment_notice";
import { InstallAgentModal } from "./install_agent_modal";
import { RemoteDesktopPanel } from "./remote_desktop_panel";
import { StatusDot } from "./status_dot";
import { ToggleSwitch } from "./toggle_switch";
import {
  ApiError,
  apiDelete,
  apiPost,
  apiPut,
  describeError,
} from "../api_client";
import { DEVICE_ICON_NAMES, toDeviceIconName } from "../device_icon";
import {
  DEVICE_REACH_LABELS,
  isDeviceManaged,
  toDeviceReach,
  toDevicePresence,
  toDeviceUpgradePath,
} from "../device_level";
import type { DeviceUpgradePath } from "../device_level";
import { useConfirm } from "../use_confirm";
import { formatTimeAgo } from "../format_duration";
import { stripAnsi } from "../strip_ansi";
import { HUB_EVENT_MODULE_ORDER, useHubEvents } from "../use_hub_events";
import { useTaskStream } from "../use_task_stream";
import type {
  DeviceActionName,
  DeviceAnnotation,
  DeviceEnrollmentView,
  DeviceView,
  DeviceWolResult,
  TaskStarted,
} from "../api_types";

import "./device_drawer.css";

/**
 * The detail view for one device: what it is, and what can be done to it now.
 *
 * A machine's shell and its files live on their own pages, which this links
 * to with the machine already picked. What stays here is what belongs to the
 * one record: its name, its icon, whether it wakes on a magic packet, and the
 * remote actions its agent takes. Action output streams into the log at the
 * bottom rather than into a toast, because an install is a thing you read.
 */

const WORDING = {
  close: "Close",
  terminal: "Terminal",
  files: "Files",
  identity: "Identity",
  displayName: "Display name",
  icon: "Icon",
  wol: "Wake-on-LAN",
  wolHint:
    "Whether this device can be woken with a magic packet sent to its MAC from the LAN interface.",
  actions: "Actions",
  wake: "Wake-on-LAN",
  install: "Install agent",
  reinstall: "Reinstall agent",
  reboot: "Reboot",
  shutdown: "Shut down",
  actionBody:
    "The machine is told to do this at once; anything unsaved on it is lost.",
  getLink: "Get link",
  output: "Action output",
  commandResults: "Agent command results",
  forget: "Forget device",
  forgetBody: "The device and its saved credentials are deleted from this box.",
  save: "Save device",
  saving: "Saving…",
  saved: "Saved.",
  reporting: "reporting",
  seen: "on the network",
  offline: "offline",
  seenAgo: "seen {when}",
  unknownVendor: "unknown vendor",
  running: "{action} · running",
  finished: "{action} · exit {code}",
};

// Wording for the way this device becomes managed, or catches up with the hub.
const GUIDANCE_TITLES: Record<DeviceUpgradePath, string> = {
  install: "Install the agent to manage this device.",
  link: "No credentials for this machine yet.",
};

const GUIDANCE_HINTS: Record<DeviceUpgradePath, string> = {
  install: "Install agent below asks for a login and runs the installer.",
  link: "Send it an enrollment link. The SSH installer needs Linux.",
};

const VERSION_MISMATCH_TITLE =
  "This agent is a different version from the hub.";

const VERSION_MISMATCH_HINTS: Record<DeviceUpgradePath, string> = {
  install: "Reinstall it with the Reinstall agent action below.",
  link: "Re-enroll it with a fresh link. The SSH installer needs Linux.",
};

// The agent's last_error {code, params}, worded. A code without an entry
// shows as itself, because a failure hidden entirely is worse than a bare
// code.
const AGENT_ERROR_WORDING: Record<string, string> = {
  unsupported_platform: "The agent asked for something its platform cannot do.",
  update_failed: "The agent could not update itself.",
  agent_package_missing:
    "The hub has no agent package for this machine's platform.",
  agent_package_fetch_failed:
    "The hub could not fetch the agent package for this platform.",
  agent_package_sha256_mismatch:
    "What the hub fetched is not the agent package its manifest pins.",
  agent_package_cache_unwritable:
    "The hub could not write the agent package to its own disk.",
};

// The {code, params} an action is refused with, worded.
const ACTION_ERROR_WORDING: Record<string, string> = {
  agent_offline: "The machine is not answering, so nothing was started on it.",
};

/** One remote action, as the grid draws it. */
interface DeviceAction {
  action: DeviceActionName;
  label: string;
  icon: IconName;
  isDestructive: boolean;
}

/** What this device needs next, drawn above its actions. */
interface DeviceGuidance {
  tone: string;
  icon: IconName;
  title: string;
  hint: string;
  hasEnrollmentLink: boolean;
}

// What a managed machine takes, beside Wake-on-LAN.
const MANAGED_ACTIONS: DeviceAction[] = [
  {
    action: "reinstall_agent",
    label: WORDING.reinstall,
    icon: "download",
    isDestructive: false,
  },
  {
    action: "reboot",
    label: WORDING.reboot,
    icon: "refresh",
    isDestructive: true,
  },
  {
    action: "shutdown",
    label: WORDING.shutdown,
    icon: "power",
    isDestructive: true,
  },
];

interface DeviceDrawerProps {
  device: DeviceView;
  onClose: () => void;
  onSaved: (device: DeviceView) => void;
  onForgotten: (macAddress: string) => void;
  onTaskFinished?: () => void;
}

export function DeviceDrawer({
  device,
  onClose,
  onSaved,
  onForgotten,
  onTaskFinished,
}: DeviceDrawerProps) {
  const navigate = useNavigate();
  const [name, setName] = useState(device.name ?? "");
  const [icon, setIcon] = useState<IconName>(toDeviceIconName(device.icon));
  const [isWolEnabled, setIsWolEnabled] = useState(device.is_wol_enabled);
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [runningLabel, setRunningLabel] = useState<string | null>(null);
  const [isInstallOpen, setIsInstallOpen] = useState(false);
  // A link generated for this machine alone, for the ones no installer reaches.
  const [enrollment, setEnrollment] = useState<DeviceEnrollmentView | null>(
    null,
  );
  // Bumped whenever a module order on this machine moves, so the remote
  // desktop panel reads again after software lands on it.
  const [moduleRevision, setModuleRevision] = useState(0);
  const confirm = useConfirm();

  const task = useTaskStream(taskId);
  const logRef = useRef<HTMLPreElement | null>(null);
  const wasTaskRunning = useRef(false);

  const isManaged = isDeviceManaged(device);
  const isAgentOnline = isManaged && device.is_agent_online;

  useHubEvents(
    [{ type: HUB_EVENT_MODULE_ORDER, key: device.mac_address }],
    () => setModuleRevision((current) => current + 1),
  );

  // An install's outcome — the agent appearing, the version catching up — is
  // the page's to show the moment the task ends.
  useEffect(() => {
    if (task.isRunning) {
      wasTaskRunning.current = true;
      return;
    }
    if (wasTaskRunning.current) {
      wasTaskRunning.current = false;
      onTaskFinished?.();
    }
  }, [task.isRunning, onTaskFinished]);

  useEffect(() => {
    const element = logRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [task.lines]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isInstallOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, isInstallOpen]);

  const reach = toDeviceReach(device);
  const presence = toDevicePresence(device);
  const guidance = toGuidance(device);

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const annotation: DeviceAnnotation = {
        name: name.trim(),
        icon,
        is_wol_enabled: isWolEnabled,
      };
      onSaved(
        await apiPut<DeviceView>(`/devices/${device.mac_address}`, annotation),
      );
      setNotice(WORDING.saved);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  const handleEnrollmentLink = async () => {
    setError(null);
    setNotice(null);
    try {
      setEnrollment(
        await apiPost<DeviceEnrollmentView>("/devices/enrollment", {
          name: device.name ?? "",
          mac_address: device.mac_address,
        }),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  const handleWakeOnLan = async () => {
    setError(null);
    setNotice(null);
    try {
      const result = await apiPost<DeviceWolResult>(
        `/devices/${device.mac_address}/wol`,
      );
      setNotice(result.message);
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  const handleAction = (deviceAction: DeviceAction) => {
    // A reinstall reaches a machine through its own agent; one that is not
    // answering takes the SSH installer, which asks for a login first.
    if (deviceAction.action === "reinstall_agent" && !isAgentOnline) {
      setIsInstallOpen(true);
      return;
    }
    if (!deviceAction.isDestructive) {
      void runAction(deviceAction);
      return;
    }
    confirm.ask({
      title: `${deviceAction.label} ${device.name ?? device.mac_address}`,
      body: WORDING.actionBody,
      confirmLabel: deviceAction.label,
      onConfirm: () => void runAction(deviceAction),
    });
  };

  const runAction = async (deviceAction: DeviceAction) => {
    setError(null);
    setNotice(null);
    setTaskId(null);
    setRunningLabel(deviceAction.label);
    try {
      const started = await apiPost<TaskStarted>(
        `/devices/${device.mac_address}/action`,
        { action: deviceAction.action },
      );
      setTaskId(started.task_id);
    } catch (cause: unknown) {
      setRunningLabel(null);
      setError(describeActionError(cause));
    }
  };

  const handleForget = () =>
    confirm.ask({
      title: `Forget ${device.name ?? device.mac_address}`,
      body: WORDING.forgetBody,
      confirmLabel: "Forget",
      onConfirm: () => void forgetDevice(),
    });

  const forgetDevice = async () => {
    setError(null);
    try {
      await apiDelete<Record<string, never>>(`/devices/${device.mac_address}`);
      onForgotten(device.mac_address);
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  const openPage = (path: string) => {
    onClose();
    navigate(`${path}?device=${encodeURIComponent(device.mac_address)}`);
  };

  // A portal, so the drawer escapes the page's stacking context — inside it,
  // no z-index can put the drawer above the top bar.
  return createPortal(
    <>
      <div className="device_drawer_backdrop" onClick={onClose} />
      <aside className="device_drawer" role="dialog" aria-modal="true">
        <div className="device_drawer_head">
          <div className="device_drawer_identity">
            <span className="device_drawer_icon">
              <Icon name={icon} size={20} />
            </span>
            <span className="device_drawer_titles">
              <span className="device_drawer_title">
                <StatusDot
                  tone={device.is_online ? "ok" : "idle"}
                  isPulsing={device.is_online}
                />
                {device.name ?? device.mac_address}
              </span>
              <span className="device_drawer_subtitle">
                {device.ipv4_address} · {device.mac_address}
              </span>
            </span>
          </div>
          <div className="device_drawer_head_actions">
            {isAgentOnline && (
              <>
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => openPage("/terminals")}
                >
                  <Icon name="terminal" size={13} />
                  {WORDING.terminal}
                </button>
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => openPage("/files")}
                >
                  <Icon name="folder" size={13} />
                  {WORDING.files}
                </button>
              </>
            )}
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={onClose}
              aria-label={WORDING.close}
            >
              <Icon name="close" size={15} />
            </button>
          </div>
        </div>

        <div className="device_drawer_body">
          <div className="device_drawer_section">
            <div className="button_row">
              <span
                className={`badge ${reach === "agent" ? "badge--ok" : reach === "ssh" ? "badge--accent" : ""}`}
              >
                {DEVICE_REACH_LABELS[reach]}
              </span>
              <span
                className={`badge ${presence === "offline" ? "badge--warn" : "badge--ok"}`}
              >
                {presence === "reporting"
                  ? WORDING.reporting
                  : presence === "seen"
                    ? WORDING.seen
                    : WORDING.offline}
              </span>
              <span className="badge">
                {device.client?.hostname ??
                  (device.vendor || WORDING.unknownVendor)}
              </span>
              {device.client !== null && !device.client.is_online && (
                <span className="badge">
                  {WORDING.seenAgo.replace(
                    "{when}",
                    formatTimeAgo(device.client.last_seen),
                  )}
                </span>
              )}
            </div>
            {device.client?.last_error != null && (
              <div className="notice notice--warn">
                <Icon name="alert" size={15} />
                <div className="notice_body">
                  {AGENT_ERROR_WORDING[device.client.last_error.code] ??
                    device.client.last_error.code}
                </div>
              </div>
            )}
          </div>

          {error !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{error}</div>
            </div>
          )}

          <div className="device_drawer_section">
            <span className="section_label">{WORDING.identity}</span>
            <label className="field">
              <span className="field_label">{WORDING.displayName}</span>
              <input
                className="input"
                value={name}
                placeholder={device.mac_address}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <div className="field">
              <span className="field_label">{WORDING.icon}</span>
              <div className="device_drawer_icons">
                {DEVICE_ICON_NAMES.map((option) => (
                  <button
                    key={option}
                    type="button"
                    title={option}
                    aria-label={option}
                    aria-pressed={icon === option}
                    className={`device_drawer_icon_option ${
                      icon === option
                        ? "device_drawer_icon_option--selected"
                        : ""
                    }`}
                    onClick={() => setIcon(option)}
                  >
                    <Icon name={option} size={16} />
                  </button>
                ))}
              </div>
            </div>
            <ToggleSwitch
              isOn={isWolEnabled}
              onChange={setIsWolEnabled}
              label={WORDING.wol}
              description={WORDING.wolHint}
            />
          </div>

          <div className="device_drawer_section">
            <span className="section_label">{WORDING.actions}</span>
            {guidance !== null && (
              <div className={`notice ${guidance.tone}`}>
                <Icon name={guidance.icon} size={15} />
                <div className="notice_body">
                  <strong>{guidance.title}</strong>
                  <span className="muted">{guidance.hint}</span>
                  {guidance.hasEnrollmentLink && (
                    <div className="device_drawer_guidance_action">
                      <button
                        type="button"
                        className="button"
                        onClick={() => void handleEnrollmentLink()}
                      >
                        <Icon name="link" size={14} />
                        {WORDING.getLink}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
            {enrollment !== null && (
              <DeviceEnrollmentNotice
                enrollment={enrollment}
                deviceName={device.name ?? device.mac_address}
                onDismiss={() => setEnrollment(null)}
              />
            )}
            <div className="device_drawer_actions">
              <button
                type="button"
                className="button"
                onClick={() => void handleWakeOnLan()}
              >
                <Icon name="bolt" size={14} />
                {WORDING.wake}
              </button>
              {isManaged ? (
                MANAGED_ACTIONS.map((deviceAction) => (
                  <button
                    key={deviceAction.action}
                    type="button"
                    className={`button ${deviceAction.isDestructive ? "button--danger" : ""}`}
                    disabled={task.isRunning}
                    onClick={() => handleAction(deviceAction)}
                  >
                    <Icon name={deviceAction.icon} size={14} />
                    {deviceAction.label}
                  </button>
                ))
              ) : (
                <button
                  type="button"
                  className="button"
                  disabled={task.isRunning}
                  onClick={() => setIsInstallOpen(true)}
                >
                  <Icon name="download" size={14} />
                  {WORDING.install}
                </button>
              )}
            </div>
          </div>

          {taskId !== null && (
            <div className="device_drawer_log">
              <div className="device_drawer_log_head">
                <span className="section_label">{WORDING.output}</span>
              </div>
              <div className="device_drawer_operation_line">
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
                  label={describeTask(
                    runningLabel,
                    task.isRunning,
                    task.exitCode,
                  )}
                />
              </div>
              <pre className="device_drawer_log_output" ref={logRef}>
                {stripAnsi(task.lines.join("\n"))}
              </pre>
              {task.error !== null && (
                <span className="field_error">{task.error}</span>
              )}
            </div>
          )}

          {isManaged && (
            <RemoteDesktopPanel
              device={device}
              moduleRevision={String(moduleRevision)}
            />
          )}

          {device.client != null &&
            device.client.command_results.length > 0 && (
              <div className="device_drawer_log">
                <div className="device_drawer_log_head">
                  <span className="section_label">
                    {WORDING.commandResults}
                  </span>
                </div>
                {device.client.command_results.map((outcome) => (
                  <div key={outcome.id} className="device_drawer_log_head">
                    <StatusDot
                      tone={outcome.exit_code === 0 ? "ok" : "error"}
                      isPulsing={false}
                      label={`${outcome.id} · exit ${outcome.exit_code} · ${formatTimeAgo(outcome.finished_at)}`}
                    />
                    {outcome.output.length > 0 && (
                      <span className="muted">{stripAnsi(outcome.output)}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
        </div>

        {notice !== null && (
          <div className="notice notice--ok">
            <Icon name="check" size={15} />
            <div className="notice_body">{notice}</div>
          </div>
        )}

        <div className="device_drawer_footer">
          {device.is_stored && (
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() => handleForget()}
            >
              <Icon name="trash" size={13} />
              {WORDING.forget}
            </button>
          )}
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={isSaving}
            onClick={() => void handleSave()}
          >
            <Icon name="check" size={14} />
            {isSaving ? WORDING.saving : WORDING.save}
          </button>
        </div>
      </aside>

      {isInstallOpen && (
        <InstallAgentModal
          device={device}
          isReinstall={isManaged}
          onClose={() => setIsInstallOpen(false)}
          onFinished={onTaskFinished}
        />
      )}
      {confirm.modal}
    </>,
    document.body,
  );
}

/**
 * What this device needs next, or null when it is managed and in step.
 *
 * An unmanaged device is told which of the two ways onto the hub is open to
 * it; a managed one is told only when its agent no longer matches the hub.
 */
function toGuidance(device: DeviceView): DeviceGuidance | null {
  const path = toDeviceUpgradePath(device);
  if (!isDeviceManaged(device)) {
    return {
      tone: "",
      icon: path === "link" ? "link" : "download",
      title: GUIDANCE_TITLES[path],
      hint: GUIDANCE_HINTS[path],
      hasEnrollmentLink: path === "link",
    };
  }
  if (device.client?.is_version_mismatched !== true) {
    return null;
  }
  return {
    tone: "notice--warn",
    icon: "alert",
    title: VERSION_MISMATCH_TITLE,
    hint: VERSION_MISMATCH_HINTS[path],
    hasEnrollmentLink: path === "link",
  };
}

/** The line above the action's output: what ran, and where it stands. */
function describeTask(
  label: string | null,
  isRunning: boolean,
  exitCode: number | null,
): string {
  const action = label ?? "action";
  if (isRunning) {
    return WORDING.running.replace("{action}", action);
  }
  if (exitCode === null) {
    return action;
  }
  return WORDING.finished
    .replace("{action}", action)
    .replace("{code}", String(exitCode));
}

/** Wording for a failed action, with the coded refusals spelled out. */
function describeActionError(cause: unknown): string {
  if (cause instanceof ApiError) {
    const wording = ACTION_ERROR_WORDING[cause.code];
    if (wording !== undefined) {
      return wording;
    }
  }
  return describeError(cause);
}
