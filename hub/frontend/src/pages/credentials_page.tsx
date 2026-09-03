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
  KeyView,
  KeysResponse,
  LoginView,
  LoginsResponse,
  TokenView,
  TokensResponse,
} from "../api_types";

import "./credentials_page.css";

/**
 * Everything the gateway holds on your behalf to reach other things: the SSH
 * keys and logins it uses to manage devices and sign in to services, the
 * tokens it presents to APIs, and the AI endpoints it wires into devices'
 * tools.
 *
 * Secrets travel one way. A key, password or token is typed once and never
 * shown again; everything on this page is metadata.
 */

const LOGINS_PATH = "/credentials/logins";
const TOKENS_PATH = "/credentials/tokens";
export function CredentialsPage() {
  return (
    <div className="page credentials_page">
      <header className="page_header">
        <div>
          <h1 className="page_title">Credentials</h1>
          <p className="page_subtitle">
            SSH keys and logins for reaching devices and services, tokens for
            the APIs the box speaks to, and the AI endpoints handed to
            devices&apos; tools.
          </p>
        </div>
      </header>

      <SshKeysSection />
      <LoginsSection />
      <TokensSection />
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
    resource.reload();
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

function LoginsSection() {
  const resource = useApiResource<LoginsResponse>(LOGINS_PATH);
  const [logins, setLogins] = useState<LoginView[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setLogins(resource.data.logins);
    }
  }, [resource.data]);

  const handleSaved = (saved: LoginView) => {
    setLogins((current) => {
      const exists = current.some((login) => login.id === saved.id);
      return exists
        ? current.map((login) => (login.id === saved.id ? saved : login))
        : [saved, ...current];
    });
    setIsAdding(false);
    setEditingId(null);
  };

  const handleDeleted = (loginId: string) => {
    setLogins((current) => current.filter((login) => login.id !== loginId));
    resource.reload();
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>Logins</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            Add login
          </button>
        )}
      </div>
      <p className="field_hint">
        A username and password pair, or a bare password. Used for a
        device&apos;s SSH login and sudo prompt, and to sign in to declared
        services.
      </p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <LoginForm onSaved={handleSaved} onCancel={() => setIsAdding(false)} />
      )}

      {logins.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="lock" size={22} />
          <span className="keys_empty_title">No logins yet</span>
          <span className="keys_empty_hint">
            Add a login here, then pick it wherever a device or service signs in
            with a password.
          </span>
        </div>
      ) : (
        <div className="keys_list">
          {logins.map((login) =>
            editingId === login.id ? (
              <LoginForm
                key={login.id}
                initial={login}
                onSaved={handleSaved}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <LoginCard
                key={login.id}
                value={login}
                onSaved={handleSaved}
                onEdit={() => setEditingId(login.id)}
                onDeleted={handleDeleted}
              />
            ),
          )}
        </div>
      )}
    </section>
  );
}

function TokensSection() {
  const resource = useApiResource<TokensResponse>(TOKENS_PATH);
  const [tokens, setTokens] = useState<TokenView[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setTokens(resource.data.tokens);
    }
  }, [resource.data]);

  const handleSaved = (saved: TokenView) => {
    setTokens((current) => {
      const exists = current.some((token) => token.id === saved.id);
      return exists
        ? current.map((token) => (token.id === saved.id ? saved : token))
        : [saved, ...current];
    });
    setIsAdding(false);
    setEditingId(null);
  };

  const handleDeleted = (tokenId: string) => {
    setTokens((current) => current.filter((token) => token.id !== tokenId));
    resource.reload();
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>Tokens</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            Add token
          </button>
        )}
      </div>
      <p className="field_hint">
        A single secret value under a name. An AI provider is keyed with one.
      </p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <TokenForm onSaved={handleSaved} onCancel={() => setIsAdding(false)} />
      )}

      {tokens.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="key" size={22} />
          <span className="keys_empty_title">No tokens yet</span>
          <span className="keys_empty_hint">
            Store a token once, then reference it from AI providers instead of
            pasting it again.
          </span>
        </div>
      ) : (
        <div className="keys_list">
          {tokens.map((token) =>
            editingId === token.id ? (
              <TokenForm
                key={token.id}
                initial={token}
                onSaved={handleSaved}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <TokenCard
                key={token.id}
                value={token}
                onSaved={handleSaved}
                onEdit={() => setEditingId(token.id)}
                onDeleted={handleDeleted}
              />
            ),
          )}
        </div>
      )}
    </section>
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
      body: keyDeleteBody(value.device_count),
      confirmLabel: "Delete",
      onConfirm: () => void deleteKey(),
    });

  const deleteKey = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(`/credentials/ssh_keys/${value.id}`);
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

interface LoginFormProps {
  initial?: LoginView;
  onSaved: (login: LoginView) => void;
  onCancel: () => void;
}

function LoginForm({ initial, onSaved, onCancel }: LoginFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [username, setUsername] = useState(initial?.username ?? "");
  const [password, setPassword] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEditing = initial !== undefined;
  const isReady = name.trim().length > 0 && (isEditing || password.length > 0);

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        username: username.trim().length > 0 ? username.trim() : null,
        password,
      };
      const saved = isEditing
        ? await apiPut<LoginView>(`${LOGINS_PATH}/${initial.id}`, payload)
        : await apiPost<LoginView>(LOGINS_PATH, payload);
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
        {isEditing ? `Edit ${initial.name}` : "New login"}
      </div>
      <div className="credentials_form_row">
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
          <span className="field_label">Username</span>
          <input
            className="input"
            value={username}
            placeholder="backup"
            spellCheck={false}
            onChange={(event) => setUsername(event.target.value)}
          />
          <span className="field_hint">
            Leave blank to store a bare password.
          </span>
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
          {isSaving ? "Saving…" : "Save login"}
        </button>
      </div>
    </div>
  );
}

interface LoginCardProps {
  value: LoginView;
  onSaved: (login: LoginView) => void;
  onEdit: () => void;
  onDeleted: (loginId: string) => void;
}

function LoginCard({ value, onSaved, onEdit, onDeleted }: LoginCardProps) {
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
      const updated = await apiPut<LoginView>(`${LOGINS_PATH}/${value.id}`, {
        name: draftName.trim(),
      });
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
      body: loginDeleteBody(value.device_count, value.service_count),
      confirmLabel: "Delete",
      onConfirm: () => void deleteLogin(),
    });

  const deleteLogin = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(`${LOGINS_PATH}/${value.id}`);
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

      {value.username !== null && (
        <div className="key_card_fingerprint">{value.username}</div>
      )}

      <div className="key_card_meta">
        <span
          className={`key_card_tag ${
            value.device_count + value.service_count > 0
              ? "key_card_tag--used"
              : ""
          }`}
        >
          {loginUsage(value.device_count, value.service_count)}
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

interface TokenFormProps {
  initial?: TokenView;
  onSaved: (token: TokenView) => void;
  onCancel: () => void;
}

function TokenForm({ initial, onSaved, onCancel }: TokenFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [value, setValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEditing = initial !== undefined;
  const isReady = name.trim().length > 0 && (isEditing || value.length > 0);

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const payload = { name: name.trim(), value };
      const saved = isEditing
        ? await apiPut<TokenView>(`${TOKENS_PATH}/${initial.id}`, payload)
        : await apiPost<TokenView>(TOKENS_PATH, payload);
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
        {isEditing ? `Edit ${initial.name}` : "New token"}
      </div>
      <label className="field">
        <span className="field_label">Name</span>
        <input
          className="input"
          value={name}
          placeholder="Anthropic key"
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="field">
        <span className="field_label">Value</span>
        <PasswordInput value={value} onChange={setValue} />
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
          {isSaving ? "Saving…" : "Save token"}
        </button>
      </div>
    </div>
  );
}

interface TokenCardProps {
  value: TokenView;
  onSaved: (token: TokenView) => void;
  onEdit: () => void;
  onDeleted: (tokenId: string) => void;
}

function TokenCard({ value, onSaved, onEdit, onDeleted }: TokenCardProps) {
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
      const updated = await apiPut<TokenView>(`${TOKENS_PATH}/${value.id}`, {
        name: draftName.trim(),
      });
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
      body: tokenDeleteBody(value.provider_count, value.node_count),
      confirmLabel: "Delete",
      onConfirm: () => void deleteToken(),
    });

  const deleteToken = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(`${TOKENS_PATH}/${value.id}`);
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
            value.provider_count + value.node_count > 0
              ? "key_card_tag--used"
              : ""
          }`}
        >
          {tokenUsage(value.provider_count, value.node_count)}
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

/** One count with its pluralized noun, e.g. "2 devices". */
function countNoun(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** The usage tag's wording: which counts are nonzero, joined. */
function loginUsage(deviceCount: number, serviceCount: number): string {
  const parts: string[] = [];
  if (deviceCount > 0) {
    parts.push(countNoun(deviceCount, "device"));
  }
  if (serviceCount > 0) {
    parts.push(countNoun(serviceCount, "service"));
  }
  return parts.length === 0 ? "unused" : parts.join(" · ");
}

/** The token usage tag's wording: which counts are nonzero, joined. */
function tokenUsage(providerCount: number, nodeCount: number): string {
  const parts: string[] = [];
  if (providerCount > 0) {
    parts.push(countNoun(providerCount, "provider"));
  }
  if (nodeCount > 0) {
    parts.push(countNoun(nodeCount, "node"));
  }
  return parts.length === 0 ? "unused" : parts.join(" · ");
}

/** The delete confirmation's body for a key: who loses it. */
function keyDeleteBody(deviceCount: number): string {
  if (deviceCount === 0) {
    return "The private key is deleted from this box.";
  }
  const verb = deviceCount === 1 ? "loses" : "lose";
  return `${countNoun(deviceCount, "device")} ${verb} this key and will need a new one.`;
}

/** The delete confirmation's body for a login: who loses it. */
function loginDeleteBody(deviceCount: number, serviceCount: number): string {
  const parts: string[] = [];
  if (deviceCount > 0) {
    parts.push(countNoun(deviceCount, "device"));
  }
  if (serviceCount > 0) {
    parts.push(countNoun(serviceCount, "service"));
  }
  if (parts.length === 0) {
    return "The login and its password are deleted from this box.";
  }
  const verb = deviceCount + serviceCount === 1 ? "loses" : "lose";
  return `${parts.join(" and ")} ${verb} this login and will need a new one.`;
}

/** The delete confirmation's body for a token: who loses it. */
function tokenDeleteBody(providerCount: number, nodeCount: number): string {
  const parts: string[] = [];
  if (providerCount > 0) {
    parts.push(countNoun(providerCount, "provider"));
  }
  if (nodeCount > 0) {
    parts.push(countNoun(nodeCount, "node"));
  }
  if (parts.length === 0) {
    return "The token is deleted from this box.";
  }
  const verb = providerCount + nodeCount === 1 ? "loses" : "lose";
  const disabled =
    nodeCount === 0
      ? ""
      : nodeCount === 1
        ? " The node is disabled."
        : " The nodes are disabled.";
  return `${parts.join(" and ")} ${verb} this token and will need a new one.${disabled}`;
}
