import { useEffect, useState } from "react";

import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
import { formatTimeAgo } from "../format_duration";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import type {
  AiProviderKind,
  AiProviderModel,
  AiProviderView,
  AiProvidersResponse,
  TokenView,
  TokensResponse,
} from "../api_types";

/**
 * The AI providers, managed where they are used: the AI page. Each provider
 * is keyed with a stored token from the Credentials page; the gateway is
 * re-applied quietly after every change, so switching takes effect on every
 * connected machine at once.
 */

const AI_PROVIDERS_PATH = "/ai/providers";
const TOKENS_PATH = "/credentials/tokens";

// The provider form's <select> sentinel for "store a new token" rather than
// choosing an existing one.
const NEW_TOKEN_OPTION = "__new__";

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

export function AiProvidersSection() {
  const resource = useApiResource<AiProvidersResponse>(AI_PROVIDERS_PATH);
  const [providers, setProviders] = useState<AiProviderView[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setProviders(resource.data.providers);
    }
  }, [resource.data]);

  const applyQuietly = () => {
    // The gateway re-renders from what was just saved; a failure surfaces on
    // the Gateway section's own probe rather than as a second error here.
    void apiPost("/cliproxyapi/apply").catch(() => {});
  };

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
    applyQuietly();
  };

  const handleDeleted = (providerId: string) => {
    setProviders((current) =>
      current.filter((provider) => provider.id !== providerId),
    );
    applyQuietly();
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>Providers</h2>
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
        The endpoints the gateway forwards to, each keyed with a stored token.
        Serving switches on and off instantly, on every machine at once.
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
                onSaved={handleSaved}
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
  const tokens = useApiResource<TokensResponse>(TOKENS_PATH);
  const [name, setName] = useState(initial?.name ?? "");
  const [kind, setKind] = useState<AiProviderKind>(
    initial?.kind ?? "anthropic",
  );
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? "");
  const [modelsText, setModelsText] = useState(
    serializeModels(initial?.models ?? []),
  );
  const [secretId, setSecretId] = useState(initial?.secret_id ?? "");
  const [newTokenName, setNewTokenName] = useState("");
  const [newTokenValue, setNewTokenValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEditing = initial !== undefined;
  const isAddingToken = secretId === NEW_TOKEN_OPTION;
  const isSecretReady = isAddingToken
    ? newTokenValue.trim().length > 0
    : isEditing || secretId.length > 0;
  const isReady = name.trim().length > 0 && isSecretReady;

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      // A new token is stored first, then the provider references it — the
      // same token any other provider can then reuse.
      let resolvedSecretId = secretId;
      if (isAddingToken) {
        const createdToken = await apiPost<TokenView>(TOKENS_PATH, {
          name: newTokenName.trim() || `${name.trim()} key`,
          value: newTokenValue,
        });
        resolvedSecretId = createdToken.id;
      }
      const payload = {
        name: name.trim(),
        kind,
        base_url: baseUrl.trim(),
        secret_id: resolvedSecretId.length > 0 ? resolvedSecretId : null,
        models: parseModels(modelsText),
      };
      const saved = isEditing
        ? await apiPut<AiProviderView>(
            `${AI_PROVIDERS_PATH}/${initial.id}`,
            payload,
          )
        : await apiPost<AiProviderView>(AI_PROVIDERS_PATH, payload);
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
        <span className="field_label">API token</span>
        <select
          className="input"
          value={secretId}
          onChange={(event) => setSecretId(event.target.value)}
        >
          <option value="">Select a token…</option>
          {(tokens.data?.tokens ?? []).map((token) => (
            <option key={token.id} value={token.id}>
              {token.name}
            </option>
          ))}
          <option value={NEW_TOKEN_OPTION}>＋ Store a new token…</option>
        </select>
        <span className="field_hint">
          Pick a stored token, or store a new one.
        </span>
      </label>
      {isAddingToken && (
        <div className="credentials_form_row">
          <label className="field">
            <span className="field_label">New token name</span>
            <input
              className="input"
              value={newTokenName}
              placeholder={`${name.trim() || "provider"} key`}
              onChange={(event) => setNewTokenName(event.target.value)}
            />
          </label>
          <label className="field">
            <span className="field_label">Value</span>
            <PasswordInput value={newTokenValue} onChange={setNewTokenValue} />
          </label>
        </div>
      )}
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
  onSaved: (provider: AiProviderView) => void;
  onDeleted: (providerId: string) => void;
}

function ProviderCard({
  value,
  onEdit,
  onSaved,
  onDeleted,
}: ProviderCardProps) {
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const confirm = useConfirm();

  const handleToggle = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onSaved(
        await apiPut<AiProviderView>(`${AI_PROVIDERS_PATH}/${value.id}`, {
          is_enabled: !value.is_enabled,
        }),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleDelete = () =>
    confirm.ask({
      title: `Delete ${value.name}`,
      body: "The provider is removed from this box; the token it was keyed with stays stored.",
      confirmLabel: "Delete",
      onConfirm: () => void deleteProvider(),
    });

  const deleteProvider = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(`${AI_PROVIDERS_PATH}/${value.id}`);
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
            value.secret_id !== null && value.is_enabled
              ? "key_card_tag--used"
              : ""
          }`}
        >
          <Icon name="lock" size={11} />
          {value.secret_id === null
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
          disabled={isBusy || value.secret_id === null}
          onClick={() => void handleToggle()}
        >
          <Icon name={value.is_enabled ? "power" : "play"} size={13} />
          {value.is_enabled ? "Stop serving" : "Serve"}
        </button>
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
