import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "./icon";
import {
  ApiError,
  apiGet,
  apiPost,
  apiUpload,
  describeError,
} from "../api_client";
import type { DeviceFileEntry, DeviceFileListView } from "../api_types";

import "./file_browser.css";

/**
 * The files on one machine, browsed through its agent.
 *
 * The agent reads and writes as root, so the browser opens at the machine's
 * root rather than at a home directory. Every operation acts at once and the
 * listing is read again after it, so what is on screen is what is on the
 * machine.
 */

const WORDING = {
  newFolder: "New folder",
  create: "Create",
  upload: "Upload",
  folderName: "folder name",
  rename: "Rename",
  delete: "Delete",
  deleteArmed: "Click again to delete",
  download: "Download",
  downloadArchive: "Download as tar.gz",
  loading: "Loading…",
  empty: "Empty directory",
  uploading: "Uploading {name} ({index}/{total})…",
  deleting: "Deleting {name} cannot be undone; the red check confirms it.",
  root: "The agent reads and writes as root on this machine.",
};

// The {code, params} the files API refuses with, worded. A code with no entry
// falls through to the API's own sentence.
const FILE_ERROR_WORDING: Record<string, string> = {
  agent_offline:
    "The machine is not answering, so nothing was read or written.",
  path_missing: "There is nothing at that path any more.",
  path_invalid: "That path is not one this machine will open.",
  file_exists: "Something of that name is already there.",
  write_failed: "The machine could not write that.",
  op_failed: "The machine could not do that.",
};

// Where a browse starts. The agent has the whole filesystem.
const ROOT_PATH = "/";

interface FileBrowserProps {
  /** Where this machine's files answer, below `/api`: `/devices/<id>/files`. */
  basePath: string;
}

export function FileBrowser({ basePath }: FileBrowserProps) {
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
    async (path: string, isRefresh = false) => {
      if (!isRefresh) {
        setIsLoading(true);
      }
      setError(null);
      setNewFolderName(null);
      setRenameFrom(null);
      setDeleteName(null);
      try {
        const result = await apiGet<DeviceFileListView>(
          `${basePath}?path=${encodeURIComponent(path)}`,
        );
        setListing(result);
      } catch (cause: unknown) {
        setError(describeFileError(cause));
      } finally {
        setIsLoading(false);
      }
    },
    [basePath],
  );

  useEffect(() => {
    setListing(null);
    void load(ROOT_PATH);
  }, [load]);

  const path = listing?.path ?? ROOT_PATH;
  const crumbs = toCrumbs(path);

  const handleOpen = (entry: DeviceFileEntry) => {
    if (entry.is_dir || entry.is_link) {
      void load(joinPath(path, entry.name));
    }
  };

  const handleDownload = (entry: DeviceFileEntry) => {
    // Directories leave as a tar.gz packed on the fly — and so do dot-named
    // files, because browsers strip a hidden-file name's leading dot from any
    // raw download; inside an archive the real name survives.
    const isArchive = entry.is_dir || entry.name.startsWith(".");
    const endpoint = isArchive ? "download_dir" : "download";
    const url =
      `/api${basePath}/${endpoint}?path=` +
      encodeURIComponent(joinPath(path, entry.name));
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
        fill(WORDING.uploading, {
          name: file.name,
          index: String(index + 1),
          total: String(files.length),
        }),
      );
      try {
        await apiUpload<Record<string, never>>(`${basePath}/upload`, file, {
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
      await apiPost(`${basePath}/mkdir`, { path: joinPath(path, name) });
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
      await apiPost(`${basePath}/rename`, {
        path: joinPath(path, entry.name),
        new_path: joinPath(path, name),
      });
      void load(path, true);
    } catch (cause: unknown) {
      setError(describeFileError(cause));
    }
  };

  const handleDelete = async (entry: DeviceFileEntry) => {
    setError(null);
    try {
      await apiPost(`${basePath}/delete`, { path: joinPath(path, entry.name) });
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
              {index > 1 && <span className="file_browser_crumb_sep">/</span>}
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
        <div className="file_browser_tools">
          <button
            type="button"
            className="button button--small"
            onClick={() => setNewFolderName("")}
          >
            <Icon name="plus" size={13} />
            {WORDING.newFolder}
          </button>
          <button
            type="button"
            className="button button--small"
            disabled={uploadStatus !== null}
            onClick={() => fileInputRef.current?.click()}
          >
            <Icon name="upload" size={13} />
            {WORDING.upload}
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
              placeholder={WORDING.folderName}
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
              {WORDING.create}
            </button>
          </div>
        )}

        {isLoading ? (
          <div className="file_browser_placeholder">{WORDING.loading}</div>
        ) : listing === null || listing.entries.length === 0 ? (
          <div className="file_browser_placeholder">{WORDING.empty}</div>
        ) : (
          listing.entries.map((entry) => (
            <div key={entry.name} className="file_browser_row">
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
              <span className="file_browser_actions">
                {!entry.is_link && (
                  <button
                    type="button"
                    className="file_browser_action"
                    title={
                      entry.is_dir ? WORDING.downloadArchive : WORDING.download
                    }
                    onClick={() => handleDownload(entry)}
                  >
                    <Icon name="download" size={13} />
                  </button>
                )}
                <button
                  type="button"
                  className="file_browser_action"
                  title={WORDING.rename}
                  onClick={() => {
                    setRenameFrom(entry.name);
                    setRenameTo(entry.name);
                    setDeleteName(null);
                  }}
                >
                  <Icon name="edit" size={13} />
                </button>
                {deleteName === entry.name ? (
                  <button
                    type="button"
                    className="file_browser_action file_browser_action--danger"
                    title={WORDING.deleteArmed}
                    onClick={() => void handleDelete(entry)}
                  >
                    <Icon name="check" size={13} />
                  </button>
                ) : (
                  <button
                    type="button"
                    className="file_browser_action file_browser_action--danger"
                    title={WORDING.delete}
                    onClick={() => {
                      setDeleteName(entry.name);
                      setRenameFrom(null);
                    }}
                  >
                    <Icon name="trash" size={13} />
                  </button>
                )}
              </span>
            </div>
          ))
        )}
      </div>

      <div className="file_browser_status">
        {deleteName !== null
          ? fill(WORDING.deleting, { name: deleteName })
          : WORDING.root}
      </div>
    </div>
  );
}

/** Put names and counts into a wording constant, by name. */
function fill(wording: string, values: Record<string, string>): string {
  let filled = wording;
  for (const [name, value] of Object.entries(values)) {
    filled = filled.replace(`{${name}}`, value);
  }
  return filled;
}

/** Wording for a refused file operation, from the code the API returned. */
function describeFileError(cause: unknown): string {
  if (cause instanceof ApiError) {
    const wording = FILE_ERROR_WORDING[cause.code];
    if (wording !== undefined) {
      return wording;
    }
  }
  return describeError(cause);
}

function joinPath(base: string, name: string): string {
  return base.endsWith("/") ? `${base}${name}` : `${base}/${name}`;
}

function toCrumbs(path: string): { label: string; path: string }[] {
  const crumbs = [{ label: "/", path: ROOT_PATH }];
  const parts = path.split("/").filter((part) => part.length > 0);
  let current = "";
  for (const part of parts) {
    current += `/${part}`;
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
