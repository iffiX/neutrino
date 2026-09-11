import { useEffect, useState } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { PasswordInput } from "../components/password_input";
import { apiDelete, apiPost, describeError } from "../api_client";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { privateKeyPlaceholder } from "../private_key_placeholder";
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

/** The examples the name fields show, which are names rather than words. */
const KEY_NAME_PLACEHOLDER = "work laptop";
const LOGIN_NAME_PLACEHOLDER = "lab machines";
const LOGIN_USERNAME_PLACEHOLDER = "backup";
const TOKEN_NAME_PLACEHOLDER = "Anthropic key";

export function CredentialsPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <div className="page credentials_page">
      <header className="page_header">
        <div>
          <h1 className="page_title">{t("ui.credentials.title")}</h1>
          <p className="page_subtitle">{t("ui.credentials.subtitle")}</p>
        </div>
      </header>

      <SshKeysSection />
      <LoginsSection />
      <TokensSection />
    </div>
  );
}

function SshKeysSection() {
  // Redrawn when the panel's language changes.
  useLanguage();
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
        <h2>{t("ui.credentials.keys_title")}</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            {t("ui.credentials.add_key")}
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
          <span className="keys_empty_title">
            {t("ui.credentials.keys_empty")}
          </span>
          <span className="keys_empty_hint">
            {t("ui.credentials.keys_empty_hint")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
        <h2>{t("ui.credentials.logins_title")}</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            {t("ui.credentials.add_login")}
          </button>
        )}
      </div>
      <p className="field_hint">{t("ui.credentials.logins_hint")}</p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <LoginForm onAdded={handleAdded} onCancel={() => setIsAdding(false)} />
      )}

      {logins.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="lock" size={22} />
          <span className="keys_empty_title">
            {t("ui.credentials.logins_empty")}
          </span>
          <span className="keys_empty_hint">
            {t("ui.credentials.logins_empty_hint")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
        <h2>{t("ui.credentials.tokens_title")}</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            {t("ui.credentials.add_token")}
          </button>
        )}
      </div>
      <p className="field_hint">{t("ui.credentials.tokens_hint")}</p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <TokenForm onAdded={handleAdded} onCancel={() => setIsAdding(false)} />
      )}

      {tokens.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="key" size={22} />
          <span className="keys_empty_title">
            {t("ui.credentials.tokens_empty")}
          </span>
          <span className="keys_empty_hint">
            {t("ui.credentials.tokens_empty_hint")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
      <div className="section_label">{t("ui.credentials.new_key")}</div>
      <label className="field">
        <span className="field_label">{t("ui.credentials.name")}</span>
        <input
          className="input"
          value={name}
          placeholder={KEY_NAME_PLACEHOLDER}
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="field">
        <span className="field_label">{t("ui.credentials.private_key")}</span>
        <textarea
          className="input input--key"
          value={privateKey}
          spellCheck={false}
          autoComplete="off"
          rows={8}
          placeholder={privateKeyPlaceholder()}
          onChange={(event) => setPrivateKey(event.target.value)}
        />
        <span className="field_hint">{t("ui.credentials.key_hint")}</span>
      </label>
      <label className="field">
        <span className="field_label">{t("ui.credentials.passphrase")}</span>
        <PasswordInput value={passphrase} onChange={setPassphrase} />
        <span className="field_hint">
          {t("ui.credentials.passphrase_hint")}
        </span>
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="keys_add_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          {t("ui.credentials.cancel")}
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? t("ui.credentials.saving") : t("ui.credentials.save_key")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const handleDelete = () =>
    confirm.ask({
      title: t("ui.credentials.delete_title", { name: value.name }),
      body: keyDeleteBody(value.device_count),
      confirmLabel: t("ui.credentials.delete"),
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
        <span className="key_card_name" title={value.name}>
          {value.name}
        </span>
        <span className="key_card_type">{value.key_type}</span>
      </div>

      <div className="key_card_fingerprint">{value.fingerprint}</div>

      <div className="key_card_meta">
        {value.has_passphrase && (
          <span className="key_card_tag">
            <Icon name="lock" size={11} />
            {t("state.encrypted")}
          </span>
        )}
        <span
          className={`key_card_tag ${
            value.device_count > 0 ? "key_card_tag--used" : ""
          }`}
        >
          {deviceUsage(value.device_count)}
        </span>
        {value.created_at.length > 0 && (
          <span className="key_card_added">
            {t("ui.credentials.added", {
              when: formatTimeAgo(value.created_at),
            })}
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
          {t("ui.credentials.delete")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
      <div className="section_label">{t("ui.credentials.new_login")}</div>
      <div className="credentials_form_row">
        <label className="field">
          <span className="field_label">{t("ui.credentials.name")}</span>
          <input
            className="input"
            value={name}
            placeholder={LOGIN_NAME_PLACEHOLDER}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.credentials.username")}</span>
          <input
            className="input"
            value={username}
            placeholder={LOGIN_USERNAME_PLACEHOLDER}
            spellCheck={false}
            onChange={(event) => setUsername(event.target.value)}
          />
          <span className="field_hint">
            {t("ui.credentials.username_hint")}
          </span>
        </label>
      </div>
      <label className="field">
        <span className="field_label">{t("ui.credentials.password")}</span>
        <PasswordInput value={password} onChange={setPassword} />
        <span className="field_hint">{t("ui.credentials.sealed_hint")}</span>
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="keys_add_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          {t("ui.credentials.cancel")}
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving
            ? t("ui.credentials.saving")
            : t("ui.credentials.save_login")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const handleDelete = () =>
    confirm.ask({
      title: t("ui.credentials.delete_title", { name: value.name }),
      body: loginDeleteBody(value.device_count),
      confirmLabel: t("ui.credentials.delete"),
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
        <span className="key_card_name" title={value.name}>
          {value.name}
        </span>
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
          {deviceUsage(value.device_count)}
        </span>
        {value.created_at.length > 0 && (
          <span className="key_card_added">
            {t("ui.credentials.added", {
              when: formatTimeAgo(value.created_at),
            })}
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
          {t("ui.credentials.delete")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
      <div className="section_label">{t("ui.credentials.new_token")}</div>
      <label className="field">
        <span className="field_label">{t("ui.credentials.name")}</span>
        <input
          className="input"
          value={name}
          placeholder={TOKEN_NAME_PLACEHOLDER}
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="field">
        <span className="field_label">{t("ui.credentials.value")}</span>
        <PasswordInput value={value} onChange={setValue} />
        <span className="field_hint">{t("ui.credentials.sealed_hint")}</span>
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="keys_add_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          {t("ui.credentials.cancel")}
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving
            ? t("ui.credentials.saving")
            : t("ui.credentials.save_token")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const handleDelete = () =>
    confirm.ask({
      title: t("ui.credentials.delete_title", { name: value.name }),
      body: tokenDeleteBody(value.provider_count, value.node_count),
      confirmLabel: t("ui.credentials.delete"),
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
        <span className="key_card_name" title={value.name}>
          {value.name}
        </span>
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
            {t("ui.credentials.added", {
              when: formatTimeAgo(value.created_at),
            })}
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
          {t("ui.credentials.delete")}
        </button>
      </div>
      {confirm.modal}
    </div>
  );
}

/** The usage tag's wording: unused, or how many devices hold it. */
function deviceUsage(deviceCount: number): string {
  if (deviceCount === 0) {
    return t("state.unused");
  }
  return deviceCount === 1
    ? t("ui.credentials.usage_device_one")
    : t("ui.credentials.usage_devices", { count: deviceCount });
}

/** The token usage tag's wording: which counts are nonzero, joined. */
function tokenUsage(providerCount: number, nodeCount: number): string {
  const parts: string[] = [];
  if (providerCount > 0) {
    parts.push(
      providerCount === 1
        ? t("ui.credentials.usage_provider_one")
        : t("ui.credentials.usage_providers", { count: providerCount }),
    );
  }
  if (nodeCount > 0) {
    parts.push(
      nodeCount === 1
        ? t("ui.credentials.usage_node_one")
        : t("ui.credentials.usage_nodes", { count: nodeCount }),
    );
  }
  return parts.length === 0 ? t("state.unused") : parts.join(" · ");
}

/** The delete confirmation's body for a key: who loses it. */
function keyDeleteBody(deviceCount: number): string {
  if (deviceCount === 0) {
    return t("ui.credentials.key_delete_none");
  }
  return deviceCount === 1
    ? t("ui.credentials.key_delete_one")
    : t("ui.credentials.key_delete_many", { count: deviceCount });
}

/** The delete confirmation's body for a login: who loses it. */
function loginDeleteBody(deviceCount: number): string {
  if (deviceCount === 0) {
    return t("ui.credentials.login_delete_none");
  }
  return deviceCount === 1
    ? t("ui.credentials.login_delete_one")
    : t("ui.credentials.login_delete_many", { count: deviceCount });
}

/** The delete confirmation's body for a token: who loses it, one sentence each. */
function tokenDeleteBody(providerCount: number, nodeCount: number): string {
  const sentences: string[] = [];
  if (providerCount > 0) {
    sentences.push(
      providerCount === 1
        ? t("ui.credentials.token_delete_provider_one")
        : t("ui.credentials.token_delete_providers", { count: providerCount }),
    );
  }
  if (nodeCount > 0) {
    sentences.push(
      nodeCount === 1
        ? t("ui.credentials.token_delete_node_one")
        : t("ui.credentials.token_delete_nodes", { count: nodeCount }),
    );
  }
  return sentences.length === 0
    ? t("ui.credentials.token_delete_none")
    : sentences.join(" ");
}
