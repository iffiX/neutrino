import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { Spinner } from "./spinner";
import { StatusDot } from "./status_dot";
import { ToggleSwitch } from "./toggle_switch";
import { ApiError, apiPost, describeError } from "../api_client";
import { stripAnsi } from "../strip_ansi";
import { useApiResource } from "../use_api_resource";
import { useTaskStream } from "../use_task_stream";
import type {
  DeviceInstallRequest,
  DeviceView,
  KeysResponse,
  KeyView,
  LoginsResponse,
  LoginView,
  TaskStarted,
} from "../api_types";

import "./install_agent_modal.css";

/**
 * The SSH login the hub installs a machine's agent with, and the install.
 *
 * The credential is one of three: a key the vault holds, a login it holds, or
 * a password typed here, which is kept only if the person asks for it. The
 * sudo password is typed for this install alone; nothing echoes either into
 * the output below.
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
  storedKey: "An SSH key from the vault",
  storedLogin: "A stored login",
  typedPassword: "A password typed now", // scan: allow
  pickKey: "Select a key…",
  pickLogin: "Select a login…",
  password: "Password", // scan: allow
  savePassword: "Save to the vault", // scan: allow
  savePasswordHint:
    "Whether this password is kept as a login other devices can use.",
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

/** Which of the three the person is signing in with. */
type CredentialKind = "key" | "login" | "password";

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
  const keys = useApiResource<KeysResponse>("/credentials/ssh_keys");
  const logins = useApiResource<LoginsResponse>("/credentials/logins");
  const [host, setHost] = useState(device.ssh?.host ?? device.ipv4_address);
  const [port, setPort] = useState(
    String(device.ssh?.port ?? DEFAULT_SSH_PORT),
  );
  const [username, setUsername] = useState(device.ssh?.username ?? "");
  const [credentialKind, setCredentialKind] = useState<CredentialKind>(
    device.ssh?.login_id != null ? "login" : "key",
  );
  const [keyId, setKeyId] = useState(device.ssh?.key_id ?? "");
  const [loginId, setLoginId] = useState(device.ssh?.login_id ?? "");
  const [password, setPassword] = useState("");
  const [isPasswordSaved, setIsPasswordSaved] = useState(false);
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
    credentialKind === "key"
      ? keyId.length > 0
      : credentialKind === "login"
        ? loginId.length > 0
        : password.length > 0;
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
      password: credentialKind === "password" ? password : null,
      is_password_saved: credentialKind === "password" && isPasswordSaved,
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
                <option value="key">{WORDING.storedKey}</option>
                <option value="login">{WORDING.storedLogin}</option>
                <option value="password">{WORDING.typedPassword}</option>
              </select>
              <span className="field_hint">{WORDING.credentialHint}</span>
            </label>
          </div>

          {credentialKind === "key" && (
            <label className="field">
              <span className="field_label">{WORDING.storedKey}</span>
              <select
                className="select"
                value={keyId}
                onChange={(event) => setKeyId(event.target.value)}
              >
                <option value="">{WORDING.pickKey}</option>
                {(keys.data?.keys ?? []).map((storedKey) => (
                  <option key={storedKey.id} value={storedKey.id}>
                    {keyLabel(storedKey)}
                  </option>
                ))}
              </select>
            </label>
          )}

          {credentialKind === "login" && (
            <label className="field">
              <span className="field_label">{WORDING.storedLogin}</span>
              <select
                className="select"
                value={loginId}
                onChange={(event) => setLoginId(event.target.value)}
              >
                <option value="">{WORDING.pickLogin}</option>
                {(logins.data?.logins ?? []).map((storedLogin) => (
                  <option key={storedLogin.id} value={storedLogin.id}>
                    {loginLabel(storedLogin)}
                  </option>
                ))}
              </select>
            </label>
          )}

          {credentialKind === "password" && (
            <>
              <label className="field">
                <span className="field_label">{WORDING.password}</span>
                <PasswordInput value={password} onChange={setPassword} />
              </label>
              <ToggleSwitch
                isOn={isPasswordSaved}
                onChange={setIsPasswordSaved}
                label={WORDING.savePassword}
                description={WORDING.savePasswordHint}
              />
            </>
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

/** The picker row for one login: its name, and its username where it has one. */
function loginLabel(login: LoginView): string {
  return login.username === null
    ? login.name
    : `${login.name} · ${login.username}`;
}

/** Enough of the fingerprint to tell two keys apart without filling the row. */
function keyLabel(key: KeyView): string {
  const body = key.fingerprint.replace(/^SHA256:/, "");
  const short = body.length > 12 ? `${body.slice(0, 12)}…` : body;
  return `${key.name} · ${short}`;
}
