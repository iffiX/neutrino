import { useState } from "react";
import type { FormEvent } from "react";

import { Icon } from "./icon";
import { t, useLanguage } from "../i18n";

import "./string_list_editor.css";

/**
 * A chip list of freeform strings, used for the direct domain and IP rules.
 *
 * The values are xray routing rules (`geosite:cn`, `192.168.0.0/16`), which
 * the backend validates, so the editor's job is only to keep the list tidy:
 * trim, refuse blanks, and refuse a duplicate rather than silently adding a
 * second copy that would confuse the rendered config. With Browse… a row
 * starts with a folder of a machine, `<folder>:<rest>`, as a volume does.
 */

/** A Windows drive at the start of a row: its colon belongs to the folder. */
const DRIVE_PATTERN = /^[A-Za-z]:(?=[\\/]|$)/;

interface StringListEditorProps {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  description?: string;
  /** What the add field shows while empty; a plain invitation when not given. */
  placeholder?: string;
  /** What stands in for an empty list; the proxy sentence when not given. */
  emptyText?: string;
  /**
   * Opens the path window at `startPath`, the folder the add field names,
   * and hands the folder chosen to `pick`. Given with `browseLabel`, the
   * button follows Add.
   */
  onBrowse?: (startPath: string, pick: (folder: string) => void) => void;
  browseLabel?: string;
}

export function StringListEditor({
  label,
  values,
  onChange,
  description,
  placeholder,
  emptyText,
  onBrowse,
  browseLabel,
}: StringListEditorProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [draft, setDraft] = useState("");
  const isBrowsable = onBrowse !== undefined && browseLabel !== undefined;

  const handleAdd = (event: FormEvent) => {
    event.preventDefault();
    const entry = draft.trim();
    if (entry.length === 0 || values.includes(entry)) {
      setDraft("");
      return;
    }
    onChange([...values, entry]);
    setDraft("");
  };

  const handleRemove = (entry: string) => {
    onChange(values.filter((value) => value !== entry));
  };

  const handleBrowse = () => {
    onBrowse?.(rowFolder(draft.trim()), (folder) =>
      setDraft((current) => withRowFolder(current.trim(), folder)),
    );
  };

  return (
    <div className="string_list_editor">
      <div className="field">
        <span className="field_label">{label}</span>
        {description !== undefined && (
          <span className="field_hint">{description}</span>
        )}
      </div>

      <div className="string_list_editor_chips">
        {values.length === 0 && (
          <span className="string_list_editor_empty">
            {emptyText ?? t("ui.list.empty")}
          </span>
        )}
        {values.map((value) => (
          <span key={value} className="string_list_editor_chip">
            <span className="string_list_editor_value">{value}</span>
            <button
              type="button"
              className="string_list_editor_remove"
              aria-label={t("ui.list.remove", { name: value })}
              onClick={() => handleRemove(value)}
            >
              <Icon name="close" size={11} />
            </button>
          </span>
        ))}
      </div>

      <form
        className={`string_list_editor_add ${
          isBrowsable ? "string_list_editor_add--browse" : ""
        }`}
        onSubmit={handleAdd}
      >
        <input
          className="input"
          value={draft}
          placeholder={placeholder ?? t("ui.list.add_placeholder")}
          onChange={(event) => setDraft(event.target.value)}
        />
        <div className="string_list_editor_buttons">
          <button type="submit" className="button button--small">
            <Icon name="plus" size={13} />
            {t("ui.list.add")}
          </button>
          {isBrowsable && (
            <button
              type="button"
              className="button button--small"
              onClick={handleBrowse}
            >
              <Icon name="folder" size={13} />
              {browseLabel}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

/** Where a row's own colon is, after a drive's; -1 when it has none. */
function separatorAt(row: string): number {
  const drive = DRIVE_PATTERN.exec(row);
  return row.indexOf(":", drive === null ? 0 : drive[0].length);
}

/** The folder a row names: what comes before its own colon, or all of it. */
function rowFolder(row: string): string {
  const at = separatorAt(row);
  return at < 0 ? row : row.slice(0, at);
}

/** The row with its folder replaced by `folder` and `:` after it, keeping
 * what followed the row's own colon. */
function withRowFolder(row: string, folder: string): string {
  const at = separatorAt(row);
  return `${folder}:${at < 0 ? "" : row.slice(at + 1)}`;
}
