import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { Spinner } from "../components/spinner";
import {
  ApiError,
  apiPostDownload,
  apiPut,
  apiUpload,
  describeError,
} from "../api_client";
import { formatDuration } from "../format_duration";
import { useTaskStream } from "../use_task_stream";
import { PasswordField } from "../components/password_field";
import { PasswordInput } from "../components/password_input";
import {
  PANEL_PASSWORD_HINT,
  PANEL_PASSWORD_RULES,
  isPasswordAccepted,
} from "../password_strength";
import { useApiResource } from "../use_api_resource";
import type {
  AboutInfo,
  PasswordChangeResult,
  RestoreResult,
} from "../api_types";

import "./settings_page.css";

/**
 * Panel password, config backup and restore, and version information.
 *
 * The backup is the whole of `config/`, which is the gateway's source of
 * truth, so restore is treated as the destructive operation it is: it asks for
 * confirmation and says plainly that it overwrites what is there. The vault
 * travels inside the archive sealed as it is stored, which is why the
 * download asks nothing and the restore asks for the vault master password.
 */

const NOT_A_BACKUP_SENTENCE = "This is not a Neutrino backup.";

const RESTORE_ERROR_SENTENCES: Record<string, string> = {
  vault_passphrase_needed: "The vault master password is required to restore.",
  vault_passphrase_wrong: "That is not this vault's master password.",
  backup_unrecognized: NOT_A_BACKUP_SENTENCE,
  backup_corrupt: "The backup is damaged; its checksum does not match.",
  backup_wrong_extension: "Backups are .tar.gz files.",
};

const WRONG_FILE_SENTENCE = "Backups are .tar.gz files; that file is not one.";

// Every backup is a tar.gz whose first member is its manifest, so a file that
// is no backup is turned away before it is uploaded by streaming just the
// head: a tar header is 512 bytes — name in the first 100, size in octal at
// 124.
const BACKUP_MANIFEST_MEMBER = "neutrino_backup.json";
const BACKUP_KIND = "neutrino_config_backup";

interface BackupManifest {
  kind?: string;
  version?: number;
}

function isBackupFilename(name: string): boolean {
  return /\.(tar\.gz|tgz)$/i.test(name);
}

function isManifestPeekSupported(): boolean {
  return typeof DecompressionStream !== "undefined";
}

async function readBackupManifest(file: File): Promise<BackupManifest | null> {
  try {
    const reader = file
      .stream()
      .pipeThrough(new DecompressionStream("gzip"))
      .getReader();
    let head = new Uint8Array(0);
    while (head.length < 4096) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      const grown = new Uint8Array(head.length + value.length);
      grown.set(head);
      grown.set(value, head.length);
      head = grown;
    }
    await reader.cancel();
    const text = new TextDecoder();
    const memberName = text.decode(head.slice(0, 100)).split("\0")[0];
    if (memberName !== BACKUP_MANIFEST_MEMBER) {
      return null;
    }
    const size = parseInt(text.decode(head.slice(124, 136)).trim(), 8);
    if (!Number.isFinite(size) || size <= 0 || 512 + size > head.length) {
      return null;
    }
    const parsed: unknown = JSON.parse(
      text.decode(head.slice(512, 512 + size)),
    );
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      (parsed as BackupManifest).kind !== BACKUP_KIND
    ) {
      return null;
    }
    return parsed as BackupManifest;
  } catch {
    return null;
  }
}

export function SettingsPage() {
  const about = useApiResource<AboutInfo>("/settings/about");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [passwordNotice, setPasswordNotice] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const [isBackingUp, setIsBackingUp] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreName, setRestoreName] = useState<string | null>(null);
  const [backupNotice, setBackupNotice] = useState<string | null>(null);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [restorePassphrase, setRestorePassphrase] = useState("");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreTaskId, setRestoreTaskId] = useState<string | null>(null);

  const isPasswordValid =
    currentPassword.length > 0 &&
    isPasswordAccepted(newPassword, confirmPassword, PANEL_PASSWORD_RULES);

  const handleChangePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (!isPasswordValid) {
      return;
    }
    setIsChangingPassword(true);
    setPasswordError(null);
    setPasswordNotice(null);
    try {
      const result = await apiPut<PasswordChangeResult>("/settings/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      if (!result.is_changed) {
        setPasswordError("The gateway refused the change.");
        return;
      }
      setPasswordNotice("Password changed. Other sessions stay signed in.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (cause: unknown) {
      setPasswordError(describeError(cause));
    } finally {
      setIsChangingPassword(false);
    }
  };

  const handleBackup = async () => {
    setIsBackingUp(true);
    setBackupError(null);
    setBackupNotice(null);
    try {
      await apiPostDownload("/settings/backup", undefined, backupFilename());
      setBackupNotice("Backup downloaded.");
    } catch (cause: unknown) {
      setBackupError(describeError(cause));
    } finally {
      setIsBackingUp(false);
    }
  };

  const handleRestoreFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file === undefined) {
      return;
    }
    if (!isBackupFilename(file.name)) {
      setBackupNotice(null);
      setBackupError(WRONG_FILE_SENTENCE);
      return;
    }
    if (isManifestPeekSupported()) {
      const manifest = await readBackupManifest(file);
      if (manifest === null) {
        setBackupNotice(null);
        setBackupError(NOT_A_BACKUP_SENTENCE);
        return;
      }
    }
    setRestorePassphrase("");
    setRestoreError(null);
    setRestoreFile(file);
  };

  const closeRestore = () => {
    setRestoreFile(null);
    setRestorePassphrase("");
    setRestoreError(null);
    setRestoreTaskId(null);
    setIsRestoring(false);
  };

  const restoreArchive = async () => {
    if (restoreFile === null) {
      return;
    }
    setRestoreName(restoreFile.name);
    setIsRestoring(true);
    setRestoreError(null);
    setBackupError(null);
    setBackupNotice(null);
    try {
      const result = await apiUpload<RestoreResult>(
        "/settings/restore",
        restoreFile,
        { vault_passphrase: restorePassphrase },
      );
      setRestoreTaskId(result.task_id);
    } catch (cause: unknown) {
      if (
        cause instanceof ApiError &&
        RESTORE_ERROR_SENTENCES[cause.code] !== undefined
      ) {
        setRestoreError(RESTORE_ERROR_SENTENCES[cause.code] ?? null);
      } else {
        setRestoreError(describeError(cause));
      }
    } finally {
      setIsRestoring(false);
    }
  };

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <h1>Settings</h1>
        </div>
      </div>

      <div className="settings_layout">
        <section className="card">
          <div className="card_header">
            <div className="card_title">
              <h2>Panel password</h2>
            </div>
            <Icon name="lock" size={15} />
          </div>

          <form
            className="settings_form"
            onSubmit={(event) => void handleChangePassword(event)}
          >
            <label className="field">
              <span className="field_label">Current password</span>
              <PasswordInput
                value={currentPassword}
                onChange={setCurrentPassword}
              />
            </label>
            <PasswordField
              label="New password"
              repeatLabel="Confirm new password"
              hint={PANEL_PASSWORD_HINT}
              value={newPassword}
              repeated={confirmPassword}
              rules={PANEL_PASSWORD_RULES}
              onChange={setNewPassword}
              onRepeatedChange={setConfirmPassword}
            />

            {passwordError !== null && (
              <div className="notice notice--error">
                <Icon name="alert" size={15} />
                <div className="notice_body">{passwordError}</div>
              </div>
            )}
            {passwordNotice !== null && (
              <div className="notice notice--ok">
                <Icon name="check" size={15} />
                <div className="notice_body">{passwordNotice}</div>
              </div>
            )}

            <div className="settings_actions">
              <button
                type="submit"
                className="button button--primary"
                disabled={isChangingPassword || !isPasswordValid}
              >
                <Icon name="check" size={14} />
                {isChangingPassword ? "Changing…" : "Change password"}
              </button>
            </div>
          </form>
        </section>

        <section className="card">
          <div className="card_header">
            <div className="card_title">
              <h2>Configuration archive</h2>
            </div>
            <Icon name="download" size={15} />
          </div>

          <div className="settings_form">
            <p className="muted">
              Holds all of <span className="mono">config/</span>. The
              credentials inside travel sealed under the vault master password,
              which restoring asks for.
            </p>

            {backupError !== null && (
              <div className="notice notice--error">
                <Icon name="alert" size={15} />
                <div className="notice_body">{backupError}</div>
              </div>
            )}
            {backupNotice !== null && (
              <div className="notice notice--ok">
                <Icon name="check" size={15} />
                <div className="notice_body">{backupNotice}</div>
              </div>
            )}

            <div className="settings_actions">
              <button
                type="button"
                className="button button--primary"
                onClick={() => void handleBackup()}
                disabled={isBackingUp}
              >
                <Icon name="download" size={14} />
                {isBackingUp ? "Preparing…" : "Download backup"}
              </button>
              <button
                type="button"
                className="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isRestoring}
              >
                <Icon name="upload" size={14} />
                {isRestoring ? "Restoring…" : "Restore from file"}
              </button>
              {restoreName !== null && (
                <span className="settings_restore_name">{restoreName}</span>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".tar.gz,.tgz,application/gzip"
                className="settings_file_input"
                onChange={(event) => void handleRestoreFile(event)}
              />
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card_header">
            <div className="card_title">
              <h2>About</h2>
            </div>
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={about.reload}
            >
              <Icon name="refresh" size={13} />
              Refresh
            </button>
          </div>

          {about.error !== null ? (
            <ErrorPanel
              title="Version info unavailable"
              message={about.error}
              onRetry={about.reload}
            />
          ) : about.data === null ? (
            <div className="skeleton" style={{ height: 150 }} />
          ) : (
            <div className="settings_about">
              <div className="settings_about_row">
                <span className="settings_about_key">Gateway</span>
                <span className="settings_about_value">
                  {about.data.gateway_version}
                </span>
              </div>
              <div className="settings_about_row">
                <span className="settings_about_key">xray</span>
                <span className="settings_about_value">
                  {about.data.xray_version}
                </span>
              </div>
              <div className="settings_about_row">
                <span className="settings_about_key">Kernel</span>
                <span className="settings_about_value">
                  {about.data.kernel}
                </span>
              </div>
              <div className="settings_about_row">
                <span className="settings_about_key">Uptime</span>
                <span className="settings_about_value">
                  {formatDuration(about.data.uptime_s)}
                </span>
              </div>
            </div>
          )}
        </section>
      </div>
      {restoreFile !== null && (
        <RestoreArchiveModal
          taskId={restoreTaskId}
          file={restoreFile}
          passphrase={restorePassphrase}
          onPassphrase={setRestorePassphrase}
          error={restoreError}
          isRestoring={isRestoring}
          onCancel={closeRestore}
          onRestore={() => void restoreArchive()}
        />
      )}
    </div>
  );
}

interface RestoreArchiveModalProps {
  file: File;
  taskId: string | null;
  passphrase: string;
  onPassphrase: (value: string) => void;
  error: string | null;
  isRestoring: boolean;
  onCancel: () => void;
  onRestore: () => void;
}

type RestorePhase = "ask" | "applying" | "failed" | "restarting";

const RESTORE_FAILED_APPLY =
  "The apply did not finish; the lines above say why. The files were " +
  "restored — fix the cause and run it again from a terminal: sudo nhub apply";
const RESTORE_FAILED_LOST =
  "The panel did not come back on its own. The files were restored; run " +
  "sudo nhub apply from a terminal, then reload this page.";

const RESTORE_PHASE_HINTS: Record<
  Exclude<RestorePhase, "ask" | "failed">,
  string
> = {
  applying:
    "Applying the restored configuration — this can take minutes when " +
    "heavy services re-render.",
  restarting:
    "The panel is restarting; this page reloads by itself. Sign in with " +
    "the restored password.",
};

function RestoreArchiveModal({
  file,
  taskId,
  passphrase,
  onPassphrase,
  error,
  isRestoring,
  onCancel,
  onRestore,
}: RestoreArchiveModalProps) {
  const task = useTaskStream(taskId);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isLostAfterApply, setIsLostAfterApply] = useState(false);
  const wasApplying = useRef(false);
  const logRef = useRef<HTMLPreElement | null>(null);

  const isApplyFailed = task.exitCode !== null && task.exitCode !== 0;
  const phase: RestorePhase =
    taskId === null
      ? "ask"
      : isApplyFailed || isLostAfterApply
        ? "failed"
        : isReconnecting
          ? "restarting"
          : "applying";
  const isDismissable = phase === "ask" && !isRestoring;

  useEffect(() => {
    const element = logRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [task.lines]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isDismissable) {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, isDismissable]);

  useEffect(() => {
    if (task.isRunning) {
      wasApplying.current = true;
      return;
    }
    if (!wasApplying.current) {
      return;
    }
    wasApplying.current = false;
    if (task.exitCode !== null && task.exitCode !== 0) {
      return;
    }
    // The task can also end by losing its socket to the restart itself, so
    // any end that is not a reported failure means the restart is under way.
    // The app-wide identity watch reloads the page when the new panel
    // answers; ninety silent seconds mean it never came.
    setIsReconnecting(true);
    const handle = window.setTimeout(() => setIsLostAfterApply(true), 90_000);
    return () => window.clearTimeout(handle);
  }, [task.isRunning, task.exitCode]);

  return (
    <div
      className="confirm_backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`Restore ${file.name}`}
      onClick={(event) => {
        if (event.target === event.currentTarget && isDismissable) {
          onCancel();
        }
      }}
    >
      <div className="confirm_modal">
        <div className="confirm_head">
          <Icon name="upload" size={16} />
          <h2>Restore {file.name}</h2>
        </div>
        <p className="confirm_body">
          Every file under config/ is overwritten by the archive&apos;s, the
          configuration is applied, and the panel restarts on its own.
        </p>

        {phase === "ask" && (
          <>
            <div className="settings_restore_fields">
              <label className="field">
                <span className="field_label">Vault master password</span>
                <PasswordInput
                  value={passphrase}
                  onChange={onPassphrase}
                  autoFocus
                />
                <span className="field_hint">
                  The master password of the vault this backup was taken from.
                </span>
              </label>
              {error !== null && (
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">{error}</div>
                </div>
              )}
            </div>
            <div className="confirm_foot">
              <button
                type="button"
                className="button"
                onClick={onCancel}
                disabled={isRestoring}
              >
                Cancel
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={onRestore}
                disabled={isRestoring || passphrase.length === 0}
              >
                {isRestoring ? "Restoring…" : "Restore"}
              </button>
            </div>
          </>
        )}

        {phase !== "ask" && (
          <div className="settings_restore_fields">
            {task.lines.length > 0 && (
              <pre
                className="device_drawer_log_output settings_restore_log"
                ref={logRef}
              >
                {task.lines.join("\n")}
              </pre>
            )}
            {phase === "failed" ? (
              <>
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {isApplyFailed ? RESTORE_FAILED_APPLY : RESTORE_FAILED_LOST}
                  </div>
                </div>
                <div className="confirm_foot">
                  <button type="button" className="button" onClick={onCancel}>
                    Close
                  </button>
                </div>
              </>
            ) : (
              <Spinner size={18} label={RESTORE_PHASE_HINTS[phase]} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function backupFilename(): string {
  const stamp = new Date().toISOString().slice(0, 10);
  return `neutrino_config_${stamp}.tar.gz`;
}
