import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "./icon";
import { RowMenu } from "./row_menu";
import type { RowMenuItem } from "./row_menu";
import {
  ApiError,
  apiGet,
  apiPath,
  apiPost,
  apiUpload,
  describeError,
} from "../api_client";
import { t, useLanguage } from "../i18n";
import { usePageMemory } from "../use_page_memory";
import type { DeviceFileEntry, DeviceFileListView } from "../api_types";

import "./file_browser.css";

/**
 * The files on one machine, browsed through its agent.
 *
 * The agent reads and writes as root, so the browser opens at the machine's
 * root rather than at a home directory; a Windows machine's root is its
 * drives, and its paths use the separator the listing names. Every
 * operation acts at once and the listing is read again after it, so what is
 * on screen is what is on the machine. Given `onPickDirectory`, it picks a
 * directory instead: files are greyed, nothing is changed, and the foot
 * chooses the directory open.
 */

// The codes the files API refuses with, and the sentence each is worded as. A
// code with no entry falls through to the API's own sentence.
const FILE_ERROR_KEYS: Record<string, string> = {
  agent_offline: "ui.files.agent_offline",
  path_missing: "code.path_missing",
  path_invalid: "code.path_invalid",
  file_exists: "code.file_exists",
  write_failed: "code.write_failed",
  op_failed: "code.op_failed",
};

// Where a browse starts. The agent has the whole filesystem.
const ROOT_PATH = "/";
// The separator of a machine whose paths are not Windows paths.
const POSIX_SEPARATOR = "/";

interface FileBrowserProps {
  /** The machine whose files these are. */
  deviceId: string;
  /** Picks a directory instead of managing files: called with the path of
   * the directory open when Choose this folder is pressed. */
  onPickDirectory?: (path: string) => void;
  /** Called by the foot's Cancel while picking. */
  onCancel?: () => void;
  /** Where a pick starts; the root when empty or when it cannot be read. */
  startPath?: string;
  /** The system the machine's agent reports, which names its account. */
  platformOs?: string;
}

export function FileBrowser({
  deviceId,
  onPickDirectory,
  onCancel,
  startPath = "",
  platformOs = "",
}: FileBrowserProps) {
  const isPicking = onPickDirectory !== undefined;
  // Redrawn when the panel's language changes.
  useLanguage();
  const [listing, setListing] = useState<DeviceFileListView | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState<string | null>(null);
  const [renameFrom, setRenameFrom] = useState<string | null>(null);
  const [renameTo, setRenameTo] = useState("");
  const [deleteName, setDeleteName] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(
    // A refresh after an upload or a delete keeps the current list mounted, so
    // the view does not swap to the loading placeholder and lose its scroll
    // position; only real navigation does.
    async (path: string, isRefresh = false): Promise<boolean> => {
      if (!isRefresh) {
        setIsLoading(true);
      }
      setError(null);
      setNewFolderName(null);
      setRenameFrom(null);
      setDeleteName(null);
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

  // The directory open on this machine, read back on the next visit. Where
  // this mount starts is fixed at the first render: what changes it after
  // that is this browser's own navigation, already loaded.
  const [rememberedPath, rememberPath] = usePageMemory(
    `files.path.${deviceId}`,
    ROOT_PATH,
  );
  const firstPath = useRef(
    isPicking ? startPath.trim() || ROOT_PATH : rememberedPath,
  );

  useEffect(() => {
    setListing(null);
    const first = firstPath.current;
    void load(first).then((isRead) => {
      if (!isRead && isPicking && first !== ROOT_PATH) {
        void load(ROOT_PATH);
      }
    });
  }, [load, isPicking]);

  const path = listing?.path ?? ROOT_PATH;
  const separator = listing?.separator ?? POSIX_SEPARATOR;
  const isDriveList = path === ROOT_PATH && separator !== POSIX_SEPARATOR;
  useEffect(() => {
    if (listing !== null && !isPicking) {
      rememberPath(listing.path);
    }
  }, [listing, rememberPath, isPicking]);
  const crumbs = toCrumbs(path, separator);

  const handleOpen = (entry: DeviceFileEntry) => {
    if (entry.is_dir || entry.is_link) {
      void load(toEntryPath(path, separator, entry));
    }
  };

  const handleDownload = (entry: DeviceFileEntry) => {
    // Directories leave as a tar.gz packed on the fly — and so do dot-named
    // files, because browsers strip a hidden-file name's leading dot from any
    // raw download; inside an archive the real name survives.
    const isArchive = entry.is_dir || entry.name.startsWith(".");
    const endpoint = isArchive
      ? "/agent/file/directory/download"
      : "/agent/file/download";
    const url = `/api${apiPath(endpoint, {
      device_id: deviceId,
      path: toEntryPath(path, separator, entry),
    })}`;
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = isArchive
      ? `${entry.name.replace(/^\.+/, "") || "archive"}.tar.gz`
      : entry.name;
    anchor.click();
  };

  const handleUploadPicked = async (files: FileList | null) => {
    if (files === null || files.length === 0) {
      return;
    }
    setError(null);
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      if (file === undefined) {
        continue;
      }
      setUploadStatus(
        t("ui.files.uploading", {
          name: file.name,
          index: index + 1,
          total: files.length,
        }),
      );
      try {
        await apiUpload<Record<string, never>>("/agent/file/upload", file, {
          device_id: deviceId,
          path,
        });
      } catch (cause: unknown) {
        setError(describeFileError(cause));
        break;
      }
    }
    setUploadStatus(null);
    void load(path, true);
  };

  const handleMakeFolder = async () => {
    const name = (newFolderName ?? "").trim();
    if (name.length === 0) {
      setNewFolderName(null);
      return;
    }
    setError(null);
    try {
      await apiPost("/agent/file/directory/create", {
        device_id: deviceId,
        path: joinPath(path, name, separator),
      });
      void load(path, true);
    } catch (cause: unknown) {
      setError(describeFileError(cause));
    }
  };

  const handleRename = async (entry: DeviceFileEntry) => {
    const name = renameTo.trim();
    if (name.length === 0 || name === entry.name) {
      setRenameFrom(null);
      return;
    }
    setError(null);
    try {
      await apiPost("/agent/file/rename", {
        device_id: deviceId,
        path: toEntryPath(path, separator, entry),
        new_path: joinPath(path, name, separator),
      });
      void load(path, true);
    } catch (cause: unknown) {
      setError(describeFileError(cause));
    }
  };

  const startRename = (entry: DeviceFileEntry) => {
    setRenameFrom(entry.name);
    setRenameTo(entry.name);
    setDeleteName(null);
  };

  const armDelete = (entry: DeviceFileEntry) => {
    setDeleteName(entry.name);
    setRenameFrom(null);
  };

  // The same actions as the row's hover buttons, for the ⋯ menu; deleting
  // arms on the first press and acts on the second, as the button does.
  const rowItems = (entry: DeviceFileEntry): RowMenuItem[] => {
    const isArmed = deleteName === entry.name;
    const items: RowMenuItem[] = [];
    if (!entry.is_link) {
      items.push({
        key: "download",
        label: entry.is_dir
          ? t("ui.files.download_archive")
          : t("ui.files.download"),
        icon: "download",
        onSelect: () => handleDownload(entry),
      });
    }
    items.push(
      {
        key: "rename",
        label: t("ui.files.rename"),
        icon: "edit",
        onSelect: () => startRename(entry),
      },
      {
        key: "delete",
        label: isArmed ? t("ui.files.delete_armed") : t("ui.files.delete"),
        icon: "trash",
        isDanger: true,
        isArming: true,
        isArmed,
        onSelect: () => (isArmed ? void handleDelete(entry) : armDelete(entry)),
      },
    );
    return items;
  };

  const handleDelete = async (entry: DeviceFileEntry) => {
    setError(null);
    try {
      await apiPost("/agent/file/remove", {
        device_id: deviceId,
        path: toEntryPath(path, separator, entry),
      });
      void load(path, true);
    } catch (cause: unknown) {
      setError(describeFileError(cause));
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
        {!isPicking && (
          <div className="file_browser_tools">
            <button
              type="button"
              className="button button--small"
              disabled={isDriveList}
              onClick={() => setNewFolderName("")}
            >
              <Icon name="plus" size={13} />
              {t("ui.files.new_folder")}
            </button>
            <button
              type="button"
              className="button button--small"
              disabled={isDriveList || uploadStatus !== null}
              onClick={() => fileInputRef.current?.click()}
            >
              <Icon name="upload" size={13} />
              {t("ui.files.upload")}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={(event) => {
                void handleUploadPicked(event.target.files);
                event.target.value = "";
              }}
            />
          </div>
        )}
      </div>

      {error !== null && (
        <div className="notice notice--error file_browser_notice">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
      {uploadStatus !== null && (
        <div className="notice file_browser_notice">
          <Icon name="upload" size={15} />
          <div className="notice_body">{uploadStatus}</div>
        </div>
      )}

      <div className="file_browser_list">
        {newFolderName !== null && (
          <div className="file_browser_row file_browser_row--edit">
            <Icon name="folder" size={14} />
            <input
              className="input file_browser_inline_input"
              autoFocus
              placeholder={t("ui.files.folder_name")}
              value={newFolderName}
              onChange={(event) => setNewFolderName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void handleMakeFolder();
                }
                if (event.key === "Escape") {
                  setNewFolderName(null);
                }
              }}
            />
            <button
              type="button"
              className="button button--small"
              onClick={() => void handleMakeFolder()}
            >
              <Icon name="check" size={13} />
              {t("ui.files.create")}
            </button>
          </div>
        )}

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
                isPicking && !entry.is_dir && !entry.is_link
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
              {renameFrom === entry.name ? (
                <input
                  className="input file_browser_inline_input"
                  autoFocus
                  value={renameTo}
                  onChange={(event) => setRenameTo(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      void handleRename(entry);
                    }
                    if (event.key === "Escape") {
                      setRenameFrom(null);
                    }
                  }}
                  onBlur={() => void handleRename(entry)}
                />
              ) : (
                <button
                  type="button"
                  className={`file_browser_name ${entry.is_dir || entry.is_link ? "file_browser_name--dir" : ""}`}
                  onClick={() => handleOpen(entry)}
                >
                  {entry.name}
                  {entry.is_link && <span className="faint"> →</span>}
                </button>
              )}
              <span className="file_browser_size">
                {entry.is_dir ? "" : formatSize(entry.size_bytes)}
              </span>
              <span className="file_browser_time">
                {formatModified(entry.modified_at)}
              </span>
              {!isDriveList && !isPicking && (
                <RowMenu items={rowItems(entry)}>
                  <span className="file_browser_actions">
                    {!entry.is_link && (
                      <button
                        type="button"
                        className="file_browser_action"
                        title={
                          entry.is_dir
                            ? t("ui.files.download_archive")
                            : t("ui.files.download")
                        }
                        onClick={() => handleDownload(entry)}
                      >
                        <Icon name="download" size={13} />
                      </button>
                    )}
                    <button
                      type="button"
                      className="file_browser_action"
                      title={t("ui.files.rename")}
                      onClick={() => startRename(entry)}
                    >
                      <Icon name="edit" size={13} />
                    </button>
                    {deleteName === entry.name ? (
                      <button
                        type="button"
                        className="file_browser_action file_browser_action--danger"
                        title={t("ui.files.delete_armed")}
                        onClick={() => void handleDelete(entry)}
                      >
                        <Icon name="check" size={13} />
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="file_browser_action file_browser_action--danger"
                        title={t("ui.files.delete")}
                        onClick={() => armDelete(entry)}
                      >
                        <Icon name="trash" size={13} />
                      </button>
                    )}
                  </span>
                </RowMenu>
              )}
            </div>
          ))
        )}
      </div>

      {isPicking ? (
        <div className="file_browser_pick_foot">
          <span className="file_browser_pick_path">
            {isDriveList ? t("ui.files.pick_drive") : path}
          </span>
          <button type="button" className="button" onClick={onCancel}>
            {t("ui.confirm.cancel")}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={listing === null || isDriveList}
            onClick={() => onPickDirectory(path)}
          >
            <Icon name="check" size={14} />
            {t("ui.files.pick_choose")}
          </button>
        </div>
      ) : (
        <div className="file_browser_status">
          {deleteName !== null
            ? t("ui.files.deleting", { name: deleteName })
            : t(
                platformOs === "windows"
                  ? "ui.files.root_windows"
                  : "ui.files.root",
              )}
        </div>
      )}
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
