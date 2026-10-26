import { useState } from "react";

import { DialogFrame } from "./dialog_frame";
import { Icon } from "./icon";
import { Picker } from "./picker";
import { Spinner } from "./spinner";
import { ApiError, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type { PickerOption } from "./picker";
import type {
  DeclaredAppCreate,
  DeclaredEntryCreate,
  DeclaredEntryType,
  ServiceListView,
} from "../api_types";

import "./declare_service_modal.css";

/**
 * The **Declare service** dialog: one app a machine of the network serves,
 * by its name, its host and a line on it, and its entries. Each entry row
 * is a type, Web, Port or File, its port, then the scheme and the path of a
 * page, the protocol of a port, or the share of a file server; Add entry
 * adds a row and Remove takes one away. The foot holds Cancel and Declare.
 */

/** The port a file entry takes when its field is left blank. */
const FILE_PORT = "445";

/** The path a web entry starts with. */
const WEB_PATH = "/";

const TYPE_KEYS: Record<DeclaredEntryType, string> = {
  web: "ui.services.kind_web",
  port: "ui.services.kind_port",
  file: "ui.services.kind_file",
};

/** The schemes a web entry is opened with. */
const SCHEME_OPTIONS: PickerOption[] = [
  { id: "http", name: "http" },
  { id: "https", name: "https" },
];

/** The protocols a port entry is reached over. */
const PROTOCOL_OPTIONS: PickerOption[] = [
  { id: "tcp", name: "TCP" },
  { id: "udp", name: "UDP" },
];

// The API's declared_service_invalid params.field, worded; an entry's field
// arrives as `entries.<n>.<field>`.
const DECLARED_INVALID_KEYS: Record<string, string> = {
  name: "ui.services.invalid_name",
  host: "ui.services.invalid_host",
  entries: "ui.services.invalid_entries",
  type: "ui.services.invalid_kind",
  port: "ui.services.invalid_port",
  scheme: "ui.services.invalid_scheme",
  protocol: "ui.services.invalid_protocol",
  path: "ui.services.invalid_path",
  share: "ui.services.invalid_share",
};

/** One entry row as the form holds it. */
interface EntryDraft {
  type: DeclaredEntryType;
  port: string;
  scheme: string;
  path: string;
  protocol: "tcp" | "udp";
  share: string;
}

const NEW_ENTRY: EntryDraft = {
  type: "web",
  port: "",
  scheme: "http",
  path: WEB_PATH,
  protocol: "tcp",
  share: "",
};

interface DeclareServiceModalProps {
  /** Called with the list the hub answered once the app is declared. */
  onDeclared: (view: ServiceListView) => void;
  onClose: () => void;
}

export function DeclareServiceModal({
  onDeclared,
  onClose,
}: DeclareServiceModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [description, setDescription] = useState("");
  const [entries, setEntries] = useState<EntryDraft[]>([NEW_ENTRY]);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const typeOptions: PickerOption[] = (
    Object.keys(TYPE_KEYS) as DeclaredEntryType[]
  ).map((type) => ({ id: type, name: t(TYPE_KEYS[type]) }));

  const patch = (index: number, change: Partial<EntryDraft>) =>
    setEntries((current) =>
      current.map((entry, at) =>
        at === index ? { ...entry, ...change } : entry,
      ),
    );

  const isReady =
    name.trim() !== "" &&
    host.trim() !== "" &&
    entries.length > 0 &&
    entries.every(isEntryReady) &&
    !isSaving;

  const declare = async () => {
    setIsSaving(true);
    setError(null);
    const request: DeclaredAppCreate = {
      name: name.trim(),
      host: host.trim(),
      description: description.trim(),
      entries: entries.map(toRequest),
    };
    try {
      onDeclared(
        await apiPost<ServiceListView>("/hub/service/declaration/add", request),
      );
    } catch (cause: unknown) {
      setError(describeDeclareError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <DialogFrame
      title={t("ui.services.declare")}
      icon="plus"
      onClose={onClose}
      foot={
        <>
          <button
            type="button"
            className="button button--ghost"
            onClick={onClose}
          >
            {t("ui.services.cancel")}
          </button>
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={!isReady}
            onClick={() => void declare()}
          >
            {isSaving ? <Spinner size={13} /> : <Icon name="check" size={14} />}
            {t("ui.services.save")}
          </button>
        </>
      }
    >
      <div className="field_grid">
        <label className="field">
          <span className="field_label">{t("ui.services.field_name")}</span>
          <input
            className="input"
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.services.field_host")}</span>
          <input
            className="input mono"
            value={host}
            spellCheck={false}
            onChange={(event) => setHost(event.target.value)}
          />
          <span className="field_hint">{t("ui.services.host_hint")}</span>
        </label>
      </div>
      <label className="field">
        <span className="field_label">
          {t("ui.services.field_description")}
        </span>
        <input
          className="input"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>

      <div className="declare_entries">
        <span className="section_label">{t("ui.services.entries")}</span>
        {entries.map((entry, index) => (
          <div key={index} className="declare_entry">
            <Picker
              options={typeOptions}
              value={entry.type}
              onChange={(type) =>
                patch(index, { type: type as DeclaredEntryType })
              }
              label={t("ui.services.entry_type")}
            />
            <label className="field declare_entry_port">
              <span className="field_label">{t("ui.services.field_port")}</span>
              <input
                className="input mono"
                value={entry.port}
                inputMode="numeric"
                placeholder={entry.type === "file" ? FILE_PORT : ""}
                onChange={(event) => patch(index, { port: event.target.value })}
              />
            </label>
            {entry.type === "web" && (
              <>
                <Picker
                  options={SCHEME_OPTIONS}
                  value={entry.scheme}
                  onChange={(scheme) => patch(index, { scheme })}
                  label={t("ui.services.field_scheme")}
                />
                <label className="field">
                  <span className="field_label">
                    {t("ui.services.entry_path")}
                  </span>
                  <input
                    className="input mono"
                    value={entry.path}
                    spellCheck={false}
                    onChange={(event) =>
                      patch(index, { path: event.target.value })
                    }
                  />
                </label>
              </>
            )}
            {entry.type === "port" && (
              <Picker
                options={PROTOCOL_OPTIONS}
                value={entry.protocol}
                onChange={(protocol) =>
                  patch(index, { protocol: protocol as "tcp" | "udp" })
                }
                label={t("ui.services.field_protocol")}
              />
            )}
            {entry.type === "file" && (
              <label className="field">
                <span className="field_label">
                  {t("ui.services.entry_share")}
                </span>
                <input
                  className="input mono"
                  value={entry.share}
                  spellCheck={false}
                  onChange={(event) =>
                    patch(index, { share: event.target.value })
                  }
                />
              </label>
            )}
            <button
              type="button"
              className="button button--ghost button--small declare_entry_remove"
              disabled={entries.length === 1}
              onClick={() =>
                setEntries((current) => current.filter((_, at) => at !== index))
              }
            >
              {t("ui.services.entry_remove")}
            </button>
          </div>
        ))}
        <div>
          <button
            type="button"
            className="button button--small"
            onClick={() => setEntries((current) => [...current, NEW_ENTRY])}
          >
            <Icon name="plus" size={13} />
            {t("ui.services.add_entry")}
          </button>
        </div>
      </div>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
    </DialogFrame>
  );
}

/** Whether a row holds what its type needs. */
function isEntryReady(entry: EntryDraft): boolean {
  const port = entry.port.trim();
  const isPortReady = port === "" ? entry.type === "file" : isValidPort(port);
  return isPortReady && (entry.type !== "file" || entry.share.trim() !== "");
}

/** A row as the declaration's entry. */
function toRequest(entry: EntryDraft): DeclaredEntryCreate {
  const port = entry.port.trim();
  return {
    type: entry.type,
    port: port === "" ? null : Number(port),
    scheme: entry.type === "web" ? entry.scheme : null,
    path: entry.type === "web" ? entry.path.trim() || WEB_PATH : null,
    protocol: entry.type === "port" ? entry.protocol : null,
    share: entry.type === "file" ? entry.share.trim() : null,
  };
}

/** Wording for a refused declaration, the field it names spelled out. */
function describeDeclareError(cause: unknown): string {
  if (cause instanceof ApiError && cause.code === "declared_service_invalid") {
    const field = String(cause.params.field ?? "");
    const parts = field.split(".");
    if (parts.length === 3 && parts[0] === "entries") {
      const key = DECLARED_INVALID_KEYS[parts[2] ?? ""];
      if (key !== undefined) {
        return t("ui.services.invalid_entry", {
          number: Number(parts[1]) + 1,
          problem: t(key),
        });
      }
    }
    const key = DECLARED_INVALID_KEYS[field];
    if (key !== undefined) {
      return t(key);
    }
  }
  return describeError(cause);
}

function isValidPort(value: string): boolean {
  if (!/^\d{1,5}$/.test(value)) {
    return false;
  }
  const port = Number(value);
  return port >= 1 && port <= 65535;
}
