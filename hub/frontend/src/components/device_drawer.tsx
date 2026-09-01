import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import type { IconName } from "./icon";
import { DeviceFeatures } from "./device_features";
import { FileTransferModal } from "./file_transfer_modal";
import { PasswordInput } from "./password_input";
import { StatusDot } from "./status_dot";
import { TerminalModal } from "./terminal_modal";
import { RemoteDesktopPanel } from "./remote_desktop_panel";
import { ToggleSwitch } from "./toggle_switch";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
import { DEVICE_ICON_NAMES, toDeviceIconName } from "../device_icon";
import {
  DEVICE_REACH_LABELS,
  toDeviceReach,
  toDevicePresence,
} from "../device_level";
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
  DeviceView,
  DeviceWolResult,
  KeyView,
  KeysResponse,
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

interface DeviceAction {
  action: DeviceActionName;
  label: string;
  icon: IconName;
  isDestructive: boolean;
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
  // Passwords start blank on every open: the gateway never sends them back, and
  // leaving one blank on save keeps whatever is already stored.
  const [password, setPassword] = useState("");
  const [sudoPassword, setSudoPassword] = useState("");
  const hasStoredSudoPassword = device.ssh?.has_sudo_password ?? false;
  const isAddingKey = keyId === NEW_KEY_OPTION;

  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();
  const [taskId, setTaskId] = useState<string | null>(null);
  const [runningLabel, setRunningLabel] = useState<string | null>(null);
  const [isTerminalOpen, setIsTerminalOpen] = useState(false);
  const [isFilesOpen, setIsFilesOpen] = useState(false);

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
  const isPortValid = isValidPort(port);
  const isSshComplete =
    !hasSshDraft ||
    (host.trim().length > 0 && username.trim().length > 0 && isPortValid);

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      // Pasting a new key creates it in the registry first, then the device
      // references it — the same key any other device can then reuse.
      let resolvedKeyId = keyId;
      if (auth === "key" && isAddingKey) {
        const created = await apiPost<KeyView>("/credentials/ssh_keys", {
          name: newKeyName.trim() || `${name.trim() || host.trim()} key`,
          private_key: newKeyMaterial,
          passphrase: newKeyPassphrase.length > 0 ? newKeyPassphrase : null,
        });
        resolvedKeyId = created.id;
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
              key_id:
                auth === "key" && resolvedKeyId !== NEW_KEY_OPTION
                  ? resolvedKeyId || null
                  : null,
              key_name: null,
              password:
                auth === "password" && password.length > 0 ? password : null,
              sudo_password: sudoPassword.length > 0 ? sudoPassword : null,
              has_sudo_password: hasStoredSudoPassword,
            }
          : null,
      };
      const saved = await apiPut<DeviceView>(
        `/devices/${device.mac_address}`,
        annotation,
      );
      onSaved(saved);
      setKeyId(saved.ssh?.key_id ?? "");
      setNewKeyName("");
      setNewKeyMaterial("");
      setNewKeyPassphrase("");
      setNotice("Saved.");
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsSaving(false);
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
      setError(describeError(cause));
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
              description="Unlocks the terminal, one-click installs, reboot and shutdown."
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
                  <label className="field">
                    <span className="field_label">Password</span>
                    <PasswordInput value={password} onChange={setPassword} />
                  </label>
                )}

                <label className="field">
                  <span className="field_label">
                    Sudo password
                    {hasStoredSudoPassword ? (
                      <span className="field_badge">stored</span>
                    ) : null}
                  </span>
                  <PasswordInput
                    value={sudoPassword}
                    onChange={setSudoPassword}
                  />
                  <span className="field_hint">
                    {hasStoredSudoPassword
                      ? "Stored; type a new one to replace it."
                      : "Needed for installs. Leave blank when the account has passwordless sudo."}
                  </span>
                </label>

                <ToggleSwitch
                  isOn={isWolEnabled}
                  onChange={setIsWolEnabled}
                  label="Wake-on-LAN"
                  description="Send a magic packet to this MAC from the LAN interface."
                />
              </>
            )}
          </div>

          <div className="device_drawer_section">
            <span className="section_label">Actions</span>
            {reach === "none" ? (
              <div className="notice">
                <Icon name="lock" size={15} />
                <div className="notice_body">
                  <strong>No credentials yet.</strong>
                  <span className="muted">
                    Add SSH details above and save to enable actions.
                  </span>
                </div>
              </div>
            ) : (
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
