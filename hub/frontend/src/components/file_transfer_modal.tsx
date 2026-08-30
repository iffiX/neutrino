import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import { apiGet, apiPost, describeError } from "../api_client";
import type { DeviceFileEntry, DeviceFileList, DeviceView } from "../api_types";

import "./file_transfer_modal.css";

/**
 * An SFTP browser for one device, in a window of its own.
 *
 * The gateway relays everything over the device's stored SSH credentials, so
 * this works from anywhere the panel does. Downloads go through the browser's
 * own download machinery; uploads stream the picked files up one at a time.
 */

interface FileTransferModalProps {
  device: DeviceView;
  onClose: () => void;
}

export function FileTransferModal({ device, onClose }: FileTransferModalProps) {
  const [listing, setListing] = useState<DeviceFileList | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState<string | null>(null);
  const [renameFrom, setRenameFrom] = useState<string | null>(null);
  const [renameTo, setRenameTo] = useState("");
  const [deleteName, setDeleteName] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  // React has no typed prop for directory picking, so the attribute is set by
  // hand on the hidden input.
  useEffect(() => {
    folderInputRef.current?.setAttribute("webkitdirectory", "");
  }, []);

  const base = `/devices/${device.mac_address}/files`;

  const load = useCallback(
    // A refresh after an upload or delete keeps the current list mounted, so
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
        const result = await apiGet<DeviceFileList>(
          `${base}?path=${encodeURIComponent(path)}`,
        );
        setListing(result);
      } catch (cause: unknown) {
        setError(describeError(cause));
      } finally {
        setIsLoading(false);
      }
    },
    [base],
  );

  useEffect(() => {
    void load("");
  }, [load]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const path = listing?.path ?? "";
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
    const asArchive = entry.is_dir || entry.name.startsWith(".");
    const endpoint = asArchive ? "download_dir" : "download";
    const url =
      `/api${base}/${endpoint}?path=` +
      encodeURIComponent(joinPath(path, entry.name));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = asArchive
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
      // A folder pick carries each file's place in the tree; a file pick has
      // only the name.
      const relative =
        file.webkitRelativePath.length > 0
          ? file.webkitRelativePath
          : file.name;
      setUploadStatus(`Uploading ${relative} (${index + 1}/${files.length})…`);
      try {
        const query =
          `path=${encodeURIComponent(path)}` +
          `&relative=${encodeURIComponent(relative)}`;
        const response = await fetch(`/api${base}/upload?${query}`, {
          method: "POST",
          body: file,
        });
        if (!response.ok) {
          throw new Error(await readDetail(response));
        }
      } catch (cause: unknown) {
        setError(cause instanceof Error ? cause.message : "The upload failed.");
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
      await apiPost(`${base}/mkdir`, { path: joinPath(path, name) });
      void load(path, true);
    } catch (cause: unknown) {
      setError(describeError(cause));
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
      await apiPost(`${base}/rename`, {
        path: joinPath(path, entry.name),
        new_path: joinPath(path, name),
      });
      void load(path, true);
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  const handleDelete = async (entry: DeviceFileEntry) => {
    setError(null);
    try {
      await apiPost(`${base}/delete`, { path: joinPath(path, entry.name) });
      void load(path, true);
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  return createPortal(
    <div className="file_modal_backdrop" role="dialog" aria-modal="true">
      <div className="file_modal">
        <div className="file_modal_head">
          <div className="file_modal_title">
            <Icon name="folder" size={15} />
            <span className="file_modal_target">
              {device.name ?? device.ipv4_address}
            </span>
          </div>
          <button
            type="button"
            className="button button--small"
            onClick={onClose}
          >
            <Icon name="close" size={13} />
            Close
          </button>
        </div>

        <div className="file_modal_toolbar">
          <div className="file_modal_crumbs">
            {crumbs.map((crumb, index) => (
              <Fragment key={crumb.path}>
                {index > 1 && <span className="file_modal_crumb_sep">/</span>}
                <button
                  type="button"
                  className="file_modal_crumb"
                  onClick={() => void load(crumb.path)}
                >
                  {crumb.label}
                </button>
              </Fragment>
            ))}
          </div>
          <div className="file_modal_tools">
            <button
              type="button"
              className="button button--small"
              onClick={() => setNewFolderName("")}
            >
              <Icon name="plus" size={13} />
              New folder
            </button>
            <button
              type="button"
              className="button button--small"
              disabled={uploadStatus !== null}
              onClick={() => fileInputRef.current?.click()}
            >
              <Icon name="upload" size={13} />
              Upload
            </button>
            <button
              type="button"
              className="button button--small"
              disabled={uploadStatus !== null}
              onClick={() => folderInputRef.current?.click()}
            >
              <Icon name="upload" size={13} />
              Upload folder
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
            <input
              ref={folderInputRef}
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
          <div className="notice notice--error file_modal_notice">
            <Icon name="alert" size={15} />
            <div className="notice_body">{error}</div>
          </div>
        )}
        {uploadStatus !== null && (
          <div className="notice file_modal_notice">
            <Icon name="upload" size={15} />
            <div className="notice_body">{uploadStatus}</div>
          </div>
        )}

        <div className="file_modal_list">
          {newFolderName !== null && (
            <div className="file_modal_row file_modal_row--edit">
              <Icon name="folder" size={14} />
              <input
                className="input file_modal_inline_input"
                autoFocus
                placeholder="folder name"
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
                Create
              </button>
            </div>
          )}

          {isLoading ? (
            <div className="file_modal_placeholder">Loading…</div>
          ) : listing === null || listing.entries.length === 0 ? (
            <div className="file_modal_placeholder">Empty directory</div>
          ) : (
            listing.entries.map((entry) => (
              <div key={entry.name} className="file_modal_row">
                <span
                  className={`file_modal_icon ${entry.is_dir || entry.is_link ? "file_modal_icon--dir" : ""}`}
                >
                  <Icon
                    name={entry.is_dir || entry.is_link ? "folder" : "file"}
                    size={14}
                  />
                </span>
                {renameFrom === entry.name ? (
                  <input
                    className="input file_modal_inline_input"
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
                    className={`file_modal_name ${entry.is_dir || entry.is_link ? "file_modal_name--dir" : ""}`}
                    onClick={() => handleOpen(entry)}
                  >
                    {entry.name}
                    {entry.is_link && <span className="faint"> →</span>}
                  </button>
                )}
                <span className="file_modal_size">
                  {entry.is_dir ? "" : formatSize(entry.size_bytes)}
                </span>
                <span className="file_modal_time">
                  {formatModified(entry.modified_at)}
                </span>
                <span className="file_modal_actions">
                  {!entry.is_link && (
                    <button
                      type="button"
                      className="file_modal_action"
                      title={entry.is_dir ? "Download as tar.gz" : "Download"}
                      onClick={() => handleDownload(entry)}
                    >
                      <Icon name="download" size={13} />
                    </button>
                  )}
                  <button
                    type="button"
                    className="file_modal_action"
                    title="Rename"
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
                      className="file_modal_action file_modal_action--danger"
                      title="Click again to delete"
                      onClick={() => void handleDelete(entry)}
                    >
                      <Icon name="check" size={13} />
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="file_modal_action file_modal_action--danger"
                      title="Delete"
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

        <div className="file_modal_status">
          {deleteName !== null
            ? `Deleting ${deleteName} cannot be undone; the red check confirms it.`
            : "Transfers go through the gateway over the device's SSH."}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function joinPath(base: string, name: string): string {
  return base.endsWith("/") ? `${base}${name}` : `${base}/${name}`;
}

function toCrumbs(path: string): { label: string; path: string }[] {
  const crumbs = [{ label: "/", path: "/" }];
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

async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Fall through to the generic message.
  }
  return `Upload failed with status ${response.status}.`;
}
