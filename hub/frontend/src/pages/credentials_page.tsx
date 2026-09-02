import { useEffect, useState } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { PasswordInput } from "../components/password_input";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
import { formatTimeAgo } from "../format_duration";
import { PRIVATE_KEY_PLACEHOLDER } from "../private_key_placeholder";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import type {
  AiProviderKind,
  AiProviderModel,
  AiProviderView,
  AiProvidersResponse,
  KeyView,
  KeysResponse,
  PasswordView,
  PasswordsResponse,
  ServiceAccountView,
  ServiceAccountsResponse,
} from "../api_types";

import "./credentials_page.css";

/**
 * Everything the gateway holds on your behalf to reach other things: the SSH
 * keys and passwords it uses to manage devices, the accounts it presents to
 * services, and the AI endpoints and tokens it wires into devices' tools.
 *
 * Secrets travel one way. A key, password or token is typed once and never
 * shown again; everything on this page is metadata.
 */

const PROVIDER_KINDS: AiProviderKind[] = [
  "anthropic",
  "openai",
  "gemini",
  "custom",
];

// Placeholder per kind: the endpoint used when Base URL is left empty.
const PROVIDER_URL_PLACEHOLDERS: Record<AiProviderKind, string> = {
  anthropic: "https://api.anthropic.com",
  openai: "https://api.openai.com/v1",
  gemini: "https://generativelanguage.googleapis.com",
  custom: "https://relay.example.com/v1",
};

/**
 * What the kind actually decides: which protocol the hub speaks to this
 * endpoint. It is not about who runs it — a relay reached over Anthropic's
 * protocol is "Anthropic", whoever serves the models behind it. Choosing by
 * vendor instead of by protocol is how an endpoint ends up being spoken to
 * in a language it does not answer.
 */
const PROVIDER_KIND_LABELS: Record<AiProviderKind, string> = {
  anthropic: "Anthropic — /v1/messages",
  openai: "OpenAI — /v1/responses",
  gemini: "Gemini — generateContent",
  custom: "OpenAI-compatible — /chat/completions",
};

export function CredentialsPage() {
  return (
    <div className="page credentials_page">
      <header className="page_header">
        <div>
          <h1 className="page_title">Credentials</h1>
          <p className="page_subtitle">
            SSH keys and passwords for reaching devices, accounts for the
            services they use, and the AI endpoints handed to their tools.
          </p>
        </div>
      </header>

      <SshKeysSection />
      <PasswordsSection />
      <ServiceAccountsSection />
      <AiProvidersSection />
    </div>
  );
}

function SshKeysSection() {
  const resource = useApiResource<KeysResponse>("/credentials/ssh_keys");
  const [keys, setKeys] = useState<KeyView[]>([]);
  const [isAdding, setIsAdding] = useState(false);

  useEffect(() => {
    if (resource.data !== null) {
      setKeys(resource.data.keys);
    }
  }, [resource.data]);

  const handleAdded = (created: KeyView) => {
    setKeys((current) => [created, ...current]);
    setIsAdding(false);
  };

  const handleRenamed = (updated: KeyView) => {
    setKeys((current) =>
      current.map((key) => (key.id === updated.id ? updated : key)),
    );
  };

  const handleDeleted = (keyId: string) => {
    setKeys((current) => current.filter((key) => key.id !== keyId));
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>SSH keys</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            Add key
          </button>
        )}
      </div>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <AddKeyForm onAdded={handleAdded} onCancel={() => setIsAdding(false)} />
      )}

      {keys.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="key" size={22} />
          <span className="keys_empty_title">No keys yet</span>
          <span className="keys_empty_hint">
            Add a key here, then pick it when you configure a device over SSH.
          </span>
        </div>
      ) : (
        <div className="keys_list">
          {keys.map((key) => (
            <KeyCard
              key={key.id}
              value={key}
              onRenamed={handleRenamed}
              onDeleted={handleDeleted}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function PasswordsSection() {
  const resource = useApiResource<PasswordsResponse>("/credentials/passwords");
  const [passwords, setPasswords] = useState<PasswordView[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setPasswords(resource.data.passwords);
    }
  }, [resource.data]);

  const handleSaved = (saved: PasswordView) => {
    setPasswords((current) => {
      const exists = current.some((password) => password.id === saved.id);
      return exists
        ? current.map((password) =>
            password.id === saved.id ? saved : password,
          )
        : [saved, ...current];
    });
    setIsAdding(false);
    setEditingId(null);
  };

  const handleDeleted = (passwordId: string) => {
    setPasswords((current) =>
      current.filter((password) => password.id !== passwordId),
    );
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>Passwords</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            Add password
          </button>
        )}
      </div>
      <p className="field_hint">
        Used for a device&apos;s SSH login and for its sudo prompt.
      </p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <PasswordForm
          onSaved={handleSaved}
          onCancel={() => setIsAdding(false)}
        />
      )}

      {passwords.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="lock" size={22} />
          <span className="keys_empty_title">No passwords yet</span>
          <span className="keys_empty_hint">
            Add a password here, then pick it when a device signs in without a
            key.
          </span>
        </div>
      ) : (
        <div className="keys_list">
          {passwords.map((password) =>
            editingId === password.id ? (
              <PasswordForm
                key={password.id}
                initial={password}
                onSaved={handleSaved}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <PasswordCard
                key={password.id}
                value={password}
                onSaved={handleSaved}
                onEdit={() => setEditingId(password.id)}
                onDeleted={handleDeleted}
              />
            ),
          )}
        </div>
      )}
    </section>
  );
}

function ServiceAccountsSection() {
  const resource = useApiResource<ServiceAccountsResponse>(
    "/credentials/service_accounts",
  );
  const [accounts, setAccounts] = useState<ServiceAccountView[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setAccounts(resource.data.service_accounts);
    }
  }, [resource.data]);

  const handleSaved = (saved: ServiceAccountView) => {
    setAccounts((current) => {
      const exists = current.some((account) => account.id === saved.id);
      return exists
        ? current.map((account) => (account.id === saved.id ? saved : account))
        : [saved, ...current];
    });
    setIsAdding(false);
    setEditingId(null);
  };

  const handleDeleted = (accountId: string) => {
    setAccounts((current) =>
      current.filter((account) => account.id !== accountId),
    );
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>Service accounts</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            Add account
          </button>
        )}
      </div>
      <p className="field_hint">
        Used to sign in to declared services and to the Samba shares devices
        mount.
      </p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <ServiceAccountForm
          onSaved={handleSaved}
          onCancel={() => setIsAdding(false)}
        />
      )}

      {accounts.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="services" size={22} />
          <span className="keys_empty_title">No accounts yet</span>
          <span className="keys_empty_hint">
            Add a username and password once, instead of typing them into every
            service.
          </span>
        </div>
      ) : (
        <div className="keys_list">
          {accounts.map((account) =>
            editingId === account.id ? (
              <ServiceAccountForm
                key={account.id}
                initial={account}
                onSaved={handleSaved}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <ServiceAccountCard
                key={account.id}
                value={account}
                onSaved={handleSaved}
                onEdit={() => setEditingId(account.id)}
                onDeleted={handleDeleted}
              />
            ),
          )}
        </div>
      )}
    </section>
  );
}

function AiProvidersSection() {
  const resource = useApiResource<AiProvidersResponse>(
    "/credentials/ai_providers",
  );
  const [providers, setProviders] = useState<AiProviderView[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setProviders(resource.data.providers);
    }
  }, [resource.data]);

  const handleSaved = (saved: AiProviderView) => {
    setProviders((current) => {
      const exists = current.some((provider) => provider.id === saved.id);
      return exists
        ? current.map((provider) =>
            provider.id === saved.id ? saved : provider,
          )
        : [saved, ...current];
    });
    setIsAdding(false);
    setEditingId(null);
  };

  const handleDeleted = (providerId: string) => {
    setProviders((current) =>
      current.filter((provider) => provider.id !== providerId),
    );
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>AI providers</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            Add provider
          </button>
        )}
      </div>
      <p className="field_hint">
        Stored once here; Dev Setup points every machine&apos;s AI tools at
        them.
      </p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <ProviderForm
          onSaved={handleSaved}
          onCancel={() => setIsAdding(false)}
        />
      )}

      {providers.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="nodes" size={22} />
          <span className="keys_empty_title">No providers yet</span>
          <span className="keys_empty_hint">
            Add an API endpoint and token once, instead of pasting it into every
            machine.
          </span>
        </div>
      ) : (
        <div className="keys_list">
          {providers.map((provider) =>
            editingId === provider.id ? (
              <ProviderForm
                key={provider.id}
                initial={provider}
                onSaved={handleSaved}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <ProviderCard
                key={provider.id}
                value={provider}
                onEdit={() => setEditingId(provider.id)}
                onDeleted={handleDeleted}
              />
            ),
          )}
        </div>
      )}
    </section>
  );
}

interface ProviderFormProps {
  initial?: AiProviderView;
  onSaved: (provider: AiProviderView) => void;
  onCancel: () => void;
}

function ProviderForm({ initial, onSaved, onCancel }: ProviderFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [kind, setKind] = useState<AiProviderKind>(
    initial?.kind ?? "anthropic",
  );
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? "");
  const [modelsText, setModelsText] = useState(
    serializeModels(initial?.models ?? []),
  );
  const [apiKey, setApiKey] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEditing = initial !== undefined;
  const isReady =
    name.trim().length > 0 && (isEditing || apiKey.trim().length > 0);

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        kind,
        base_url: baseUrl.trim(),
        api_key: apiKey,
        models: parseModels(modelsText),
      };
      const saved = isEditing
        ? await apiPut<AiProviderView>(
            `/credentials/ai_providers/${initial.id}`,
            payload,
          )
        : await apiPost<AiProviderView>("/credentials/ai_providers", payload);
      onSaved(saved);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="keys_add">
      <div className="section_label">
        {isEditing ? `Edit ${initial.name}` : "New provider"}
      </div>
      <div className="credentials_form_row">
        <label className="field">
          <span className="field_label">Name</span>
          <input
            className="input"
            value={name}
            placeholder="Anthropic direct"
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">Kind</span>
          <select
            className="input"
            value={kind}
            onChange={(event) => setKind(event.target.value as AiProviderKind)}
          >
            {PROVIDER_KINDS.map((option) => (
              <option key={option} value={option}>
                {PROVIDER_KIND_LABELS[option]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="field">
        <span className="field_label">Base URL</span>
        <input
          className="input"
          value={baseUrl}
          placeholder={PROVIDER_URL_PLACEHOLDERS[kind]}
          spellCheck={false}
          onChange={(event) => setBaseUrl(event.target.value)}
        />
        <span className="field_hint">
          Leave empty for the service&apos;s default; set it for a relay. Match
          the kind to the protocol the endpoint speaks, not to whose models are
          behind it — DeepSeek&apos;s /anthropic endpoint is Anthropic.
        </span>
      </label>
      <label className="field">
        <span className="field_label">Model aliases</span>
        <textarea
          className="input"
          rows={3}
          spellCheck={false}
          placeholder={"claude-fable-5\nrelay-model-name = claude-opus-5"}
          value={modelsText}
          onChange={(event) => setModelsText(event.target.value)}
        />
        <span className="field_hint">
          One per line, real name first; add = alias when tools should see a
          different name. Devices are told to ask for the first one.
        </span>
      </label>
      <label className="field">
        <span className="field_label">API key</span>
        <PasswordInput value={apiKey} onChange={setApiKey} />
        {isEditing && (
          <span className="field_hint">
            Stored; type a new one to replace it.
          </span>
        )}
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="keys_add_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? "Saving…" : "Save provider"}
        </button>
      </div>
    </div>
  );
}

interface ProviderCardProps {
  value: AiProviderView;
  onEdit: () => void;
  onDeleted: (providerId: string) => void;
}

function ProviderCard({ value, onEdit, onDeleted }: ProviderCardProps) {
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const confirm = useConfirm();

  const handleDelete = () =>
    confirm.ask({
      title: `Delete ${value.name}`,
      body: "The provider and the key held for it are removed from this box.",
      confirmLabel: "Delete",
      onConfirm: () => void deleteProvider(),
    });

  const deleteProvider = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(`/credentials/ai_providers/${value.id}`);
      onDeleted(value.id);
    } catch (cause: unknown) {
      setError(describeError(cause));
      setIsBusy(false);
    }
  };

  return (
    <div className="key_card">
      <div className="key_card_head">
        <span className="credentials_provider_name">{value.name}</span>
        <span className="key_card_type">{value.kind}</span>
      </div>

      <div className="key_card_fingerprint">
        {value.base_url.length > 0 ? value.base_url : "default endpoint"}
      </div>

      <div className="key_card_meta">
        <span
          className={`key_card_tag ${
            value.has_api_key && value.is_enabled ? "key_card_tag--used" : ""
          }`}
        >
          <Icon name="lock" size={11} />
          {!value.has_api_key
            ? "no key"
            : value.is_enabled
              ? "serving"
              : "unused"}
        </span>
        {value.created_at.length > 0 && (
          <span className="key_card_added">
            added {formatTimeAgo(value.created_at)}
          </span>
        )}
      </div>

      {error !== null && <span className="field_error">{error}</span>}

      <div className="key_card_actions">
        <button
          type="button"
          className="button button--ghost button--small"
          disabled={isBusy}
          onClick={onEdit}
        >
          <Icon name="edit" size={13} />
          Edit
        </button>
        <button
          type="button"
          className="button button--ghost button--small button--danger"
          disabled={isBusy}
          onClick={handleDelete}
        >
          <Icon name="trash" size={13} />
          Delete
        </button>
      </div>
      {confirm.modal}
    </div>
  );
}

interface AddKeyFormProps {
  onAdded: (key: KeyView) => void;
  onCancel: () => void;
}

function AddKeyForm({ onAdded, onCancel }: AddKeyFormProps) {
  const [name, setName] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isReady = name.trim().length > 0 && privateKey.trim().length > 0;

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const created = await apiPost<KeyView>("/credentials/ssh_keys", {
        name: name.trim(),
        private_key: privateKey,
        passphrase: passphrase.length > 0 ? passphrase : null,
      });
      onAdded(created);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="keys_add">
      <div className="section_label">New key</div>
      <label className="field">
        <span className="field_label">Name</span>
        <input
          className="input"
          value={name}
          placeholder="work laptop"
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="field">
        <span className="field_label">Private key</span>
        <textarea
          className="input input--key"
          value={privateKey}
          spellCheck={false}
          autoComplete="off"
          rows={8}
          placeholder={PRIVATE_KEY_PLACEHOLDER}
          onChange={(event) => setPrivateKey(event.target.value)}
        />
        <span className="field_hint">
          Stored on the gateway readable only by root, and never shown again.
        </span>
      </label>
      <label className="field">
        <span className="field_label">Key passphrase</span>
        <PasswordInput value={passphrase} onChange={setPassphrase} />
        <span className="field_hint">
          Only if the key is encrypted. Leave blank otherwise.
        </span>
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="keys_add_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? "Saving…" : "Save key"}
        </button>
      </div>
    </div>
  );
}

interface KeyCardProps {
  value: KeyView;
  onRenamed: (key: KeyView) => void;
  onDeleted: (keyId: string) => void;
}

function KeyCard({ value, onRenamed, onDeleted }: KeyCardProps) {
  const [isEditingName, setIsEditingName] = useState(false);
  const confirm = useConfirm();
  const [draftName, setDraftName] = useState(value.name);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const handleRename = async () => {
    if (draftName.trim().length === 0 || draftName.trim() === value.name) {
      setIsEditingName(false);
      setDraftName(value.name);
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const updated = await apiPut<KeyView>(
        `/credentials/ssh_keys/${value.id}`,
        {
          name: draftName.trim(),
        },
      );
      onRenamed(updated);
      setIsEditingName(false);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleDelete = () =>
    confirm.ask({
      title: `Delete ${value.name}`,
      body:
        value.device_count > 0
          ? `${value.device_count} device(s) authenticate with this key and ` +
            "fall back to password authentication once it is gone."
          : "The private key is deleted from this box.",
      confirmLabel: "Delete",
      onConfirm: () => void deleteKey(),
    });

  const deleteKey = async () => {
    const inUse = value.device_count > 0;
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(
        `/credentials/ssh_keys/${value.id}${inUse ? "?force=true" : ""}`,
      );
      onDeleted(value.id);
    } catch (cause: unknown) {
      setError(describeError(cause));
      setIsBusy(false);
    }
  };

  return (
    <div className="key_card">
      <div className="key_card_head">
        {isEditingName ? (
          <input
            className="input key_card_name_input"
            value={draftName}
            autoFocus
            onChange={(event) => setDraftName(event.target.value)}
            onBlur={() => void handleRename()}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleRename();
              } else if (event.key === "Escape") {
                setIsEditingName(false);
                setDraftName(value.name);
              }
            }}
          />
        ) : (
          <button
            type="button"
            className="key_card_name"
            onClick={() => setIsEditingName(true)}
            title="Rename"
          >
            {value.name}
            <Icon name="edit" size={12} />
          </button>
        )}
        <span className="key_card_type">{value.key_type}</span>
      </div>

      <div className="key_card_fingerprint">{value.fingerprint}</div>

      <div className="key_card_meta">
        {value.has_passphrase && (
          <span className="key_card_tag">
            <Icon name="lock" size={11} />
            encrypted
          </span>
        )}
        <span
          className={`key_card_tag ${
            value.device_count > 0 ? "key_card_tag--used" : ""
          }`}
        >
          {value.device_count === 0
            ? "unused"
            : `${value.device_count} device${value.device_count === 1 ? "" : "s"}`}
        </span>
        {value.created_at.length > 0 && (
          <span className="key_card_added">
            added {formatTimeAgo(value.created_at)}
          </span>
        )}
      </div>

      {error !== null && <span className="field_error">{error}</span>}

      <div className="key_card_actions">
        <button
          type="button"
          className="button button--ghost button--small button--danger"
          disabled={isBusy}
          onClick={handleDelete}
        >
          <Icon name="trash" size={13} />
          Delete
        </button>
      </div>
      {confirm.modal}
    </div>
  );
}

interface PasswordFormProps {
  initial?: PasswordView;
  onSaved: (password: PasswordView) => void;
  onCancel: () => void;
}

function PasswordForm({ initial, onSaved, onCancel }: PasswordFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [password, setPassword] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEditing = initial !== undefined;
  const isReady = name.trim().length > 0 && (isEditing || password.length > 0);

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const payload = { name: name.trim(), password };
      const saved = isEditing
        ? await apiPut<PasswordView>(
            `/credentials/passwords/${initial.id}`,
            payload,
          )
        : await apiPost<PasswordView>("/credentials/passwords", payload);
      onSaved(saved);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="keys_add">
      <div className="section_label">
        {isEditing ? `Edit ${initial.name}` : "New password"}
      </div>
      <label className="field">
        <span className="field_label">Name</span>
        <input
          className="input"
          value={name}
          placeholder="lab machines"
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="field">
        <span className="field_label">Password</span>
        <PasswordInput value={password} onChange={setPassword} />
        <span className="field_hint">
          {isEditing
            ? "Stored; type a new one to replace it."
            : "Stored sealed on the gateway, and never shown again."}
        </span>
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="keys_add_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? "Saving…" : "Save password"}
        </button>
      </div>
    </div>
  );
}

interface PasswordCardProps {
  value: PasswordView;
  onSaved: (password: PasswordView) => void;
  onEdit: () => void;
  onDeleted: (passwordId: string) => void;
}

function PasswordCard({
  value,
  onSaved,
  onEdit,
  onDeleted,
}: PasswordCardProps) {
  const [isEditingName, setIsEditingName] = useState(false);
  const confirm = useConfirm();
  const [draftName, setDraftName] = useState(value.name);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const handleRename = async () => {
    if (draftName.trim().length === 0 || draftName.trim() === value.name) {
      setIsEditingName(false);
      setDraftName(value.name);
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const updated = await apiPut<PasswordView>(
        `/credentials/passwords/${value.id}`,
        { name: draftName.trim() },
      );
      onSaved(updated);
      setIsEditingName(false);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleDelete = () =>
    confirm.ask({
      title: `Delete ${value.name}`,
      body:
        value.device_count > 0
          ? `${value.device_count} device(s) sign in with this password and ` +
            "are left without one once it is gone."
          : "The password is deleted from this box.",
      confirmLabel: "Delete",
      onConfirm: () => void deletePassword(),
    });

  const deletePassword = async () => {
    const inUse = value.device_count > 0;
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(
        `/credentials/passwords/${value.id}${inUse ? "?force=true" : ""}`,
      );
      onDeleted(value.id);
    } catch (cause: unknown) {
      setError(describeError(cause));
      setIsBusy(false);
    }
  };

  return (
    <div className="key_card">
      <div className="key_card_head">
        {isEditingName ? (
          <input
            className="input key_card_name_input"
            value={draftName}
            autoFocus
            onChange={(event) => setDraftName(event.target.value)}
            onBlur={() => void handleRename()}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleRename();
              } else if (event.key === "Escape") {
                setIsEditingName(false);
                setDraftName(value.name);
              }
            }}
          />
        ) : (
          <button
            type="button"
            className="key_card_name"
            onClick={() => setIsEditingName(true)}
            title="Rename"
          >
            {value.name}
            <Icon name="edit" size={12} />
          </button>
        )}
      </div>

      <div className="key_card_meta">
        <span
          className={`key_card_tag ${
            value.device_count > 0 ? "key_card_tag--used" : ""
          }`}
        >
          {value.device_count === 0
            ? "unused"
            : `${value.device_count} device${value.device_count === 1 ? "" : "s"}`}
        </span>
        {value.created_at.length > 0 && (
          <span className="key_card_added">
            added {formatTimeAgo(value.created_at)}
          </span>
        )}
      </div>

      {error !== null && <span className="field_error">{error}</span>}

      <div className="key_card_actions">
        <button
          type="button"
          className="button button--ghost button--small"
          disabled={isBusy}
          onClick={onEdit}
        >
          <Icon name="edit" size={13} />
          Edit
        </button>
        <button
          type="button"
          className="button button--ghost button--small button--danger"
          disabled={isBusy}
          onClick={handleDelete}
        >
          <Icon name="trash" size={13} />
          Delete
        </button>
      </div>
      {confirm.modal}
    </div>
  );
}

interface ServiceAccountFormProps {
  initial?: ServiceAccountView;
  onSaved: (account: ServiceAccountView) => void;
  onCancel: () => void;
}

function ServiceAccountForm({
  initial,
  onSaved,
  onCancel,
}: ServiceAccountFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [username, setUsername] = useState(initial?.username ?? "");
  const [password, setPassword] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEditing = initial !== undefined;
  const isReady =
    name.trim().length > 0 &&
    username.trim().length > 0 &&
    (isEditing || password.length > 0);

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        username: username.trim(),
        password,
      };
      const saved = isEditing
        ? await apiPut<ServiceAccountView>(
            `/credentials/service_accounts/${initial.id}`,
            payload,
          )
        : await apiPost<ServiceAccountView>(
            "/credentials/service_accounts",
            payload,
          );
      onSaved(saved);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="keys_add">
      <div className="section_label">
        {isEditing ? `Edit ${initial.name}` : "New service account"}
      </div>
      <div className="credentials_form_row">
        <label className="field">
          <span className="field_label">Name</span>
          <input
            className="input"
            value={name}
            placeholder="NAS backup"
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">Username</span>
          <input
            className="input"
            value={username}
            placeholder="backup"
            spellCheck={false}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
      </div>
      <label className="field">
        <span className="field_label">Password</span>
        <PasswordInput value={password} onChange={setPassword} />
        <span className="field_hint">
          {isEditing
            ? "Stored; type a new one to replace it."
            : "Stored sealed on the gateway, and never shown again."}
        </span>
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="keys_add_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? "Saving…" : "Save account"}
        </button>
      </div>
    </div>
  );
}

interface ServiceAccountCardProps {
  value: ServiceAccountView;
  onSaved: (account: ServiceAccountView) => void;
  onEdit: () => void;
  onDeleted: (accountId: string) => void;
}

function ServiceAccountCard({
  value,
  onSaved,
  onEdit,
  onDeleted,
}: ServiceAccountCardProps) {
  const [isEditingName, setIsEditingName] = useState(false);
  const confirm = useConfirm();
  const [draftName, setDraftName] = useState(value.name);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const handleRename = async () => {
    if (draftName.trim().length === 0 || draftName.trim() === value.name) {
      setIsEditingName(false);
      setDraftName(value.name);
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const updated = await apiPut<ServiceAccountView>(
        `/credentials/service_accounts/${value.id}`,
        { name: draftName.trim() },
      );
      onSaved(updated);
      setIsEditingName(false);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleDelete = () =>
    confirm.ask({
      title: `Delete ${value.name}`,
      body:
        value.service_count > 0
          ? `${value.service_count} service(s) sign in with this account and ` +
            "are left without one once it is gone."
          : "The account and its password are deleted from this box.",
      confirmLabel: "Delete",
      onConfirm: () => void deleteAccount(),
    });

  const deleteAccount = async () => {
    const inUse = value.service_count > 0;
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(
        `/credentials/service_accounts/${value.id}${inUse ? "?force=true" : ""}`,
      );
      onDeleted(value.id);
    } catch (cause: unknown) {
      setError(describeError(cause));
      setIsBusy(false);
    }
  };

  return (
    <div className="key_card">
      <div className="key_card_head">
        {isEditingName ? (
          <input
            className="input key_card_name_input"
            value={draftName}
            autoFocus
            onChange={(event) => setDraftName(event.target.value)}
            onBlur={() => void handleRename()}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleRename();
              } else if (event.key === "Escape") {
                setIsEditingName(false);
                setDraftName(value.name);
              }
            }}
          />
        ) : (
          <button
            type="button"
            className="key_card_name"
            onClick={() => setIsEditingName(true)}
            title="Rename"
          >
            {value.name}
            <Icon name="edit" size={12} />
          </button>
        )}
      </div>

      <div className="key_card_fingerprint">{value.username}</div>

      <div className="key_card_meta">
        <span
          className={`key_card_tag ${
            value.service_count > 0 ? "key_card_tag--used" : ""
          }`}
        >
          {value.service_count === 0
            ? "unused"
            : `${value.service_count} service${value.service_count === 1 ? "" : "s"}`}
        </span>
        {value.created_at.length > 0 && (
          <span className="key_card_added">
            added {formatTimeAgo(value.created_at)}
          </span>
        )}
      </div>

      {error !== null && <span className="field_error">{error}</span>}

      <div className="key_card_actions">
        <button
          type="button"
          className="button button--ghost button--small"
          disabled={isBusy}
          onClick={onEdit}
        >
          <Icon name="edit" size={13} />
          Edit
        </button>
        <button
          type="button"
          className="button button--ghost button--small button--danger"
          disabled={isBusy}
          onClick={handleDelete}
        >
          <Icon name="trash" size={13} />
          Delete
        </button>
      </div>
      {confirm.modal}
    </div>
  );
}

function serializeModels(models: AiProviderModel[]): string {
  return models
    .map((model) =>
      model.alias.length > 0 && model.alias !== model.name
        ? `${model.name} = ${model.alias}`
        : model.name,
    )
    .join("\n");
}

function parseModels(text: string): AiProviderModel[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const [name = "", alias = ""] = line
        .split("=")
        .map((part) => part.trim());
      return { name, alias };
    })
    .filter((model) => model.name.length > 0);
}
