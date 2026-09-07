import { useState } from "react";
import type { FormEvent } from "react";

import { Icon } from "./icon";
import "./string_list_editor.css";

/**
 * A chip list of freeform strings, used for the direct domain and IP rules.
 *
 * The values are xray routing rules (`geosite:cn`, `192.168.0.0/16`), which
 * the backend validates, so the editor's job is only to keep the list tidy:
 * trim, refuse blanks, and refuse a duplicate rather than silently adding a
 * second copy that would confuse the rendered config.
 */

interface StringListEditorProps {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  description?: string;
  placeholder?: string;
  emptyText?: string;
}

export function StringListEditor({
  label,
  values,
  onChange,
  description,
  placeholder = "Add an entry",
  emptyText = "No entries; everything goes through the proxy.",
}: StringListEditorProps) {
  const [draft, setDraft] = useState("");

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
          <span className="string_list_editor_empty">{emptyText}</span>
        )}
        {values.map((value) => (
          <span key={value} className="string_list_editor_chip">
            {value}
            <button
              type="button"
              className="string_list_editor_remove"
              aria-label={`Remove ${value}`}
              onClick={() => handleRemove(value)}
            >
              <Icon name="close" size={11} />
            </button>
          </span>
        ))}
      </div>

      <form className="string_list_editor_add" onSubmit={handleAdd}>
        <input
          className="input"
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" className="button button--small">
          <Icon name="plus" size={13} />
          Add
        </button>
      </form>
    </div>
  );
}
