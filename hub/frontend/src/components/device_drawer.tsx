import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";

import { Icon } from "./icon";
import type { IconName } from "./icon";
import { DeviceEnrollmentNotice } from "./device_enrollment_notice";
import { InstallAgentModal } from "./install_agent_modal";
import { RemoteDesktopPanel } from "./remote_desktop_panel";
import { StatusDot } from "./status_dot";
import {
  ApiError,
  apiDelete,
  apiPost,
  apiPut,
  describeError,
} from "../api_client";
import { DEVICE_ICON_NAMES, toDeviceIconName } from "../device_icon";
import {
  DEVICE_REACH_KEYS,
  isDeviceManaged,
  toDeviceReach,
  toDevicePresence,
  toDeviceUpgradePath,
} from "../device_level";
import type { DeviceUpgradePath } from "../device_level";
import { t, useLanguage } from "../i18n";
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
 * one record: its name, its icon, and the remote actions it takes. Action
 * output streams into the log at the
 * bottom rather than into a toast, because an install is a thing you read.
 */

// Wording for the way this device becomes managed, or catches up with the hub.
const GUIDANCE_TITLE_KEYS: Record<DeviceUpgradePath, string> = {
  install: "ui.drawer.guidance_install_title",
  link: "ui.drawer.guidance_link_title",
};

const GUIDANCE_HINT_KEYS: Record<DeviceUpgradePath, string> = {
  install: "ui.drawer.guidance_install_hint",
  link: "ui.drawer.guidance_link_hint",
};

const VERSION_MISMATCH_HINT_KEYS: Record<DeviceUpgradePath, string> = {
  install: "ui.drawer.version_mismatch_install_hint",
  link: "ui.drawer.version_mismatch_link_hint",
};

// The agent's last_error {code, params}, worded. A code without an entry
// shows as itself, because a failure hidden entirely is worse than a bare
// code.
const AGENT_ERROR_KEYS: Record<string, string> = {
  unsupported_platform: "code.unsupported_platform",
  update_failed: "code.update_failed",
  agent_package_missing: "code.agent_package_missing",
  agent_package_fetch_failed: "code.agent_package_fetch_failed",
  agent_package_sha256_mismatch: "code.agent_package_sha256_mismatch",
  agent_package_cache_unwritable: "code.agent_package_cache_unwritable",
};

// The {code, params} an action is refused with, worded.
const ACTION_ERROR_KEYS: Record<string, string> = {
  agent_offline: "ui.devices.agent_offline",
};

/** One remote action, as the grid draws it. */
interface DeviceAction {
  action: DeviceActionName;
  labelKey: string;
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
    labelKey: "ui.drawer.reinstall",
    icon: "download",
    isDestructive: false,
  },
  {
    action: "reboot",
    labelKey: "ui.drawer.reboot",
    icon: "refresh",
    isDestructive: true,
  },
  {
    action: "shutdown",
    labelKey: "ui.drawer.shutdown",
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
  // Redrawn when the panel's language changes.
  useLanguage();
  const navigate = useNavigate();
  const [name, setName] = useState(device.name ?? "");
  const [icon, setIcon] = useState<IconName>(toDeviceIconName(device.icon));
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
      };
      onSaved(
        await apiPut<DeviceView>(`/devices/${device.mac_address}`, annotation),
      );
      setNotice(t("ui.drawer.saved"));
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
      title: t("ui.drawer.action_title", {
        action: t(deviceAction.labelKey),
        name: device.name ?? device.mac_address,
      }),
      body: t("ui.drawer.action_body"),
      confirmLabel: t(deviceAction.labelKey),
      onConfirm: () => void runAction(deviceAction),
    });
  };

  const runAction = async (deviceAction: DeviceAction) => {
    setError(null);
    setNotice(null);
    setTaskId(null);
    setRunningLabel(t(deviceAction.labelKey));
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
      title: t("ui.drawer.forget_title", {
        name: device.name ?? device.mac_address,
      }),
      body: t("ui.drawer.forget_body"),
      confirmLabel: t("ui.drawer.forget_confirm"),
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
                  {t("ui.drawer.terminal")}
                </button>
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => openPage("/files")}
                >
                  <Icon name="folder" size={13} />
                  {t("ui.drawer.files")}
                </button>
              </>
            )}
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={onClose}
              aria-label={t("ui.drawer.close")}
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
                {t(DEVICE_REACH_KEYS[reach])}
              </span>
              <span
                className={`badge ${presence === "offline" ? "badge--warn" : "badge--ok"}`}
              >
                {presence === "reporting"
                  ? t("state.reporting")
                  : presence === "seen"
                    ? t("state.on_the_network")
                    : t("state.offline")}
              </span>
              <span className="badge">
                {device.client?.hostname ??
                  (device.vendor || t("ui.drawer.unknown_vendor"))}
              </span>
              {device.client !== null && !device.client.is_online && (
                <span className="badge">
                  {t("ui.drawer.seen_ago", {
                    when: formatTimeAgo(device.client.last_seen),
                  })}
                </span>
              )}
            </div>
            {device.client?.last_error != null && (
              <div className="notice notice--warn">
                <Icon name="alert" size={15} />
                <div className="notice_body">
                  {describeAgentError(device.client.last_error.code)}
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
            <span className="section_label">{t("ui.drawer.identity")}</span>
            <label className="field">
              <span className="field_label">{t("ui.drawer.display_name")}</span>
              <input
                className="input"
                value={name}
                placeholder={device.mac_address}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <div className="field">
              <span className="field_label">{t("ui.drawer.icon")}</span>
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
          </div>

          <div className="device_drawer_section">
            <span className="section_label">{t("ui.drawer.actions")}</span>
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
                        {t("ui.drawer.get_link")}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
            {enrollment !== null && (
              <DeviceEnrollmentNotice
                link={enrollment.link}
                expiresInS={enrollment.expires_in_s}
                title={t("ui.drawer.enrollment_title", {
                  name: device.name ?? device.mac_address,
                })}
                hint={t("ui.drawer.enrollment_hint")}
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
                {t("ui.drawer.wake")}
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
                    {t(deviceAction.labelKey)}
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
                  {t("ui.drawer.install")}
                </button>
              )}
            </div>
          </div>

          {taskId !== null && (
            <div className="device_drawer_log">
              <div className="device_drawer_log_head">
                <span className="section_label">{t("ui.drawer.output")}</span>
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
                    {t("ui.drawer.command_results")}
                  </span>
                </div>
                {device.client.command_results.map((outcome) => (
                  <div key={outcome.id} className="device_drawer_log_head">
                    <StatusDot
                      tone={outcome.exit_code === 0 ? "ok" : "error"}
                      isPulsing={false}
                      label={t("ui.drawer.command_result", {
                        id: outcome.id,
                        code: outcome.exit_code,
                        when: formatTimeAgo(outcome.finished_at),
                      })}
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
              {t("ui.drawer.forget")}
            </button>
          )}
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={isSaving}
            onClick={() => void handleSave()}
          >
            <Icon name="check" size={14} />
            {isSaving ? t("ui.drawer.saving") : t("ui.drawer.save")}
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
      title: t(GUIDANCE_TITLE_KEYS[path]),
      hint: t(GUIDANCE_HINT_KEYS[path]),
      hasEnrollmentLink: path === "link",
    };
  }
  if (device.client?.is_version_mismatched !== true) {
    return null;
  }
  return {
    tone: "notice--warn",
    icon: "alert",
    title: t("ui.drawer.version_mismatch_title"),
    hint: t(VERSION_MISMATCH_HINT_KEYS[path]),
    hasEnrollmentLink: path === "link",
  };
}

/** The line above the action's output: what ran, and where it stands. */
function describeTask(
  label: string | null,
  isRunning: boolean,
  exitCode: number | null,
): string {
  const action = label ?? t("ui.drawer.task_action");
  if (isRunning) {
    return t("ui.drawer.task_running", { action });
  }
  if (exitCode === null) {
    return action;
  }
  return t("ui.drawer.task_finished", { action, code: exitCode });
}

/** One agent failure, worded, or the bare code where none is worded. */
function describeAgentError(code: string): string {
  const key = AGENT_ERROR_KEYS[code];
  return key === undefined ? code : t(key);
}

/** Wording for a failed action, with the coded refusals spelled out. */
function describeActionError(cause: unknown): string {
  if (cause instanceof ApiError) {
    const key = ACTION_ERROR_KEYS[cause.code];
    if (key !== undefined) {
      return t(key);
    }
  }
  return describeError(cause);
}
