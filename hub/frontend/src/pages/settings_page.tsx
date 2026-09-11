import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, ReactNode } from "react";

import { ApplyBar } from "../components/apply_bar";
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
import {
  LANGUAGES,
  LANGUAGE_NAMES,
  asLanguage,
  setLanguage,
  t,
  useLanguage,
} from "../i18n";
import { useApiResource } from "../use_api_resource";
import { stripAnsi } from "../strip_ansi";
import { useTaskStream } from "../use_task_stream";
import { PasswordField } from "../components/password_field";
import { PasswordInput } from "../components/password_input";
import {
  panelPasswordHint,
  PANEL_PASSWORD_RULES,
  isPasswordAccepted,
} from "../password_strength";
import { usePolledResource } from "../use_polled_resource";
import type {
  AboutInfo,
  PanelSettings,
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

// The components this hub carries are named by their projects, so these rows
// keep their names in every language.
const ABOUT_XRAY = "xray";
const ABOUT_CLIPROXYAPI = "CLIProxyAPI";
const ABOUT_PYTHON = "Python";

/** What the API answers when it is asked for a language nobody ships. */
const LANGUAGE_UNKNOWN_CODE = "language_unknown";

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
  // Redrawn when the panel's language changes.
  useLanguage();
  const about = usePolledResource<AboutInfo>("/settings/about");
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
        setPasswordError(t("ui.settings.password_refused"));
        return;
      }
      setPasswordNotice(t("ui.settings.password_changed"));
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
      setBackupNotice(t("ui.settings.backup_downloaded"));
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
      setBackupError(t("ui.settings.wrong_file"));
      return;
    }
    if (isManifestPeekSupported()) {
      const manifest = await readBackupManifest(file);
      if (manifest === null) {
        setBackupNotice(null);
        setBackupError(t("ui.settings.not_a_backup"));
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
      setRestoreError(describeError(cause));
    } finally {
      setIsRestoring(false);
    }
  };

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <h1>{t("ui.settings.title")}</h1>
        </div>
      </div>

      <div className="settings_layout">
        <section className="card">
          <div className="card_header">
            <div className="card_title">
              <h2>{t("ui.settings.about_title")}</h2>
            </div>
          </div>

          {about.error !== null ? (
            <ErrorPanel
              title={t("ui.settings.about_unavailable")}
              message={about.error}
              onRetry={about.reload}
            />
          ) : about.data === null ? (
            <div className="skeleton" style={{ height: 250 }} />
          ) : (
            <div className="settings_about">
              <div className="section_label">
                {t("ui.settings.about_carried")}
              </div>
              <AboutRow
                label={t("ui.settings.about_panel")}
                value={about.data.gateway_version}
              />
              <AboutRow label={ABOUT_XRAY} value={about.data.xray_version} />
              <AboutRow
                label={ABOUT_CLIPROXYAPI}
                value={about.data.cliproxyapi_version}
              />
              <AboutRow
                label={ABOUT_PYTHON}
                value={about.data.python_version}
              />
              <AboutRow
                label={t("ui.settings.about_geodata")}
                value={about.data.geodata_version}
              />
              <div className="section_label">{t("ui.settings.about_host")}</div>
              <AboutRow
                label={t("ui.settings.about_kernel")}
                value={about.data.kernel}
              />
              <AboutRow
                label={t("ui.settings.about_uptime")}
                value={formatDuration(about.data.uptime_s)}
              />
              {about.data.acknowledgements.length > 0 && (
                <>
                  <div className="section_label">
                    {t("ui.settings.about_credits")}
                  </div>
                  <span className="field_hint">
                    {t("ui.settings.about_credits_hint")}
                  </span>
                  {about.data.acknowledgements.map((credit) => (
                    <AboutRow
                      key={credit.name}
                      label={
                        credit.version === ""
                          ? credit.name
                          : `${credit.name} ${credit.version}`
                      }
                      value={
                        credit.corresponding_source === "" ? (
                          credit.license
                        ) : (
                          <>
                            {`${credit.license} — `}
                            <a
                              href={credit.corresponding_source}
                              target="_blank"
                              rel="noreferrer noopener"
                            >
                              {t("ui.settings.about_credits_source")}
                            </a>
                          </>
                        )
                      }
                    />
                  ))}
                </>
              )}
            </div>
          )}
        </section>

        <LanguagePanel />

        <section className="card">
          <div className="card_header">
            <div className="card_title">
              <h2>{t("ui.settings.password_title")}</h2>
            </div>
            <Icon name="lock" size={15} />
          </div>

          <form
            className="settings_form"
            onSubmit={(event) => void handleChangePassword(event)}
          >
            <label className="field">
              <span className="field_label">
                {t("ui.settings.current_password")}
              </span>
              <PasswordInput
                value={currentPassword}
                onChange={setCurrentPassword}
              />
            </label>
            <PasswordField
              label={t("ui.settings.new_password")}
              repeatLabel={t("ui.settings.confirm_password")}
              hint={panelPasswordHint}
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
                {isChangingPassword
                  ? t("ui.settings.changing")
                  : t("ui.settings.change_password")}
              </button>
            </div>
          </form>
        </section>

        <section className="card">
          <div className="card_header">
            <div className="card_title">
              <h2>{t("ui.settings.backup_title")}</h2>
            </div>
            <Icon name="download" size={15} />
          </div>

          <div className="settings_form">
            <p className="muted">{t("ui.settings.backup_hint")}</p>

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
                {isBackingUp
                  ? t("ui.settings.preparing")
                  : t("ui.settings.download_backup")}
              </button>
              <button
                type="button"
                className="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isRestoring}
              >
                <Icon name="upload" size={14} />
                {isRestoring
                  ? t("ui.settings.restoring")
                  : t("ui.settings.restore_from_file")}
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

/**
 * The language every page is drawn in.
 *
 * One panel-wide answer, stored on the box rather than in this browser, so
 * the terminal and the panel agree on what somebody chose at first run. The
 * apply writes it and the page re-words itself where it stands.
 */
function LanguagePanel() {
  const current = useLanguage();
  const resource = useApiResource<PanelSettings>("/settings");
  const [chosen, setChosen] = useState(current);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applied = resource.data?.language ?? null;
  const isDirty = applied !== null && chosen !== applied;

  const apply = async () => {
    if (resource.data === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const saved = await apiPut<PanelSettings>("/settings", {
        listen_port: resource.data.listen_port,
        language: chosen,
      });
      resource.setData(saved);
      setLanguage(saved.language);
    } catch (cause: unknown) {
      setError(
        cause instanceof ApiError && cause.code === LANGUAGE_UNKNOWN_CODE
          ? t("code.language_unknown")
          : describeError(cause),
      );
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section className={`card ${isDirty ? "card--dirty" : ""}`}>
      <div className="card_header">
        <div className="card_title">
          <h2>{t("ui.settings.language_title")}</h2>
        </div>
      </div>

      <div className="settings_form">
        <label className="field">
          <span className="field_label">{t("ui.settings.language_field")}</span>
          <select
            className="select"
            value={chosen}
            onChange={(event) => {
              setError(null);
              setChosen(asLanguage(event.target.value));
            }}
          >
            {LANGUAGES.map((language) => (
              <option key={language} value={language}>
                {LANGUAGE_NAMES[language]}
              </option>
            ))}
          </select>
          <span className="field_hint">{t("ui.settings.language_hint")}</span>
        </label>

        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy}
          label={t("ui.settings.language_apply")}
          hint={t("ui.settings.language_apply_hint")}
          error={error}
          onReset={() => setChosen(asLanguage(applied ?? current))}
          onApply={() => void apply()}
        />
      </div>
    </section>
  );
}

interface AboutRowProps {
  label: string;
  value: ReactNode;
}

/** One name and its version, the full value on hover where it is cut. */
function AboutRow({ label, value }: AboutRowProps) {
  return (
    <div className="settings_about_row">
      <span className="settings_about_key">{label}</span>
      <span
        className="settings_about_value"
        title={typeof value === "string" ? value : undefined}
      >
        {value}
      </span>
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

const RESTORE_PHASE_HINT_KEYS: Record<
  Exclude<RestorePhase, "ask" | "failed">,
  string
> = {
  applying: "ui.settings.restore_applying",
  restarting: "ui.settings.restore_restarting",
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
      aria-label={t("ui.settings.restore_title", { name: file.name })}
      onClick={(event) => {
        if (event.target === event.currentTarget && isDismissable) {
          onCancel();
        }
      }}
    >
      <div className="confirm_modal">
        <div className="confirm_head">
          <Icon name="upload" size={16} />
          <h2>{t("ui.settings.restore_title", { name: file.name })}</h2>
        </div>
        <p className="confirm_body">{t("ui.settings.restore_body")}</p>

        {phase === "ask" && (
          <>
            <div className="settings_restore_fields">
              <label className="field">
                <span className="field_label">
                  {t("ui.settings.vault_password")}
                </span>
                <PasswordInput
                  value={passphrase}
                  onChange={onPassphrase}
                  autoFocus
                />
                <span className="field_hint">
                  {t("ui.settings.vault_password_hint")}
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
                {t("ui.settings.cancel")}
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={onRestore}
                disabled={isRestoring || passphrase.length === 0}
              >
                {isRestoring
                  ? t("ui.settings.restoring")
                  : t("ui.settings.restore")}
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
                {stripAnsi(task.lines.join("\n"))}
              </pre>
            )}
            {phase === "failed" ? (
              <>
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {isApplyFailed
                      ? t("ui.settings.restore_failed_apply")
                      : t("ui.settings.restore_failed_lost")}
                  </div>
                </div>
                <div className="confirm_foot">
                  <button type="button" className="button" onClick={onCancel}>
                    {t("ui.settings.close")}
                  </button>
                </div>
              </>
            ) : (
              <Spinner size={18} label={t(RESTORE_PHASE_HINT_KEYS[phase])} />
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
