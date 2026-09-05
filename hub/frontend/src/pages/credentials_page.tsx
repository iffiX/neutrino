import { useEffect, useState } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { PasswordInput } from "../components/password_input";
import { apiDelete, apiPost, describeError } from "../api_client";
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
 *
 * A credential is added and deleted, never edited — not its value, not its
 * name. Replacing one is adding its successor, pointing the things that use it
 * at the new record, and deleting the old one.
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
            <KeyCard key={key.id} value={key} onDeleted={handleDeleted} />
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

  useEffect(() => {
    if (resource.data !== null) {
      setLogins(resource.data.logins);
    }
  }, [resource.data]);

  const handleAdded = (created: LoginView) => {
    setLogins((current) => [created, ...current]);
    setIsAdding(false);
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
        <LoginForm onAdded={handleAdded} onCancel={() => setIsAdding(false)} />
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
          {logins.map((login) => (
            <LoginCard key={login.id} value={login} onDeleted={handleDeleted} />
          ))}
        </div>
      )}
    </section>
  );
}

function TokensSection() {
  const resource = useApiResource<TokensResponse>(TOKENS_PATH);
  const [tokens, setTokens] = useState<TokenView[]>([]);
  const [isAdding, setIsAdding] = useState(false);

  useEffect(() => {
    if (resource.data !== null) {
      setTokens(resource.data.tokens);
    }
  }, [resource.data]);

  const handleAdded = (created: TokenView) => {
    setTokens((current) => [created, ...current]);
    setIsAdding(false);
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
        <TokenForm onAdded={handleAdded} onCancel={() => setIsAdding(false)} />
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
          {tokens.map((token) => (
            <TokenCard key={token.id} value={token} onDeleted={handleDeleted} />
          ))}
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
  onDeleted: (keyId: string) => void;
}

function KeyCard({ value, onDeleted }: KeyCardProps) {
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

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
        <span className="key_card_name">{value.name}</span>
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
  onAdded: (login: LoginView) => void;
  onCancel: () => void;
}

function LoginForm({ onAdded, onCancel }: LoginFormProps) {
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isReady = name.trim().length > 0 && password.length > 0;

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const created = await apiPost<LoginView>(LOGINS_PATH, {
        name: name.trim(),
        username: username.trim().length > 0 ? username.trim() : null,
        password,
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
      <div className="section_label">New login</div>
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
          Stored sealed on the gateway, and never shown again.
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
  onDeleted: (loginId: string) => void;
}

function LoginCard({ value, onDeleted }: LoginCardProps) {
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const handleDelete = () =>
    confirm.ask({
      title: `Delete ${value.name}`,
      body: loginDeleteBody(value.device_count),
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
        <span className="key_card_name">{value.name}</span>
      </div>

      {value.username !== null && (
        <div className="key_card_fingerprint">{value.username}</div>
      )}

      <div className="key_card_meta">
        <span
          className={`key_card_tag ${
            value.device_count > 0 ? "key_card_tag--used" : ""
          }`}
        >
          {loginUsage(value.device_count)}
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

interface TokenFormProps {
  onAdded: (token: TokenView) => void;
  onCancel: () => void;
}

function TokenForm({ onAdded, onCancel }: TokenFormProps) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isReady = name.trim().length > 0 && value.length > 0;

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const created = await apiPost<TokenView>(TOKENS_PATH, {
        name: name.trim(),
        value,
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
      <div className="section_label">New token</div>
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
          Stored sealed on the gateway, and never shown again.
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
  onDeleted: (tokenId: string) => void;
}

function TokenCard({ value, onDeleted }: TokenCardProps) {
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

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
        <span className="key_card_name">{value.name}</span>
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

/** The usage tag's wording: unused, or how many devices hold it. */
function loginUsage(deviceCount: number): string {
  return deviceCount === 0 ? "unused" : countNoun(deviceCount, "device");
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
function loginDeleteBody(deviceCount: number): string {
  if (deviceCount === 0) {
    return "The login and its password are deleted from this box.";
  }
  const verb = deviceCount === 1 ? "loses" : "lose";
  return `${countNoun(deviceCount, "device")} ${verb} this login and will need a new one.`;
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
