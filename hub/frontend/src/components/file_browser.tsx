import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "./icon";
import { ApiError, apiGet, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type { DeviceFileEntry, DeviceFileListView } from "../api_types";

import "./file_browser.css";

/**
 * The path window's listing: the folders and files of one machine, read
 * through its agent, to pick a folder or a file.
 *
 * It opens at the path given, or at the machine's root when that cannot be
 * read; a Windows machine's root is its drives, and its paths use the
 * separator the listing names. Picking a folder, files are greyed and the
 * foot chooses the folder open; picking a file, a press on a file hands its
 * path back. Nothing on the machine changes.
 */

// The codes the listing is refused with, and the sentence each is worded as.
// A code with no entry falls through to the API's own sentence.
const FILE_ERROR_KEYS: Record<string, string> = {
  agent_offline: "ui.files.agent_offline",
  path_missing: "code.path_missing",
  path_invalid: "code.path_invalid",
  op_failed: "code.op_failed",
};

// Where a browse starts. The agent lists the whole filesystem.
const ROOT_PATH = "/";
// The separator of a machine whose paths are not Windows paths.
const POSIX_SEPARATOR = "/";

interface FileBrowserProps {
  /** The machine whose files these are. */
  deviceId: string;
  /** What a pick hands back: the folder open, or the file pressed. */
  pick: "directory" | "file";
  /** Called with the path picked. */
  onPick: (path: string) => void;
  /** Called by the foot's Cancel. */
  onCancel: () => void;
  /** Where the browse starts; the root when empty or when it cannot be read. */
  startPath?: string;
}

export function FileBrowser({
  deviceId,
  pick,
  onPick,
  onCancel,
  startPath = "",
}: FileBrowserProps) {
  const isPickingFile = pick === "file";
  // Redrawn when the panel's language changes.
  useLanguage();
  const [listing, setListing] = useState<DeviceFileListView | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (path: string): Promise<boolean> => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await apiGet<DeviceFileListView>("/agent/file", {
          device_id: deviceId,
          path,
        });
        setListing(result);
        return true;
      } catch (cause: unknown) {
        setError(describeFileError(cause));
        return false;
      } finally {
        setIsLoading(false);
      }
    },
    [deviceId],
  );

  // Where this mount starts is fixed at the first render.
  const firstPath = useRef(startPath.trim() || ROOT_PATH);

  useEffect(() => {
    setListing(null);
    const first = firstPath.current;
    void load(first).then((isRead) => {
      if (!isRead && first !== ROOT_PATH) {
        void load(ROOT_PATH);
      }
    });
  }, [load]);

  const path = listing?.path ?? ROOT_PATH;
  const separator = listing?.separator ?? POSIX_SEPARATOR;
  const isDriveList = path === ROOT_PATH && separator !== POSIX_SEPARATOR;
  const crumbs = toCrumbs(path, separator);

  const handleOpen = (entry: DeviceFileEntry) => {
    if (entry.is_dir || entry.is_link) {
      void load(toEntryPath(path, separator, entry));
    } else if (isPickingFile) {
      onPick(toEntryPath(path, separator, entry));
    }
  };

  return (
    <div className="file_browser">
      <div className="file_browser_toolbar">
        <div className="file_browser_crumbs">
          {crumbs.map((crumb, index) => (
            <Fragment key={crumb.path}>
              {index > 1 && (
                <span className="file_browser_crumb_sep">{separator}</span>
              )}
              <button
                type="button"
                className="file_browser_crumb"
                onClick={() => void load(crumb.path)}
              >
                {crumb.label}
              </button>
            </Fragment>
          ))}
        </div>
      </div>

      {error !== null && (
        <div className="notice notice--error file_browser_notice">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      <div className="file_browser_list">
        {isLoading ? (
          <div className="file_browser_placeholder">
            {t("ui.files.loading")}
          </div>
        ) : listing === null || listing.entries.length === 0 ? (
          <div className="file_browser_placeholder">{t("ui.files.empty")}</div>
        ) : (
          listing.entries.map((entry) => (
            <div
              key={entry.name}
              className={`file_browser_row ${
                !isPickingFile && !entry.is_dir && !entry.is_link
                  ? "file_browser_row--muted"
                  : ""
              }`}
            >
              <span
                className={`file_browser_icon ${entry.is_dir || entry.is_link ? "file_browser_icon--dir" : ""}`}
              >
                <Icon
                  name={entry.is_dir || entry.is_link ? "folder" : "file"}
                  size={14}
                />
              </span>
              <button
                type="button"
                className={`file_browser_name ${entry.is_dir || entry.is_link ? "file_browser_name--dir" : ""}`}
                onClick={() => handleOpen(entry)}
              >
                {entry.name}
                {entry.is_link && <span className="faint"> →</span>}
              </button>
              <span className="file_browser_size">
                {entry.is_dir ? "" : formatSize(entry.size_bytes)}
              </span>
              <span className="file_browser_time">
                {formatModified(entry.modified_at)}
              </span>
            </div>
          ))
        )}
      </div>

      <div className="file_browser_pick_foot">
        <span className="file_browser_pick_path">
          {!isDriveList ? path : isPickingFile ? "" : t("ui.files.pick_drive")}
        </span>
        <button type="button" className="button" onClick={onCancel}>
          {t("ui.confirm.cancel")}
        </button>
        {!isPickingFile && (
          <button
            type="button"
            className="button button--primary"
            disabled={listing === null || isDriveList}
            onClick={() => onPick(path)}
          >
            <Icon name="check" size={14} />
            {t("ui.files.pick_choose")}
          </button>
        )}
      </div>
    </div>
  );
}

/** Wording for a refused file operation, from the code the API returned. */
function describeFileError(cause: unknown): string {
  if (cause instanceof ApiError) {
    const key = FILE_ERROR_KEYS[cause.code];
    if (key !== undefined) {
      return t(key);
    }
  }
  return describeError(cause);
}

function joinPath(base: string, name: string, separator: string): string {
  return base.endsWith(separator)
    ? `${base}${name}`
    : `${base}${separator}${name}`;
}

/** An entry's path as the machine wrote it, or joined when it named none. */
function toEntryPath(
  base: string,
  separator: string,
  entry: DeviceFileEntry,
): string {
  return entry.path || joinPath(base, entry.name, separator);
}

/**
 * The crumbs from the root to a path. On a Windows machine the root is the
 * drive list and the first part is a drive, such as `C:` for `C:\`.
 */
function toCrumbs(
  path: string,
  separator: string,
): { label: string; path: string }[] {
  if (separator === POSIX_SEPARATOR) {
    const crumbs = [{ label: ROOT_PATH, path: ROOT_PATH }];
    let current = "";
    for (const part of path.split(separator).filter(Boolean)) {
      current += `${separator}${part}`;
      crumbs.push({ label: part, path: current });
    }
    return crumbs;
  }
  const crumbs = [{ label: t("ui.files.drives"), path: ROOT_PATH }];
  if (path === ROOT_PATH) {
    return crumbs;
  }
  let current = "";
  for (const part of path.split(separator).filter(Boolean)) {
    current =
      current === ""
        ? `${part}${separator}`
        : joinPath(current, part, separator);
    crumbs.push({ label: part, path: current });
  }
  return crumbs;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let value = bytes;
  let unit = "B";
  for (const next of units) {
    if (value < 1024) {
      break;
    }
    value /= 1024;
    unit = next;
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${unit}`;
}

function formatModified(epochSeconds: number): string {
  if (epochSeconds <= 0) {
    return "";
  }
  const date = new Date(epochSeconds * 1000);
  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}
