import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { privateKeyPlaceholder } from "../private_key_placeholder";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_CONFIG } from "../use_hub_events";
import type { HubEventMatch } from "../use_hub_events";
import type {
  KeyView,
  KeysResponse,
  LoginView,
  LoginsResponse,
  TokenView,
  TokensResponse,
} from "../api_types";

import "./vault_picker.css";

/**
 * The one control that picks a credential the vault holds.
 *
 * Every screen that references a stored key, login or token uses this, so the
 * rows read the same everywhere and storing a new credential happens where it
 * is needed rather than on another page. The list is the vault's entries and
 * the row after them stores one more; nothing here reads a secret back.
 */

/** What one kind of vault entry is called on this control, as catalog keys. */
interface VaultKindKeys {
  empty: string;
  none: string;
  add: string;
  namePlaceholder: string;
  valueLabel: string;
  valueHint: string;
  save: string;
}

const KIND_KEYS: Record<VaultKind, VaultKindKeys> = {
  ssh_key: {
    empty: "ui.vault.key_empty",
    none: "ui.vault.key_none",
    add: "ui.vault.key_add",
    namePlaceholder: "ui.vault.key_name_placeholder",
    valueLabel: "ui.vault.key_value_label",
    valueHint: "ui.vault.key_value_hint",
    save: "ui.vault.key_save",
  },
  login: {
    empty: "ui.vault.login_empty",
    none: "ui.vault.login_none",
    add: "ui.vault.login_add",
    namePlaceholder: "ui.vault.login_name_placeholder",
    valueLabel: "ui.vault.login_value_label",
    valueHint: "ui.vault.login_value_hint",
    save: "ui.vault.login_save",
  },
  token: {
    empty: "ui.vault.token_empty",
    none: "ui.vault.token_none",
    add: "ui.vault.token_add",
    namePlaceholder: "ui.vault.token_name_placeholder",
    valueLabel: "ui.vault.token_value_label",
    valueHint: "ui.vault.token_value_hint",
    save: "ui.vault.token_save",
  },
};

/** Which kind of credential a picker lists. */
export type VaultKind = "ssh_key" | "login" | "token";

const VAULT_PATHS: Record<VaultKind, string> = {
  ssh_key: "/credentials/ssh_keys",
  login: "/credentials/logins",
  token: "/credentials/tokens",
};

// The vault's one file: a credential stored anywhere in the panel writes it,
// and every open picker reads its list again.
const VAULT_CONFIG_KEY = "credentials/vault.json";

const VAULT_INVALIDATE_ON: HubEventMatch[] = [
  { type: HUB_EVENT_CONFIG, key: VAULT_CONFIG_KEY },
];

// How the open list is sized: five rows at once, the add row among them,
// and the rest reached by scrolling.
const VISIBLE_ROW_COUNT = 5;
const ROW_HEIGHT_PX = 34;
const PANEL_GAP_PX = 4;
const PANEL_EDGE_PX = 12;
const FORM_HEIGHT_PX = 260;

/** One row of the list: what the vault holds, as this control shows it. */
interface VaultEntry {
  id: string;
  name: string;
  detail: string;
}

/** Whichever list the picked kind's route answers with. */
type VaultListResponse = KeysResponse | LoginsResponse | TokensResponse;

/** Where the open panel sits, measured against the viewport. */
interface PanelPlacement {
  left: number;
  width: number;
  top: number | null;
  bottom: number | null;
  available: number;
}

interface VaultPickerProps {
  kind: VaultKind;
  value: string | null;
  onChange: (id: string | null) => void;
  label: string;
  /** The line under the control, where the screen has one to say. */
  hint?: string;
  isDisabled?: boolean;
}

export function VaultPicker({
  kind,
  value,
  onChange,
  label,
  hint,
  isDisabled,
}: VaultPickerProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<VaultListResponse>(VAULT_PATHS[kind], {
    invalidateOn: VAULT_INVALIDATE_ON,
  });
  const [storedEntries, setStoredEntries] = useState<VaultEntry[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [placement, setPlacement] = useState<PanelPlacement | null>(null);
  const controlRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const escapeRef = useRef<() => void>(() => {});
  const listId = useId();

  const entries = mergeEntries(toEntries(resource.data), storedEntries);
  const selected = entries.find((entry) => entry.id === value) ?? null;
  const rowCount = entries.length + 1;
  const keys = KIND_KEYS[kind];

  const close = useCallback(() => {
    setIsOpen(false);
    setIsAdding(false);
    controlRef.current?.focus();
  }, []);

  const measure = useCallback(() => {
    const control = controlRef.current;
    if (control === null) {
      return;
    }
    const rect = control.getBoundingClientRect();
    const below =
      window.innerHeight - rect.bottom - PANEL_GAP_PX - PANEL_EDGE_PX;
    const above = rect.top - PANEL_GAP_PX - PANEL_EDGE_PX;
    const wanted = isAdding
      ? FORM_HEIGHT_PX
      : Math.min(rowCount, VISIBLE_ROW_COUNT) * ROW_HEIGHT_PX;
    const isFlipped = below < wanted && above > below;
    setPlacement({
      left: rect.left,
      width: rect.width,
      top: isFlipped ? null : rect.bottom + PANEL_GAP_PX,
      bottom: isFlipped ? window.innerHeight - rect.top + PANEL_GAP_PX : null,
      available: Math.max(ROW_HEIGHT_PX * 2, isFlipped ? above : below),
    });
  }, [isAdding, rowCount]);

  useLayoutEffect(() => {
    if (!isOpen) {
      return;
    }
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [isOpen, measure]);

  useEffect(() => {
    escapeRef.current = () => {
      if (isAdding) {
        setIsAdding(false);
        return;
      }
      close();
    };
  });

  // Escape belongs to the open list before it belongs to whatever holds it,
  // so a modal hosting a picker stays open.
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handler = () => escapeRef.current();
    escapeHandlers.push(handler);
    return () => {
      const at = escapeHandlers.indexOf(handler);
      if (at >= 0) {
        escapeHandlers.splice(at, 1);
      }
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) {
        return;
      }
      if (
        panelRef.current?.contains(event.target) === true ||
        controlRef.current?.contains(event.target) === true
      ) {
        return;
      }
      setIsOpen(false);
      setIsAdding(false);
    };
    document.addEventListener("pointerdown", handlePointerDown, true);
    return () =>
      document.removeEventListener("pointerdown", handlePointerDown, true);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || isAdding) {
      return;
    }
    listRef.current?.children.item(activeIndex)?.scrollIntoView({
      block: "nearest",
    });
  }, [isOpen, isAdding, activeIndex]);

  const handleOpen = () => {
    const at = entries.findIndex((entry) => entry.id === value);
    setActiveIndex(at >= 0 ? at : 0);
    setIsOpen(true);
  };

  const handlePick = (id: string) => {
    onChange(id);
    close();
  };

  const handleAdded = (entry: VaultEntry) => {
    setStoredEntries((current) => [entry, ...current]);
    resource.reload();
    onChange(entry.id);
    close();
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen) {
        handleOpen();
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((index) => (index + step + rowCount) % rowCount);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      if (!isOpen || isAdding) {
        return;
      }
      event.preventDefault();
      const picked = entries[activeIndex];
      if (picked === undefined) {
        setIsAdding(true);
        return;
      }
      handlePick(picked.id);
      return;
    }
    if (event.key === "Tab" && isOpen) {
      setIsOpen(false);
      setIsAdding(false);
    }
  };

  return (
    <div className="field vault_picker">
      <span className="field_label">{label}</span>
      <button
        type="button"
        ref={controlRef}
        className="select vault_picker_control"
        disabled={isDisabled === true}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={listId}
        onClick={() => (isOpen ? close() : handleOpen())}
        onKeyDown={handleKeyDown}
      >
        <span
          className={`vault_picker_value ${
            selected === null ? "vault_picker_value--none" : ""
          }`}
        >
          {selected === null ? t(keys.none) : entryLabel(selected)}
        </span>
      </button>
      {hint !== undefined && <span className="field_hint">{hint}</span>}
      {resource.error !== null && (
        <span className="field_error">{resource.error}</span>
      )}
      {isOpen &&
        placement !== null &&
        createPortal(
          <div
            className="vault_picker_panel"
            ref={panelRef}
            style={{
              left: placement.left,
              width: placement.width,
              top: placement.top ?? undefined,
              bottom: placement.bottom ?? undefined,
              maxHeight: placement.available,
            }}
          >
            {isAdding ? (
              <VaultAddForm
                kind={kind}
                onAdded={handleAdded}
                onCancel={() => setIsAdding(false)}
              />
            ) : (
              <>
                {entries.length === 0 && (
                  <span className="vault_picker_empty">
                    {t(resource.isLoading ? "ui.vault.loading" : keys.empty)}
                  </span>
                )}
                <div
                  className="vault_picker_list"
                  id={listId}
                  role="listbox"
                  ref={listRef}
                  aria-label={label}
                  style={{
                    maxHeight: Math.min(
                      VISIBLE_ROW_COUNT * ROW_HEIGHT_PX,
                      placement.available,
                    ),
                  }}
                >
                  {entries.map((entry, index) => (
                    <button
                      key={entry.id}
                      type="button"
                      role="option"
                      aria-selected={entry.id === value}
                      className={`vault_picker_row ${
                        index === activeIndex ? "vault_picker_row--active" : ""
                      }`}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => handlePick(entry.id)}
                    >
                      <span className="vault_picker_row_name">
                        {entry.name}
                      </span>
                      {entry.detail.length > 0 && (
                        <span className="vault_picker_row_detail">
                          {entry.detail}
                        </span>
                      )}
                    </button>
                  ))}
                  <button
                    type="button"
                    role="option"
                    aria-selected={false}
                    className={`vault_picker_row vault_picker_row--add ${
                      activeIndex === entries.length
                        ? "vault_picker_row--active"
                        : ""
                    }`}
                    onMouseEnter={() => setActiveIndex(entries.length)}
                    onClick={() => setIsAdding(true)}
                  >
                    <Icon name="plus" size={13} />
                    {t(keys.add)}
                  </button>
                </div>
              </>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}

interface VaultAddFormProps {
  kind: VaultKind;
  onAdded: (entry: VaultEntry) => void;
  onCancel: () => void;
}

function VaultAddForm({ kind, onAdded, onCancel }: VaultAddFormProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const keys = KIND_KEYS[kind];
  const isReady = name.trim().length > 0 && secret.trim().length > 0;

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      onAdded(await createEntry(kind, name.trim(), secret));
    } catch (cause: unknown) {
      setError(describeError(cause));
      setIsSaving(false);
    }
  };

  return (
    <div className="vault_picker_form">
      <label className="field">
        <span className="field_label">{t("ui.vault.name")}</span>
        <input
          className="input"
          value={name}
          placeholder={t(keys.namePlaceholder)}
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="field">
        <span className="field_label">{t(keys.valueLabel)}</span>
        {kind === "ssh_key" ? (
          <textarea
            className="input input--key vault_picker_key"
            value={secret}
            spellCheck={false}
            autoComplete="off"
            rows={5}
            placeholder={privateKeyPlaceholder()}
            onChange={(event) => setSecret(event.target.value)}
          />
        ) : (
          <PasswordInput value={secret} onChange={setSecret} />
        )}
        <span className="field_hint">{t(keys.valueHint)}</span>
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="vault_picker_form_actions">
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={onCancel}
        >
          {t("ui.vault.cancel")}
        </button>
        <button
          type="button"
          className="button button--primary button--small"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={13} />
          {isSaving ? t("ui.vault.saving") : t(keys.save)}
        </button>
      </div>
    </div>
  );
}

// The open picker takes Escape before whatever holds it does: one listener
// serves every picker, and it stands before a modal's own.
const escapeHandlers: Array<() => void> = [];

if (typeof window !== "undefined") {
  window.addEventListener("keydown", takeEscape, true);
}

function takeEscape(event: KeyboardEvent): void {
  const handler = escapeHandlers.at(-1);
  if (event.key !== "Escape" || handler === undefined) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  handler();
}

/** Store one credential of this kind, and return the row it becomes. */
async function createEntry(
  kind: VaultKind,
  name: string,
  secret: string,
): Promise<VaultEntry> {
  if (kind === "ssh_key") {
    return toKeyEntry(
      await apiPost<KeyView>(VAULT_PATHS.ssh_key, {
        name,
        private_key: secret,
        passphrase: null,
      }),
    );
  }
  if (kind === "login") {
    return toLoginEntry(
      await apiPost<LoginView>(VAULT_PATHS.login, {
        name,
        username: null,
        password: secret, // scan: allow
      }),
    );
  }
  return toTokenEntry(
    await apiPost<TokenView>(VAULT_PATHS.token, { name, value: secret }),
  );
}

/** The rows of whichever list came back. */
function toEntries(data: VaultListResponse | null): VaultEntry[] {
  if (data === null) {
    return [];
  }
  if ("keys" in data) {
    return data.keys.map(toKeyEntry);
  }
  if ("logins" in data) {
    return data.logins.map(toLoginEntry);
  }
  return data.tokens.map(toTokenEntry);
}

/** The listed rows, with anything stored here that the list has not caught up
 * with in front of them. */
function mergeEntries(
  listed: VaultEntry[],
  stored: VaultEntry[],
): VaultEntry[] {
  const missing = stored.filter(
    (entry) => !listed.some((row) => row.id === entry.id),
  );
  return [...missing, ...listed];
}

function toKeyEntry(key: KeyView): VaultEntry {
  return {
    id: key.id,
    name: key.name,
    detail: shortFingerprint(key.fingerprint),
  };
}

function toLoginEntry(login: LoginView): VaultEntry {
  return {
    id: login.id,
    name: login.name,
    detail: login.username ?? maskedId(login.id),
  };
}

function toTokenEntry(token: TokenView): VaultEntry {
  return { id: token.id, name: token.name, detail: maskedId(token.id) };
}

/** One row's whole line: the name, and what tells two of them apart. */
function entryLabel(entry: VaultEntry): string {
  return entry.detail.length === 0
    ? entry.name
    : `${entry.name} · ${entry.detail}`;
}

/** Enough of the fingerprint to tell two keys apart without filling the row. */
function shortFingerprint(fingerprint: string): string {
  const body = fingerprint.replace(/^SHA256:/, "");
  return body.length > 12 ? `${body.slice(0, 12)}…` : body;
}

/** Enough of the id to tell two records of one name apart. */
function maskedId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}
