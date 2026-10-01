import { useState } from "react";

import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { Picker } from "./picker";
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
  ssh_key: "/hub/credential/ssh_key",
  login: "/hub/credential/login",
  token: "/hub/credential/token",
};

// The vault's one file: a credential stored anywhere in the panel writes it,
// and every open picker reads its list again.
const VAULT_CONFIG_KEY = "credentials/vault.json";

const VAULT_INVALIDATE_ON: HubEventMatch[] = [
  { type: HUB_EVENT_CONFIG, key: VAULT_CONFIG_KEY },
];

/** One row of the list: what the vault holds, as this control shows it. */
interface VaultEntry {
  id: string;
  name: string;
  detail: string;
}

/** Whichever list the picked kind's route answers with. */
type VaultListResponse = KeysResponse | LoginsResponse | TokensResponse;

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

  const entries = mergeEntries(toEntries(resource.data), storedEntries);
  const keys = KIND_KEYS[kind];

  const handleAdded = (entry: VaultEntry) => {
    setStoredEntries((current) => [entry, ...current]);
    resource.reload();
  };

  return (
    <Picker
      options={entries}
      value={value}
      onChange={onChange}
      label={label}
      hint={hint}
      error={resource.error}
      placeholder={t(keys.none)}
      emptyText={t(resource.isLoading ? "ui.vault.loading" : keys.empty)}
      isDisabled={isDisabled}
      addRow={{
        label: t(keys.add),
        renderForm: (finish) => (
          <VaultAddForm
            kind={kind}
            onAdded={(entry) => {
              handleAdded(entry);
              finish(entry.id);
            }}
            onCancel={() => finish(null)}
          />
        ),
      }}
    />
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

/** Store one credential of this kind, and return the row it becomes. */
async function createEntry(
  kind: VaultKind,
  name: string,
  secret: string,
): Promise<VaultEntry> {
  if (kind === "ssh_key") {
    return toKeyEntry(
      await apiPost<KeyView>(`${VAULT_PATHS.ssh_key}/add`, {
        name,
        private_key: secret,
        passphrase: null,
      }),
    );
  }
  if (kind === "login") {
    return toLoginEntry(
      await apiPost<LoginView>(`${VAULT_PATHS.login}/add`, {
        name,
        username: null,
        password: secret, // scan: allow
      }),
    );
  }
  return toTokenEntry(
    await apiPost<TokenView>(`${VAULT_PATHS.token}/add`, {
      name,
      value: secret,
    }),
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

/** Enough of the fingerprint to tell two keys apart without filling the row. */
function shortFingerprint(fingerprint: string): string {
  const body = fingerprint.replace(/^SHA256:/, "");
  return body.length > 12 ? `${body.slice(0, 12)}…` : body;
}

/** Enough of the id to tell two records of one name apart. */
function maskedId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}
