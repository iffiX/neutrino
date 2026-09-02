import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import type { IconName } from "./icon";
import { DeviceEnrollmentNotice } from "./device_enrollment_notice";
import { DeviceFeatures } from "./device_features";
import { FileTransferModal } from "./file_transfer_modal";
import { PasswordInput } from "./password_input";
import { StatusDot } from "./status_dot";
import { TerminalModal } from "./terminal_modal";
import { RemoteDesktopPanel } from "./remote_desktop_panel";
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
import { PRIVATE_KEY_PLACEHOLDER } from "../private_key_placeholder";
import { stripAnsi } from "../strip_ansi";
import { useApiResource } from "../use_api_resource";
import { useTaskStream } from "../use_task_stream";
import type {
  DeviceActionName,
  DeviceActionResult,
  DeviceAnnotation,
  DeviceAuthMethod,
  DeviceEnrollmentView,
  DeviceView,
  DeviceWolResult,
  KeyView,
  KeysResponse,
  PasswordView,
  PasswordsResponse,
} from "../api_types";

import "./device_drawer.css";

/**
 * The detail view for one device: identity, credentials, and remote actions.
 *
 * Everything an action needs comes from the SSH block, so a device without one
 * gets the status header and the credential form and nothing else — offering a
 * reboot button that can only fail would be worse than not offering it. Action
 * output streams into the log at the bottom rather than into a toast, because
 * an install is a thing you read, not a thing you acknowledge.
 */

const DEFAULT_SSH_PORT = 22;

// The <select> sentinel for "paste a new key" rather than choosing an existing
// one.
const NEW_KEY_OPTION = "__new__";

// The password pickers' sentinel for "store a new password" rather than
// choosing an existing one.
const NEW_PASSWORD_OPTION = "__new__";

// Wording for the way this device becomes managed, or catches up with the hub.
const GUIDANCE_TITLES: Record<DeviceUpgradePath, string> = {
  install: "Install the agent to manage this device.",
  link: "No credentials for this machine yet.",
};

const GUIDANCE_HINTS: Record<DeviceUpgradePath, string> = {
  install: "The Install agent action below runs the installer over SSH.",
  link: "Add SSH details above and save, or send it an enrollment link.",
};

const VERSION_MISMATCH_TITLE =
  "This agent is a different version from the hub.";

const VERSION_MISMATCH_HINTS: Record<DeviceUpgradePath, string> = {
  install: "Reinstall it with the Install agent action below.",
  link: "Re-enroll it with a fresh link. The SSH installer needs Linux.",
};

// Wording for the save refusals the backend reports as codes.
const UNKNOWN_CREDENTIAL_WORDING: Record<string, string> = {
  key_id: "The chosen SSH key is no longer stored; pick another.",
  password_id: "The chosen password is no longer stored; pick another.",
  sudo_password_id:
    "The chosen sudo password is no longer stored; pick another.",
};

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

const DEVICE_ACTIONS: DeviceAction[] = [
  {
    action: "install_client",
    label: "Install agent",
    icon: "download",
    isDestructive: false,
  },
  { action: "reboot", label: "Reboot", icon: "refresh", isDestructive: true },
  {
    action: "shutdown",
    label: "Shut down",
    icon: "power",
    isDestructive: true,
  },
];

interface DeviceDrawerProps {
  device: DeviceView;
  onClose: () => void;
  onSaved: (device: DeviceView) => void;
  onForgotten: (macAddress: string) => void;
}

export function DeviceDrawer({
  device,
  onClose,
  onSaved,
  onForgotten,
}: DeviceDrawerProps) {
  const [name, setName] = useState(device.name ?? "");
  const [icon, setIcon] = useState<IconName>(toDeviceIconName(device.icon));
  const [isWolEnabled, setIsWolEnabled] = useState(device.is_wol_enabled);
  const [hasSshDraft, setHasSshDraft] = useState(device.ssh !== null);
  const [host, setHost] = useState(device.ssh?.host ?? device.ipv4_address);
  const [port, setPort] = useState(
    String(device.ssh?.port ?? DEFAULT_SSH_PORT),
  );
  const [username, setUsername] = useState(device.ssh?.username ?? "");
  const [auth, setAuth] = useState<DeviceAuthMethod>(device.ssh?.auth ?? "key");
  // Key auth references a stored key by id. The keys come from the registry, so
  // the drawer never holds key material — it either picks an existing key or
  // pastes a new one, which is created in the registry on save.
  const keys = useApiResource<KeysResponse>("/credentials/ssh_keys");
  const [keyId, setKeyId] = useState<string>(device.ssh?.key_id ?? "");
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyMaterial, setNewKeyMaterial] = useState("");
  const [newKeyPassphrase, setNewKeyPassphrase] = useState("");
  // Password auth references a vault password by id, the same way key auth
  // references a key: pick a stored one, or store a new one on save.
  const passwords = useApiResource<PasswordsResponse>("/credentials/passwords");
  const [passwordId, setPasswordId] = useState<string>(
    device.ssh?.password_id ?? "",
  );
  const [sudoPasswordId, setSudoPasswordId] = useState<string>(
    device.ssh?.sudo_password_id ?? "",
  );
  const [newPasswordName, setNewPasswordName] = useState("");
  const [newPasswordValue, setNewPasswordValue] = useState("");
  const [newSudoPasswordName, setNewSudoPasswordName] = useState("");
  const [newSudoPasswordValue, setNewSudoPasswordValue] = useState("");
  const isAddingKey = keyId === NEW_KEY_OPTION;
  const isAddingPassword = passwordId === NEW_PASSWORD_OPTION;
  const isAddingSudoPassword = sudoPasswordId === NEW_PASSWORD_OPTION;

  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();
  const [taskId, setTaskId] = useState<string | null>(null);
  const [runningLabel, setRunningLabel] = useState<string | null>(null);
  const [isTerminalOpen, setIsTerminalOpen] = useState(false);
  const [isFilesOpen, setIsFilesOpen] = useState(false);
  // A link minted for this machine alone, for the ones no installer reaches.
  const [enrollment, setEnrollment] = useState<DeviceEnrollmentView | null>(
    null,
  );

  const task = useTaskStream(taskId);
  const logRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    const element = logRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [task.lines]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isTerminalOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, isTerminalOpen]);

  const reach = toDeviceReach(device);
  const presence = toDevicePresence(device);
  const guidance = toGuidance(device);
  const isPortValid = isValidPort(port);
  const isSshComplete =
    !hasSshDraft ||
    (host.trim().length > 0 && username.trim().length > 0 && isPortValid);

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      // A new credential is created first, then the device references it —
      // the same key or password any other device can then reuse.
      let resolvedKeyId = keyId;
      if (hasSshDraft && auth === "key" && isAddingKey) {
        const created = await apiPost<KeyView>("/credentials/ssh_keys", {
          name: newKeyName.trim() || `${name.trim() || host.trim()} key`,
          private_key: newKeyMaterial,
          passphrase: newKeyPassphrase.length > 0 ? newKeyPassphrase : null,
        });
        resolvedKeyId = created.id;
      }
      let resolvedPasswordId = passwordId;
      if (hasSshDraft && auth === "password" && isAddingPassword) {
        const created = await apiPost<PasswordView>("/credentials/passwords", {
          name: newPasswordName.trim() || `${name.trim() || host.trim()} login`,
          password: newPasswordValue,
        });
        resolvedPasswordId = created.id;
      }
      let resolvedSudoPasswordId = sudoPasswordId;
      if (hasSshDraft && isAddingSudoPassword) {
        const created = await apiPost<PasswordView>("/credentials/passwords", {
          name:
            newSudoPasswordName.trim() || `${name.trim() || host.trim()} sudo`,
          password: newSudoPasswordValue,
        });
        resolvedSudoPasswordId = created.id;
      }
      const annotation: DeviceAnnotation = {
        name: name.trim(),
        icon,
        is_wol_enabled: isWolEnabled,
        ssh: hasSshDraft
          ? {
              host: host.trim(),
              port: Number(port),
              username: username.trim(),
              auth,
              key_id: auth === "key" ? resolvedKeyId || null : null,
              key_name: null,
              password_id:
                auth === "password" ? resolvedPasswordId || null : null,
              sudo_password_id: resolvedSudoPasswordId || null,
            }
          : null,
      };
      const saved = await apiPut<DeviceView>(
        `/devices/${device.mac_address}`,
        annotation,
      );
      onSaved(saved);
      setKeyId(saved.ssh?.key_id ?? "");
      setPasswordId(saved.ssh?.password_id ?? "");
      setSudoPasswordId(saved.ssh?.sudo_password_id ?? "");
      setNewKeyName("");
      setNewKeyMaterial("");
      setNewKeyPassphrase("");
      setNewPasswordName("");
      setNewPasswordValue("");
      setNewSudoPasswordName("");
      setNewSudoPasswordValue("");
      if (isAddingKey) {
        keys.reload();
      }
      if (isAddingPassword || isAddingSudoPassword) {
        passwords.reload();
      }
      setNotice("Saved.");
    } catch (cause: unknown) {
      setError(describeSaveError(cause));
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
    if (!deviceAction.isDestructive) {
      void runAction(deviceAction);
      return;
    }
    confirm.ask({
      title: `${deviceAction.label} ${device.name ?? device.mac_address}`,
      body: "The machine is told to do this at once; anything unsaved on it is lost.",
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
      const result = await apiPost<DeviceActionResult>(
        `/devices/${device.mac_address}/action`,
        { action: deviceAction.action },
      );
      setTaskId(result.task_id);
    } catch (cause: unknown) {
      setRunningLabel(null);
      setError(describeActionError(cause));
    }
  };

  const handleForget = () =>
    confirm.ask({
      title: `Forget ${device.name ?? device.mac_address}`,
      body: "The device and its saved credentials are deleted from this box.",
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
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={onClose}
            aria-label="Close"
          >
            <Icon name="close" size={15} />
          </button>
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
                  ? "reporting"
                  : presence === "seen"
                    ? "on the network"
                    : "offline"}
              </span>
              <span className="badge">{device.vendor || "unknown vendor"}</span>
              {device.client !== null && (
                <span className="badge">
                  seen {formatTimeAgo(device.client.last_seen)}
                </span>
              )}
            </div>
          </div>

          {error !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{error}</div>
            </div>
          )}

          {notice !== null && (
            <div className="notice notice--ok">
              <Icon name="check" size={15} />
              <div className="notice_body">{notice}</div>
            </div>
          )}

          <div className="device_drawer_section">
            <span className="section_label">Identity</span>
            <label className="field">
              <span className="field_label">Display name</span>
              <input
                className="input"
                value={name}
                placeholder={device.mac_address}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <div className="field">
              <span className="field_label">Icon</span>
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
            <span className="section_label">SSH credentials</span>
            <ToggleSwitch
              isOn={hasSshDraft}
              onChange={setHasSshDraft}
              label="Manage this device over SSH"
              description="Whether this device is managed over SSH. It unlocks the terminal, one-click installs, reboot and shutdown."
            />

            {hasSshDraft && (
              <>
                <div className="field_grid">
                  <label className="field">
                    <span className="field_label">Host</span>
                    <input
                      className="input"
                      value={host}
                      onChange={(event) => setHost(event.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span className="field_label">Port</span>
                    <input
                      className={`input ${isPortValid ? "" : "input--invalid"}`}
                      value={port}
                      inputMode="numeric"
                      onChange={(event) => setPort(event.target.value)}
                    />
                    {!isPortValid && (
                      <span className="field_error">Port must be 1–65535.</span>
                    )}
                  </label>
                  <label className="field">
                    <span className="field_label">Username</span>
                    <input
                      className="input"
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span className="field_label">Authentication</span>
                    <select
                      className="select"
                      value={auth}
                      onChange={(event) =>
                        setAuth(event.target.value as DeviceAuthMethod)
                      }
                    >
                      <option value="key">Private key</option>
                      <option value="password">Password</option>
                    </select>
                  </label>
                </div>

                {auth === "key" ? (
                  <>
                    <label className="field">
                      <span className="field_label">SSH key</span>
                      <select
                        className="select"
                        value={keyId}
                        onChange={(event) => setKeyId(event.target.value)}
                      >
                        <option value="">Select a key…</option>
                        {(keys.data?.keys ?? []).map((storedKey) => (
                          <option key={storedKey.id} value={storedKey.id}>
                            {storedKey.name} · {shortFingerprint(storedKey)}
                          </option>
                        ))}
                        <option value={NEW_KEY_OPTION}>
                          ＋ Paste a new key…
                        </option>
                      </select>
                      <span className="field_hint">
                        Pick a stored key, or paste a new one.
                      </span>
                    </label>
                    {isAddingKey && (
                      <div className="device_drawer_newkey">
                        <label className="field">
                          <span className="field_label">New key name</span>
                          <input
                            className="input"
                            value={newKeyName}
                            placeholder={`${name.trim() || "device"} key`}
                            onChange={(event) =>
                              setNewKeyName(event.target.value)
                            }
                          />
                        </label>
                        <label className="field">
                          <span className="field_label">Private key</span>
                          <textarea
                            className="input input--key"
                            value={newKeyMaterial}
                            spellCheck={false}
                            autoComplete="off"
                            rows={8}
                            placeholder={PRIVATE_KEY_PLACEHOLDER}
                            onChange={(event) =>
                              setNewKeyMaterial(event.target.value)
                            }
                          />
                          <span className="field_hint">
                            Stored on the gateway readable only by root, and
                            never shown again.
                          </span>
                        </label>
                        <label className="field">
                          <span className="field_label">Key passphrase</span>
                          <PasswordInput
                            value={newKeyPassphrase}
                            onChange={setNewKeyPassphrase}
                          />
                          <span className="field_hint">
                            Only if the key is encrypted. Leave blank otherwise.
                          </span>
                        </label>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <label className="field">
                      <span className="field_label">Password</span>
                      <select
                        className="select"
                        value={passwordId}
                        onChange={(event) => setPasswordId(event.target.value)}
                      >
                        <option value="">Select a password…</option>
                        {(passwords.data?.passwords ?? []).map(
                          (storedPassword) => (
                            <option
                              key={storedPassword.id}
                              value={storedPassword.id}
                            >
                              {storedPassword.name}
                            </option>
                          ),
                        )}
                        <option value={NEW_PASSWORD_OPTION}>
                          ＋ Store a new password…
                        </option>
                      </select>
                      <span className="field_hint">
                        Pick a stored password, or store a new one.
                      </span>
                    </label>
                    {isAddingPassword && (
                      <div className="device_drawer_newkey">
                        <label className="field">
                          <span className="field_label">New password name</span>
                          <input
                            className="input"
                            value={newPasswordName}
                            placeholder={`${name.trim() || host.trim() || "device"} login`}
                            onChange={(event) =>
                              setNewPasswordName(event.target.value)
                            }
                          />
                        </label>
                        <label className="field">
                          <span className="field_label">Password</span>
                          <PasswordInput
                            value={newPasswordValue}
                            onChange={setNewPasswordValue}
                          />
                          <span className="field_hint">
                            Sealed in the vault and never shown again.
                          </span>
                        </label>
                      </div>
                    )}
                  </>
                )}

                <label className="field">
                  <span className="field_label">Sudo password</span>
                  <select
                    className="select"
                    value={sudoPasswordId}
                    onChange={(event) => setSudoPasswordId(event.target.value)}
                  >
                    <option value="">(none)</option>
                    {(passwords.data?.passwords ?? []).map((storedPassword) => (
                      <option key={storedPassword.id} value={storedPassword.id}>
                        {storedPassword.name}
                      </option>
                    ))}
                    <option value={NEW_PASSWORD_OPTION}>
                      ＋ Store a new password…
                    </option>
                  </select>
                  <span className="field_hint">
                    Needed for installs. Leave (none) when the account has
                    passwordless sudo.
                  </span>
                </label>
                {isAddingSudoPassword && (
                  <div className="device_drawer_newkey">
                    <label className="field">
                      <span className="field_label">New password name</span>
                      <input
                        className="input"
                        value={newSudoPasswordName}
                        placeholder={`${name.trim() || host.trim() || "device"} sudo`}
                        onChange={(event) =>
                          setNewSudoPasswordName(event.target.value)
                        }
                      />
                    </label>
                    <label className="field">
                      <span className="field_label">Sudo password</span>
                      <PasswordInput
                        value={newSudoPasswordValue}
                        onChange={setNewSudoPasswordValue}
                      />
                      <span className="field_hint">
                        Sealed in the vault and never shown again.
                      </span>
                    </label>
                  </div>
                )}

                <ToggleSwitch
                  isOn={isWolEnabled}
                  onChange={setIsWolEnabled}
                  label="Wake-on-LAN"
                  description="Whether this device can be woken with a magic packet sent to its MAC from the LAN interface."
                />
              </>
            )}
          </div>

          <div className="device_drawer_section">
            <span className="section_label">Actions</span>
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
                        Get link
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
            {reach !== "none" && (
              <div className="device_drawer_actions">
                <button
                  type="button"
                  className="button"
                  onClick={() => void handleWakeOnLan()}
                >
                  <Icon name="bolt" size={14} />
                  Wake-on-LAN
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => setIsTerminalOpen(true)}
                >
                  <Icon name="terminal" size={14} />
                  Open terminal
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => setIsFilesOpen(true)}
                >
                  <Icon name="folder" size={14} />
                  Transfer files
                </button>
                {DEVICE_ACTIONS.map((deviceAction) => (
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
                ))}
              </div>
            )}
          </div>

          <DeviceFeatures macAddress={device.mac_address} />

          {device.ssh !== null && <RemoteDesktopPanel device={device} />}

          {(taskId !== null || task.lines.length > 0) && (
            <div className="device_drawer_log">
              <div className="device_drawer_log_head">
                <span className="section_label">
                  {runningLabel ?? "Action"} output
                </span>
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
                  label={
                    task.isRunning
                      ? "running"
                      : task.exitCode === null
                        ? "idle"
                        : `exit ${task.exitCode}`
                  }
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
        </div>

        <div className="device_drawer_footer">
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => handleForget()}
          >
            <Icon name="trash" size={13} />
            Forget device
          </button>
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={isSaving || !isSshComplete}
            onClick={() => void handleSave()}
          >
            <Icon name="check" size={14} />
            {isSaving ? "Saving…" : "Save device"}
          </button>
        </div>
      </aside>

      {isTerminalOpen && (
        <TerminalModal
          device={device}
          onClose={() => setIsTerminalOpen(false)}
        />
      )}

      {isFilesOpen && (
        <FileTransferModal
          device={device}
          onClose={() => setIsFilesOpen(false)}
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

/** Wording for a failed save, with the coded refusals spelled out. */
function describeActionError(cause: unknown): string {
  if (
    cause instanceof ApiError &&
    cause.code === "unsupported_remote_install" &&
    typeof cause.detail === "object" &&
    cause.detail !== null
  ) {
    const os = String((cause.detail as Record<string, unknown>).os ?? "");
    return `This machine reports ${os || "another OS"}; the SSH installer is for Linux — use Get link instead.`;
  }
  return describeError(cause);
}

function describeSaveError(cause: unknown): string {
  if (
    cause instanceof ApiError &&
    typeof cause.detail === "object" &&
    cause.detail !== null
  ) {
    const detail = cause.detail as Record<string, unknown>;
    if (detail.code === "unknown_credential") {
      const wording = UNKNOWN_CREDENTIAL_WORDING[String(detail.field)];
      if (wording !== undefined) {
        return wording;
      }
    }
  }
  return describeError(cause);
}

function isValidPort(value: string): boolean {
  if (!/^\d{1,5}$/.test(value)) {
    return false;
  }
  const port = Number(value);
  return port >= 1 && port <= 65535;
}

// Enough of the fingerprint to tell two keys apart in a dropdown, without
// filling the row.
function shortFingerprint(key: KeyView): string {
  const body = key.fingerprint.replace(/^SHA256:/, "");
  return body.length > 12 ? `${body.slice(0, 12)}…` : body;
}
