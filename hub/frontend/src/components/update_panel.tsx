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
import { openUpdateDialog, useUpdateDialog } from "../use_update_dialog";
import type {
  HubPackageFamily,
  HubReleaseScanView,
  HubReleaseView,
  HubUpdateRecord,
} from "../api_types";

import "./update_panel.css";

/**
 * Updating the hub itself, from the newest release published.
 *
 * Nothing is asked of GitHub until the button is pressed. What a check
 * found is kept for the visit, so the page can be left and come back to
 * without checking again. An install is confirmed in the update dialog,
 * which follows the update through the panel's restart to its end. The
 * record of what became of it is read from the backend, and shown until the
 * next update.
 */

/** How often the record is read while an update is under way. */
const INFLIGHT_POLL_INTERVAL_MS = 3000;

const STAGES_IN_FLIGHT = new Set(["preparing", "installing", "rolling_back"]);

/** The families the system's own installer installs; the others are
 * installed by the package manager under systemd. */
const INSTALLER_FAMILIES: ReadonlySet<HubPackageFamily> = new Set([
  "msi",
  "pkg",
]);

/** The reasons worded apart for a family the system's installer installs. */
const INSTALLER_WORDED_REASONS = new Set([
  "package_install_failed",
  "update_launch_failed",
]);

export function UpdatePanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [scan, setScan] = usePageMemory<HubReleaseScanView | null>(
    "settings.release",
    null,
  );
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [pollIntervalMs, setPollIntervalMs] = useState(
    DEFAULT_POLL_INTERVAL_MS,
  );
  const release = usePolledResource<HubReleaseView>(
    "/hub/setting/release",
    pollIntervalMs,
  );
  const { reload: reloadRelease } = release;
  const record = release.data?.update ?? null;
  const runningTaskId = release.data?.task_id ?? null;
  const packageFamily = release.data?.package_family ?? "";
  const isDialogOpen = useUpdateDialog() !== null;
  const followedTaskId = useRef<string | null>(null);
  const wasDialogOpen = useRef(false);

  // An update under way is watched closely; the rest of the time the record
  // only changes when somebody presses Install.
  useEffect(() => {
    const isInFlight = record !== null && STAGES_IN_FLIGHT.has(record.stage);
    setPollIntervalMs(
      isInFlight ? INFLIGHT_POLL_INTERVAL_MS : DEFAULT_POLL_INTERVAL_MS,
    );
  }, [record]);

  // A page opened while the staging runs follows it from where it is, once.
  useEffect(() => {
    if (runningTaskId === null || runningTaskId === followedTaskId.current) {
      return;
    }
    followedTaskId.current = runningTaskId;
    if (isDialogOpen || record === null || record.stage !== "preparing") {
      return;
    }
    openUpdateDialog(
      {
        from: record.from_version,
        version: record.to_version,
        isRollbackAvailable: true,
      },
      INSTALLER_FAMILIES.has(packageFamily),
      runningTaskId,
    );
  }, [runningTaskId, isDialogOpen, record, packageFamily]);

  // The record is read again as soon as the dialog closes.
  useEffect(() => {
    if (wasDialogOpen.current && !isDialogOpen) {
      reloadRelease();
    }
    wasDialogOpen.current = isDialogOpen;
  }, [isDialogOpen, reloadRelease]);

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
    scan.has_package &&
    scan.is_newer &&
    !scan.is_major &&
    scan.is_space_enough;

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
            <RecordNotice record={record} packageFamily={view.package_family} />
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
                  disabled={isScanning || isDialogOpen}
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
                    onClick={() =>
                      openUpdateDialog(
                        {
                          from: scan.current,
                          version: latest.version,
                          isRollbackAvailable: scan.is_rollback_available,
                        },
                        INSTALLER_FAMILIES.has(view.package_family),
                        null,
                      )
                    }
                    disabled={isDialogOpen}
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
              {scan !== null && (
                <ScanResult
                  scan={scan}
                  packageFamily={view?.package_family ?? ""}
                />
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

interface ScanResultProps {
  scan: HubReleaseScanView;
  /** The kind of package this hub was installed from; empty when unknown. */
  packageFamily: HubPackageFamily;
}

function ScanResult({ scan, packageFamily }: ScanResultProps) {
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
      <span className="field_hint">{t("ui.settings.update_on_newest")}</span>
    );
  }
  return (
    <div className="update_found">
      <div className="update_found_line">
        <span className="mono">{latest.version}</span>
        <span className="faint">{localDate(latest.published_at)}</span>
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
      {!scan.has_package && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {packageFamily === ""
              ? t("ui.settings.update_no_package", { version: latest.version })
              : t("ui.settings.update_no_package_family", {
                  version: latest.version,
                  family: packageFamily,
                })}
          </div>
        </div>
      )}
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
  packageFamily: HubPackageFamily;
}

function RecordNotice({ record, packageFamily }: RecordNoticeProps) {
  const isInstallerWorded =
    INSTALLER_FAMILIES.has(packageFamily) &&
    INSTALLER_WORDED_REASONS.has(record.reason);
  const reason =
    record.reason === ""
      ? ""
      : isInstallerWorded
        ? t(`ui.settings.update_reason_installer.${record.reason}`)
        : t(`ui.settings.update_reason.${record.reason}`);
  const values = {
    from: record.from_version,
    to: record.to_version,
    date: localDate(record.finished_at || record.started_at),
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

/**
 * The calendar date of a UTC stamp, in the browser's own time zone.
 *
 * Args:
 *   isoTimestamp: An ISO 8601 stamp.
 *
 * Returns:
 *   `YYYY-MM-DD` in local time, or the stamp's first ten characters when it
 *   will not parse.
 */
function localDate(isoTimestamp: string): string {
  const parsed = Date.parse(isoTimestamp);
  if (Number.isNaN(parsed)) {
    return isoTimestamp.slice(0, 10);
  }
  const date = new Date(parsed);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}
