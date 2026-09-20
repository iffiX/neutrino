import { useEffect, useRef, useState } from "react";

import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { StatusDot } from "./status_dot";
import { apiPost, describeError } from "../api_client";
import { formatBytes } from "../format_bytes";
import { t, useLanguage } from "../i18n";
import { stripAnsi } from "../strip_ansi";
import { usePageMemory } from "../use_page_memory";
import {
  DEFAULT_POLL_INTERVAL_MS,
  usePolledResource,
} from "../use_polled_resource";
import { useTaskStream } from "../use_task_stream";
import type {
  HubReleaseScanView,
  HubReleaseView,
  HubUpdateRecord,
  HubUpdateRequest,
  TaskStarted,
} from "../api_types";

import "./update_panel.css";

/**
 * Updating the hub itself, from the newest release published.
 *
 * Nothing is asked of GitHub until the button is pressed. What a check
 * found is kept for the visit, so the page can be left and come back to
 * without checking again. An install is confirmed in a modal that then
 * follows the staging task; the install itself runs in a unit of its own
 * and restarts the panel, at which point the app-wide identity watch
 * reloads this page. The record of what became of it is read from the
 * backend once the panel is back, and shown until the next update.
 */

/** How often the record is read while an update is under way. */
const INFLIGHT_POLL_INTERVAL_MS = 3000;
/** How long the restart is waited for before the modal says it is taking long. */
const RESTART_PATIENCE_MS = 90_000;
/** The install and a rollback each hold a gate of three minutes. */
const RESTART_LOST_MS = 8 * 60_000;

const STAGES_IN_FLIGHT = new Set(["preparing", "installing", "rolling_back"]);

type ModalPhase = "ask" | "preparing" | "restarting" | "failed";

export function UpdatePanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [scan, setScan] = usePageMemory<HubReleaseScanView | null>(
    "settings.release",
    null,
  );
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [pollIntervalMs, setPollIntervalMs] = useState(
    DEFAULT_POLL_INTERVAL_MS,
  );
  const release = usePolledResource<HubReleaseView>(
    "/hub/setting/release",
    pollIntervalMs,
  );
  const record = release.data?.update ?? null;

  // An update under way is watched closely; the rest of the time the record
  // only changes when somebody presses Install.
  useEffect(() => {
    const isInFlight = record !== null && STAGES_IN_FLIGHT.has(record.stage);
    setPollIntervalMs(
      isInFlight ? INFLIGHT_POLL_INTERVAL_MS : DEFAULT_POLL_INTERVAL_MS,
    );
  }, [record]);

  // A page opened while the staging runs follows it from where it is.
  useEffect(() => {
    if (release.data?.task_id && taskId === null) {
      setTaskId(release.data.task_id);
      setIsModalOpen(true);
    }
  }, [release.data?.task_id, taskId]);

  const check = async () => {
    setScanError(null);
    setIsScanning(true);
    try {
      setScan(await apiPost<HubReleaseScanView>("/hub/setting/release/scan"));
    } catch (cause: unknown) {
      setScanError(describeError(cause));
    } finally {
      setIsScanning(false);
    }
  };

  const view = release.data;
  const latest = scan?.latest ?? null;
  const isInstallable =
    scan !== null &&
    latest !== null &&
    scan.is_newer &&
    !scan.is_major &&
    scan.is_space_enough;
  // What the modal is about: the release just checked, or, on a page opened
  // while a staging runs, the versions its record names.
  const target: UpdateTarget | null =
    scan !== null && latest !== null
      ? {
          from: scan.current,
          version: latest.version,
          isRollbackAvailable: scan.is_rollback_available,
        }
      : record !== null && record.stage === "preparing"
        ? {
            from: record.from_version,
            version: record.to_version,
            isRollbackAvailable: true,
          }
        : null;

  return (
    <section className="card">
      <div className="card_header">
        <div className="card_title">
          <h2>{t("ui.settings.update_title")}</h2>
        </div>
        {record !== null && STAGES_IN_FLIGHT.has(record.stage) && (
          <span className="badge badge--warn">
            <StatusDot tone="warn" isPulsing />
            {record.stage === "rolling_back"
              ? t("ui.settings.update_rolling_back", {
                  from: record.from_version,
                })
              : t("ui.settings.update_installing")}
          </span>
        )}
      </div>

      {view === null ? (
        <div className="skeleton" style={{ height: 80 }} />
      ) : (
        <div className="update">
          <div className="update_current">
            <span className="update_current_key">
              {t("ui.settings.update_current")}
            </span>
            <span className="mono">{view.current}</span>
          </div>

          {record !== null && !STAGES_IN_FLIGHT.has(record.stage) && (
            <RecordNotice record={record} />
          )}

          {!view.is_packaged ? (
            <span className="field_hint">
              {t("ui.settings.update_checkout")}
            </span>
          ) : (
            <>
              <div className="update_actions">
                <button
                  type="button"
                  className="button"
                  onClick={() => void check()}
                  disabled={isScanning || isModalOpen}
                >
                  {isScanning ? (
                    <Spinner size={14} />
                  ) : (
                    <Icon name="refresh" size={14} />
                  )}
                  {isScanning
                    ? t("ui.settings.update_checking")
                    : t("ui.settings.update_check")}
                </button>
                {isInstallable && (
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={() => setIsModalOpen(true)}
                    disabled={isModalOpen}
                  >
                    <Icon name="download" size={14} />
                    {t("ui.settings.update_install", {
                      version: latest.version,
                    })}
                  </button>
                )}
              </div>
              {scanError !== null && (
                <span className="field_error">{scanError}</span>
              )}
              {scan !== null && <ScanResult scan={scan} />}
            </>
          )}
        </div>
      )}

      {isModalOpen && target !== null && (
        <UpdateModal
          target={target}
          taskId={taskId}
          onStarted={setTaskId}
          onClose={() => {
            setIsModalOpen(false);
            setTaskId(null);
            release.reload();
          }}
        />
      )}
    </section>
  );
}

interface ScanResultProps {
  scan: HubReleaseScanView;
}

function ScanResult({ scan }: ScanResultProps) {
  const latest = scan.latest;
  if (latest === null) {
    return (
      <span className="field_hint">
        {t("ui.settings.update_none_published")}
      </span>
    );
  }
  if (!scan.is_newer) {
    return (
      <span className="field_hint">
        {t("ui.settings.update_on_newest", { version: latest.version })}
      </span>
    );
  }
  return (
    <div className="update_found">
      <div className="update_found_line">
        <span className="mono">{latest.version}</span>
        <span className="faint">{latest.published_at.slice(0, 10)}</span>
        <span className="faint">{formatBytes(latest.size_bytes)}</span>
        <span className="faint">
          {t("ui.settings.update_room", {
            needed: formatBytes(scan.needed_bytes),
            free: formatBytes(scan.free_bytes),
          })}
        </span>
        {latest.page_url !== "" && (
          <a href={latest.page_url} target="_blank" rel="noreferrer noopener">
            {t("ui.settings.update_release_page")}
          </a>
        )}
      </div>
      {scan.is_major && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {t("ui.settings.update_major", { version: latest.version })}
          </div>
        </div>
      )}
      {!scan.is_space_enough && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {t("ui.settings.update_room_short", {
              needed: formatBytes(scan.needed_bytes),
              free: formatBytes(scan.free_bytes),
            })}
          </div>
        </div>
      )}
      {latest.notes.trim() !== "" && (
        <>
          <span className="field_hint">{t("ui.settings.update_notes")}</span>
          <pre className="update_notes">{latest.notes.trim()}</pre>
        </>
      )}
    </div>
  );
}

interface RecordNoticeProps {
  record: HubUpdateRecord;
}

function RecordNotice({ record }: RecordNoticeProps) {
  const reason =
    record.reason === "" ? "" : t(`ui.settings.update_reason.${record.reason}`);
  const values = {
    from: record.from_version,
    to: record.to_version,
    date: (record.finished_at || record.started_at).slice(0, 10),
    reason,
  };
  const tone =
    record.stage === "installed"
      ? "notice--ok"
      : record.stage === "rolled_back"
        ? "notice--warn"
        : "notice--error";
  const key =
    record.stage === "installed"
      ? "ui.settings.update_result_installed"
      : record.stage === "rolled_back"
        ? "ui.settings.update_result_rolled_back"
        : "ui.settings.update_result_failed";
  return (
    <div className="update_record">
      <div className={`notice ${tone}`}>
        <Icon
          name={record.stage === "installed" ? "check" : "alert"}
          size={15}
        />
        <div className="notice_body">{t(key, values)}</div>
      </div>
      {record.output.trim() !== "" && (
        <details className="update_output">
          <summary>{t("ui.settings.update_output")}</summary>
          <pre className="device_drawer_log_output update_log">
            {stripAnsi(record.output)}
          </pre>
        </details>
      )}
    </div>
  );
}

interface UpdateTarget {
  from: string;
  version: string;
  isRollbackAvailable: boolean;
}

interface UpdateModalProps {
  target: UpdateTarget;
  taskId: string | null;
  onStarted: (taskId: string) => void;
  onClose: () => void;
}

function UpdateModal({ target, taskId, onStarted, onClose }: UpdateModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const task = useTaskStream(taskId);
  const [isStarting, setIsStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [isRestarting, setIsRestarting] = useState(false);
  const [isTakingLong, setIsTakingLong] = useState(false);
  const [isLost, setIsLost] = useState(false);
  const wasRunning = useRef(false);
  const logRef = useRef<HTMLPreElement | null>(null);

  const isStagingFailed = task.exitCode !== null && task.exitCode !== 0;
  const phase: ModalPhase =
    taskId === null
      ? "ask"
      : isStagingFailed || isLost
        ? "failed"
        : isRestarting
          ? "restarting"
          : "preparing";
  const isDismissable = phase === "ask" || phase === "failed";

  useEffect(() => {
    const element = logRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [task.lines]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isDismissable && !isStarting) {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, isDismissable, isStarting]);

  useEffect(() => {
    if (task.isRunning) {
      wasRunning.current = true;
      return;
    }
    if (!wasRunning.current) {
      return;
    }
    wasRunning.current = false;
    if (task.exitCode !== null && task.exitCode !== 0) {
      return;
    }
    // The task ends when the staging hands over, or when the restart takes
    // its socket; either way the panel is on its way down. The identity
    // watch reloads the page when the new one answers.
    setIsRestarting(true);
    const patience = window.setTimeout(
      () => setIsTakingLong(true),
      RESTART_PATIENCE_MS,
    );
    const lost = window.setTimeout(() => setIsLost(true), RESTART_LOST_MS);
    return () => {
      window.clearTimeout(patience);
      window.clearTimeout(lost);
    };
  }, [task.isRunning, task.exitCode]);

  const start = async () => {
    setStartError(null);
    setIsStarting(true);
    try {
      const request: HubUpdateRequest = { version: target.version };
      const started = await apiPost<TaskStarted>(
        "/hub/setting/release/install",
        request,
      );
      onStarted(started.task_id);
    } catch (cause: unknown) {
      setStartError(describeError(cause));
    } finally {
      setIsStarting(false);
    }
  };

  const version = target.version;
  return (
    <div
      className="confirm_backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={t("ui.settings.update_confirm_title", { version })}
      onClick={(event) => {
        if (
          event.target === event.currentTarget &&
          isDismissable &&
          !isStarting
        ) {
          onClose();
        }
      }}
    >
      <div className="confirm_modal">
        <div className="confirm_head">
          <Icon name="download" size={16} />
          <h2>{t("ui.settings.update_confirm_title", { version })}</h2>
        </div>

        {phase === "ask" && (
          <>
            <p className="confirm_body">
              {t("ui.settings.update_confirm_body", {
                from: target.from,
                version,
              })}
            </p>
            {!target.isRollbackAvailable && (
              <div className="update_modal_fields">
                <div className="notice notice--warn">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {t("ui.settings.update_confirm_no_rollback", {
                      from: target.from,
                      version,
                    })}
                  </div>
                </div>
              </div>
            )}
            {startError !== null && (
              <div className="update_modal_fields">
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">{startError}</div>
                </div>
              </div>
            )}
            <div className="confirm_foot">
              <button
                type="button"
                className="button"
                onClick={onClose}
                disabled={isStarting}
              >
                {t("ui.settings.cancel")}
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void start()}
                disabled={isStarting}
              >
                {isStarting ? (
                  <Spinner size={14} />
                ) : (
                  <Icon name="download" size={14} />
                )}
                {t("ui.settings.update_install_short")}
              </button>
            </div>
          </>
        )}

        {phase !== "ask" && (
          <div className="update_modal_fields">
            {task.lines.length > 0 && (
              <pre className="device_drawer_log_output update_log" ref={logRef}>
                {stripAnsi(task.lines.join("\n"))}
              </pre>
            )}
            {phase === "failed" ? (
              <>
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {isLost
                      ? t("ui.settings.update_lost")
                      : t("ui.settings.update_failed")}
                  </div>
                </div>
                <div className="confirm_foot">
                  <button type="button" className="button" onClick={onClose}>
                    {t("ui.settings.close")}
                  </button>
                </div>
              </>
            ) : phase === "restarting" ? (
              <>
                <Spinner size={18} label={t("ui.settings.update_restarting")} />
                {isTakingLong && (
                  <span className="field_hint">
                    {t("ui.settings.update_restarting_long")}
                  </span>
                )}
              </>
            ) : (
              <Spinner size={18} label={t("ui.settings.update_preparing")} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
