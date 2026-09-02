import { useEffect, useRef, useState } from "react";
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

const RESTORE_WRONG_PASSPHRASE = "That passphrase does not open this archive.";

// A sealed backup announces itself in its first bytes, so which modal to
// show is settled before anything is uploaded.
const SEALED_MAGIC = "NEUTRINO-SEALED-1\n";

async function isSealedArchive(file: File): Promise<boolean> {
  try {
    const head = await file.slice(0, SEALED_MAGIC.length).arrayBuffer();
    return new TextDecoder().decode(new Uint8Array(head)) === SEALED_MAGIC;
  } catch {
    return false;
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
  const [backupPassphrase, setBackupPassphrase] = useState("");
  const [restorePassphrase, setRestorePassphrase] = useState("");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [isArchiveProtected, setIsArchiveProtected] = useState(false);

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
        backupFilename(backupPassphrase.length > 0),
      );
      setBackupNotice("Backup downloaded.");
      setBackupPassphrase("");
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
    const isProtected = await isSealedArchive(file);
    setRestorePassphrase("");
    setRestoreError(null);
    setIsArchiveProtected(isProtected);
    setRestoreFile(file);
  };

  const closeRestore = () => {
    setRestoreFile(null);
    setRestorePassphrase("");
    setRestoreError(null);
    setIsArchiveProtected(false);
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
        { passphrase: restorePassphrase },
      );
      closeRestore();
      setBackupNotice(
        result.is_restored
          ? "Config restored. Re-render and restart services to apply it."
          : "The gateway rejected the archive.",
      );
    } catch (cause: unknown) {
      if (
        cause instanceof ApiError &&
        cause.code === BACKUP_PASSPHRASE_NEEDED
      ) {
        setIsArchiveProtected(true);
      } else if (
        cause instanceof ApiError &&
        cause.code === BACKUP_PASSPHRASE_WRONG
      ) {
        setIsArchiveProtected(true);
        setRestoreError(RESTORE_WRONG_PASSPHRASE);
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
                accept=".tar.gz,.tgz,.sealed,application/gzip"
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
          file={restoreFile}
          passphrase={restorePassphrase}
          onPassphrase={setRestorePassphrase}
          error={restoreError}
          isProtected={isArchiveProtected}
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
  passphrase: string;
  onPassphrase: (value: string) => void;
  error: string | null;
  isProtected: boolean;
  isRestoring: boolean;
  onCancel: () => void;
  onRestore: () => void;
}

function RestoreArchiveModal({
  file,
  passphrase,
  onPassphrase,
  error,
  isProtected,
  isRestoring,
  onCancel,
  onRestore,
}: RestoreArchiveModalProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isRestoring) {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, isRestoring]);

  return (
    <div
      className="confirm_backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`Restore ${file.name}`}
      onClick={(event) => {
        if (event.target === event.currentTarget && !isRestoring) {
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
          Every file under config/ is overwritten by the archive&apos;s. Render
          and restart services afterwards for it to take effect.
        </p>
        {(isProtected || error !== null) && (
          <div className="settings_restore_fields">
            {isProtected && (
              <label className="field">
                <span className="field_label">Archive passphrase</span>
                <PasswordInput
                  value={passphrase}
                  onChange={onPassphrase}
                  autoFocus
                />
                <span className="field_hint">
                  The passphrase this archive was sealed under.
                </span>
              </label>
            )}
            {error !== null && (
              <div className="notice notice--error">
                <Icon name="alert" size={15} />
                <div className="notice_body">{error}</div>
              </div>
            )}
          </div>
        )}
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
            disabled={isRestoring || (isProtected && passphrase.length === 0)}
          >
            {isRestoring ? "Restoring…" : "Restore"}
          </button>
        </div>
      </div>
    </div>
  );
}

function backupFilename(isSealed: boolean): string {
  const stamp = new Date().toISOString().slice(0, 10);
  return `neutrino_config_${stamp}.${isSealed ? "sealed" : "tar.gz"}`;
}
