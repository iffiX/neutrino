import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { Spinner } from "./spinner";
import { StatusDot } from "./status_dot";
import { VaultPicker } from "./vault_picker";
import { ApiError, apiPost, describeError } from "../api_client";
import { stripAnsi } from "../strip_ansi";
import { useTaskStream } from "../use_task_stream";
import type {
  DeviceInstallRequest,
  DeviceView,
  TaskStarted,
} from "../api_types";

import "./install_agent_modal.css";

/**
 * The SSH login the hub installs a machine's agent with, and the install.
 *
 * The credential is one the vault holds: a key or a login, picked here and
 * stored here where it is not stored yet. The sudo password is typed for this
 * install alone; nothing echoes either into the output below.
 */

const WORDING = {
  install: "Install the agent on {device}",
  reinstall: "Reinstall the agent on {device}",
  close: "Close",
  host: "Host",
  port: "Port",
  portInvalid: "Port must be 1–65535.",
  username: "Username",
  credential: "Credential", // scan: allow
  credentialHint: "How the hub signs in to install the agent.",
  keyKind: "SSH key",
  loginKind: "Password", // scan: allow
  key: "SSH key",
  keyHint: "The key the hub signs in with.",
  login: "Login",
  loginHint: "The stored password the hub signs in with.",
  sudoPassword: "Sudo password", // scan: allow
  sudoHint:
    "Used for this install and stored nowhere. Leave blank when the account has passwordless sudo.",
  submit: "Install agent",
  submitReinstall: "Reinstall agent",
  running: "Installing…",
  output: "Install output",
  runningLabel: "installing",
  doneLabel: "exit {code}",
};

// The {code, params} an install is refused with, worded.
const INSTALL_ERROR_WORDING: Record<string, string> = {
  agent_offline: "The machine is not answering, so nothing was started on it.",
  unknown_credential: "That credential is no longer stored; pick another.",
  agent_package_missing:
    "This hub carries no agent package for the machine's platform.",
};

const DEFAULT_SSH_PORT = 22;

/** Which of the two the person is signing in with. */
type CredentialKind = "key" | "login";

interface InstallAgentModalProps {
  device: DeviceView;
  /** Whether the machine already had an agent, which only changes wording. */
  isReinstall: boolean;
  onClose: () => void;
  /** Called once the install ends, so the page behind can read the outcome. */
  onFinished?: () => void;
}

export function InstallAgentModal({
  device,
  isReinstall,
  onClose,
  onFinished,
}: InstallAgentModalProps) {
  const [host, setHost] = useState(device.ssh?.host ?? device.ipv4_address);
  const [port, setPort] = useState(
    String(device.ssh?.port ?? DEFAULT_SSH_PORT),
  );
  const [username, setUsername] = useState(device.ssh?.username ?? "");
  const [credentialKind, setCredentialKind] = useState<CredentialKind>(
    device.ssh?.login_id != null ? "login" : "key",
  );
  const [keyId, setKeyId] = useState<string | null>(device.ssh?.key_id ?? null);
  const [loginId, setLoginId] = useState<string | null>(
    device.ssh?.login_id ?? null,
  );
  const [sudoPassword, setSudoPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const task = useTaskStream(taskId);
  const logRef = useRef<HTMLPreElement | null>(null);
  const wasRunning = useRef(false);

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

  useEffect(() => {
    const element = logRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [task.lines]);

  useEffect(() => {
    if (task.isRunning) {
      wasRunning.current = true;
      return;
    }
    if (wasRunning.current) {
      wasRunning.current = false;
      onFinished?.();
    }
  }, [task.isRunning, onFinished]);

  const isPortValid = isValidPort(port);
  const hasCredential =
    credentialKind === "key" ? keyId !== null : loginId !== null;
  const isReady =
    host.trim().length > 0 &&
    username.trim().length > 0 &&
    isPortValid &&
    hasCredential &&
    !task.isRunning;
  const deviceName = device.name ?? device.mac_address;

  const handleSubmit = async () => {
    setError(null);
    setTaskId(null);
    const request: DeviceInstallRequest = {
      action: "install_client",
      host: host.trim(),
      port: Number(port),
      username: username.trim(),
      key_id: credentialKind === "key" ? keyId : null,
      login_id: credentialKind === "login" ? loginId : null,
      sudo_password: sudoPassword,
    };
    try {
      const started = await apiPost<TaskStarted>(
        `/devices/${device.mac_address}/action`,
        request,
      );
      setTaskId(started.task_id);
    } catch (cause: unknown) {
      setError(describeInstallError(cause));
    }
  };

  // A portal, so no ancestor's transform or scroll container can capture the
  // fixed backdrop.
  return createPortal(
    <div
      className="install_modal_backdrop"
      role="dialog"
      aria-modal="true"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="install_modal">
        <div className="install_modal_head">
          <div className="install_modal_title">
            <Icon name="download" size={15} />
            <h2>
              {(isReinstall ? WORDING.reinstall : WORDING.install).replace(
                "{device}",
                deviceName,
              )}
            </h2>
          </div>
          <button
            type="button"
            className="button button--small"
            onClick={onClose}
          >
            <Icon name="close" size={13} />
            {WORDING.close}
          </button>
        </div>

        <div className="install_modal_body">
          {error !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{error}</div>
            </div>
          )}

          <div className="field_grid">
            <label className="field">
              <span className="field_label">{WORDING.host}</span>
              <input
                className="input"
                value={host}
                onChange={(event) => setHost(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field_label">{WORDING.port}</span>
              <input
                className={`input ${isPortValid ? "" : "input--invalid"}`}
                value={port}
                inputMode="numeric"
                onChange={(event) => setPort(event.target.value)}
              />
              {!isPortValid && (
                <span className="field_error">{WORDING.portInvalid}</span>
              )}
            </label>
            <label className="field">
              <span className="field_label">{WORDING.username}</span>
              <input
                className="input"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field_label">{WORDING.credential}</span>
              <select
                className="select"
                value={credentialKind}
                onChange={(event) =>
                  setCredentialKind(event.target.value as CredentialKind)
                }
              >
                <option value="key">{WORDING.keyKind}</option>
                <option value="login">{WORDING.loginKind}</option>
              </select>
              <span className="field_hint">{WORDING.credentialHint}</span>
            </label>
          </div>

          {credentialKind === "key" ? (
            <VaultPicker
              kind="ssh_key"
              value={keyId}
              onChange={setKeyId}
              label={WORDING.key}
              hint={WORDING.keyHint}
            />
          ) : (
            <VaultPicker
              kind="login"
              value={loginId}
              onChange={setLoginId}
              label={WORDING.login}
              hint={WORDING.loginHint}
            />
          )}

          <label className="field">
            <span className="field_label">{WORDING.sudoPassword}</span>
            <PasswordInput value={sudoPassword} onChange={setSudoPassword} />
            <span className="field_hint">{WORDING.sudoHint}</span>
          </label>

          {taskId !== null && (
            <div className="install_modal_log">
              <div className="install_modal_log_head">
                <span className="section_label">{WORDING.output}</span>
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
                      ? WORDING.runningLabel
                      : WORDING.doneLabel.replace(
                          "{code}",
                          String(task.exitCode ?? ""),
                        )
                  }
                />
              </div>
              <pre className="install_modal_log_output" ref={logRef}>
                {stripAnsi(task.lines.join("\n"))}
              </pre>
              {task.error !== null && (
                <span className="field_error">{task.error}</span>
              )}
            </div>
          )}
        </div>

        <div className="install_modal_foot">
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={!isReady}
            onClick={() => void handleSubmit()}
          >
            {task.isRunning ? (
              <Spinner size={13} />
            ) : (
              <Icon name="download" size={14} />
            )}
            {task.isRunning
              ? WORDING.running
              : isReinstall
                ? WORDING.submitReinstall
                : WORDING.submit}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Wording for a refused install, from the code the API returned. */
function describeInstallError(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.code === "unsupported_remote_install") {
      const detail = cause.detail as Record<string, unknown> | null;
      const os = String(detail?.os ?? "");
      return `This machine reports ${os || "another OS"}; the SSH installer is for Linux. Send it an enrollment link instead.`;
    }
    const wording = INSTALL_ERROR_WORDING[cause.code];
    if (wording !== undefined) {
      return wording;
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
