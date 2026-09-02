import { useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import {
  ApiError,
  apiPostDownload,
  apiPut,
  apiUpload,
  describeError,
} from "../api_client";
import { formatDuration } from "../format_duration";
import { PasswordInput } from "../components/password_input";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
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
 * confirmation and says plainly that it overwrites what is there.
 */

const MIN_PASSWORD_LENGTH = 8;

const BACKUP_PASSPHRASE_NEEDED = "backup_passphrase_needed";
const BACKUP_PASSPHRASE_WRONG = "backup_passphrase_wrong";

const RESTORE_ERROR_SENTENCES: Record<string, string> = {
  [BACKUP_PASSPHRASE_NEEDED]:
    "This archive is protected. Enter its passphrase to restore it.",
  [BACKUP_PASSPHRASE_WRONG]: "That passphrase does not open this archive.",
};

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
  const confirm = useConfirm();
  const [backupNotice, setBackupNotice] = useState<string | null>(null);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupPassphrase, setBackupPassphrase] = useState("");
  const [restorePassphrase, setRestorePassphrase] = useState("");
  const [sealedFile, setSealedFile] = useState<File | null>(null);

  const isPasswordValid =
    currentPassword.length > 0 &&
    newPassword.length >= MIN_PASSWORD_LENGTH &&
    newPassword === confirmPassword;

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
      await apiPostDownload(
        "/settings/backup",
        { passphrase: backupPassphrase },
        backupFilename(),
      );
      setBackupNotice("Backup downloaded.");
    } catch (cause: unknown) {
      setBackupError(describeError(cause));
    } finally {
      setIsBackingUp(false);
    }
  };

  const handleRestoreFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file === undefined) {
      return;
    }
    setSealedFile(null);
    setRestorePassphrase("");
    confirm.ask({
      title: `Restore ${file.name}`,
      body:
        "Every file under config/ is overwritten by the archive's, and the " +
        "services are reconfigured from it.",
      confirmLabel: "Restore",
      onConfirm: () => void restoreFile(file, ""),
    });
  };

  const restoreFile = async (file: File, passphrase: string) => {
    setRestoreName(file.name);
    setIsRestoring(true);
    setBackupError(null);
    setBackupNotice(null);
    try {
      const result = await apiUpload<RestoreResult>("/settings/restore", file, {
        passphrase,
      });
      setSealedFile(null);
      setRestorePassphrase("");
      setBackupNotice(
        result.is_restored
          ? "Config restored. Re-render and restart services to apply it."
          : "The gateway rejected the archive.",
      );
    } catch (cause: unknown) {
      if (isSealedArchiveError(cause)) {
        setSealedFile(file);
      }
      setBackupError(describeRestoreError(cause));
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
            <label className="field">
              <span className="field_label">New password</span>
              <PasswordInput value={newPassword} onChange={setNewPassword} />
              <span className="field_hint">
                At least {MIN_PASSWORD_LENGTH} characters.
              </span>
            </label>
            <label className="field">
              <span className="field_label">Confirm new password</span>
              <PasswordInput
                value={confirmPassword}
                onChange={setConfirmPassword}
              />
              {confirmPassword.length > 0 &&
                confirmPassword !== newPassword && (
                  <span className="field_error">The two entries differ.</span>
                )}
            </label>

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
              Holds all of <span className="mono">config/</span>, credentials
              included. Keep it secret.
            </p>

            <label className="field">
              <span className="field_label">Backup passphrase</span>
              <PasswordInput
                value={backupPassphrase}
                onChange={setBackupPassphrase}
              />
              <span className="field_hint">
                Protects the download; blank keeps it plain.
              </span>
            </label>

            {sealedFile !== null && (
              <label className="field">
                <span className="field_label">Archive passphrase</span>
                <PasswordInput
                  value={restorePassphrase}
                  onChange={setRestorePassphrase}
                  autoFocus
                />
                <span className="field_hint">
                  The passphrase {sealedFile.name} was protected with.
                </span>
              </label>
            )}

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

            <div className="notice notice--warn">
              <Icon name="alert" size={15} />
              <div className="notice_body">
                Restoring overwrites the live config. Render and restart
                services afterwards for it to take effect.
              </div>
            </div>

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
              {sealedFile !== null && (
                <button
                  type="button"
                  className="button"
                  onClick={() =>
                    void restoreFile(sealedFile, restorePassphrase)
                  }
                  disabled={isRestoring || restorePassphrase.length === 0}
                >
                  <Icon name="check" size={14} />
                  Unlock and restore
                </button>
              )}
              {restoreName !== null && (
                <span className="settings_restore_name">{restoreName}</span>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".tar.gz,.tgz,application/gzip"
                className="settings_file_input"
                onChange={handleRestoreFile}
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
      {confirm.modal}
    </div>
  );
}

function backupFilename(): string {
  const stamp = new Date().toISOString().slice(0, 10);
  return `neutrino_config_${stamp}.tar.gz`;
}

function isSealedArchiveError(cause: unknown): boolean {
  return (
    cause instanceof ApiError &&
    (cause.code === BACKUP_PASSPHRASE_NEEDED ||
      cause.code === BACKUP_PASSPHRASE_WRONG)
  );
}

function describeRestoreError(cause: unknown): string {
  if (cause instanceof ApiError) {
    const sentence = RESTORE_ERROR_SENTENCES[cause.code];
    if (sentence !== undefined) {
      return sentence;
    }
  }
  return describeError(cause);
}
