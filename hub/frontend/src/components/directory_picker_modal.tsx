import { useEffect } from "react";
import { createPortal } from "react-dom";

import { FileBrowser } from "./file_browser";
import { Icon } from "./icon";
import { t, useLanguage } from "../i18n";

import "./directory_picker_modal.css";

/**
 * A directory on one machine, picked by browsing it rather than typed.
 *
 * The file browser in its pick mode, in a modal over a blurred page: it
 * opens at the path already in the field, or at the root, and Choose this
 * folder hands back the directory open. Escape and the backdrop cancel.
 */

interface DirectoryPickerModalProps {
  /** The machine whose directories these are. */
  deviceId: string;
  /** Where the browse starts: the field's path, empty for the root. */
  startPath: string;
  onPick: (path: string) => void;
  onCancel: () => void;
}

export function DirectoryPickerModal({
  deviceId,
  startPath,
  onPick,
  onCancel,
}: DirectoryPickerModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return createPortal(
    <div
      className="directory_picker_backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={t("ui.files.pick_title")}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onCancel();
        }
      }}
    >
      <div className="directory_picker_modal">
        <div className="directory_picker_head">
          <Icon name="folder" size={16} />
          <h2>{t("ui.files.pick_title")}</h2>
        </div>
        <FileBrowser
          deviceId={deviceId}
          startPath={startPath}
          onPickDirectory={onPick}
          onCancel={onCancel}
        />
      </div>
    </div>,
    document.body,
  );
}
