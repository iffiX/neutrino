import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { StatusDot } from "./status_dot";
import { VaultPicker } from "./vault_picker";
import { ApiError, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
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
 * stored here where it is not stored yet. The login whose password sudo is
 * given on the device comes from the same vault; nothing echoes a secret into
 * the output below.
 */

// The {code, params} an install is refused with, worded.
const INSTALL_ERROR_KEYS: Record<string, string> = {
  agent_offline: "ui.devices.agent_offline",
  unknown_credential: "code.unknown_credential",
  agent_package_missing: "code.agent_package_missing",
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
  const [sudoLoginId, setSudoLoginId] = useState<string | null>(null);
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
      sudo_login_id: sudoLoginId,
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
              {isReinstall
                ? t("ui.install_agent.reinstall_title", { device: deviceName })
                : t("ui.install_agent.install_title", { device: deviceName })}
            </h2>
          </div>
          <button
            type="button"
            className="button button--small"
            onClick={onClose}
          >
            <Icon name="close" size={13} />
            {t("ui.install_agent.close")}
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
              <span className="field_label">{t("ui.install_agent.host")}</span>
              <input
                className="input"
                value={host}
                onChange={(event) => setHost(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field_label">{t("ui.install_agent.port")}</span>
              <input
                className={`input ${isPortValid ? "" : "input--invalid"}`}
                value={port}
                inputMode="numeric"
                onChange={(event) => setPort(event.target.value)}
              />
              {!isPortValid && (
                <span className="field_error">
                  {t("ui.install_agent.port_invalid")}
                </span>
              )}
            </label>
            <label className="field">
              <span className="field_label">
                {t("ui.install_agent.username")}
              </span>
              <input
                className="input"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field_label">
                {t("ui.install_agent.credential")}
              </span>
              <select
                className="select"
                value={credentialKind}
                onChange={(event) =>
                  setCredentialKind(event.target.value as CredentialKind)
                }
              >
                <option value="key">{t("ui.install_agent.kind_key")}</option>
                <option value="login">
                  {t("ui.install_agent.kind_login")}
                </option>
              </select>
              <span className="field_hint">
                {t("ui.install_agent.credential_hint")}
              </span>
            </label>
          </div>

          {credentialKind === "key" ? (
            <VaultPicker
              kind="ssh_key"
              value={keyId}
              onChange={setKeyId}
              label={t("ui.install_agent.key")}
              hint={t("ui.install_agent.key_hint")}
            />
          ) : (
            <VaultPicker
              kind="login"
              value={loginId}
              onChange={setLoginId}
              label={t("ui.install_agent.login")}
              hint={t("ui.install_agent.login_hint")}
            />
          )}

          <VaultPicker
            kind="login"
            value={sudoLoginId}
            onChange={setSudoLoginId}
            label={t("ui.install_agent.sudo_password")}
            hint={t("ui.install_agent.sudo_hint")}
          />

          {taskId !== null && (
            <div className="install_modal_log">
              <div className="install_modal_log_head">
                <span className="section_label">
                  {t("ui.install_agent.output")}
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
                  isPulsing={task.isRunning}
                  label={
                    task.isRunning
                      ? t("ui.install_agent.running_label")
                      : t("ui.install_agent.done_label", {
                          code: task.exitCode ?? "",
                        })
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
              ? t("ui.install_agent.running")
              : isReinstall
                ? t("ui.install_agent.submit_reinstall")
                : t("ui.install_agent.submit")}
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
      return os.length === 0
        ? t("ui.install_agent.unsupported_remote_install_unknown")
        : t("code.unsupported_remote_install", { os });
    }
    const key = INSTALL_ERROR_KEYS[cause.code];
    if (key !== undefined) {
      return t(key);
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
