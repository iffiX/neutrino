import { DialogLayer } from "./dialog_layer";
import { FileBrowser } from "./file_browser";
import { Icon } from "./icon";
import { t, useLanguage } from "../i18n";

import "./directory_picker_modal.css";

/**
 * A directory on one machine, or in file mode a file, picked by browsing it
 * rather than typed.
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
  /** What a pick hands back: the directory open, or the file pressed. */
  pick?: "directory" | "file";
  onPick: (path: string) => void;
  onCancel: () => void;
}

export function DirectoryPickerModal({
  deviceId,
  startPath,
  pick = "directory",
  onPick,
  onCancel,
}: DirectoryPickerModalProps) {
  const title = t(
    pick === "file" ? "ui.files.pick_file_title" : "ui.files.pick_title",
  );
  // Redrawn when the panel's language changes.
  useLanguage();

  return (
    <DialogLayer label={title} onDismiss={onCancel}>
      <div className="directory_picker_modal">
        <div className="directory_picker_head">
          <Icon name={pick === "file" ? "file" : "folder"} size={16} />
          <h2>{title}</h2>
        </div>
        <FileBrowser
          deviceId={deviceId}
          startPath={startPath}
          pick={pick}
          onPick={onPick}
          onCancel={onCancel}
        />
      </div>
    </DialogLayer>
  );
}
