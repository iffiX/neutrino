import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { ToggleSwitch } from "./toggle_switch";
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

import "./ai_providers_section.css";

/**
 * The AI providers panel: which endpoints the gateway forwards to, and in
 * which order it tries them.
 *
 * The order and the enabled flags are a draft this panel stages and its apply
 * bar commits, because reordering is several presses and each one would
 * otherwise restart the gateway. The records themselves — adding, editing and
 * deleting a provider — write where they are entered, the way every other
 * record list in the panel does.
 */

const WORDING = {
  title: "Providers",
  hint: "The endpoints the gateway forwards to, each keyed with a stored token. The list is the serving order: the first enabled provider answers first.",
  addProvider: "Add provider",
  newProvider: "New provider",
  editProvider: (name: string) => `Edit ${name}`,
  serveEarlier: "Serve earlier",
  serveLater: "Serve later",
  position: (index: number) => `Position ${index}`,
  serving: "Serving",
  notServing: "Not serving",
  needsToken: "Needs a token before it can serve",
  defaultEndpoint: "default endpoint",
  noToken: "no key",
  keyed: "keyed",
  added: (ago: string) => `added ${ago}`,
  edit: "Edit",
  delete: "Delete",
  deleteTitle: (name: string) => `Delete ${name}`,
  deleteBody:
    "The provider is removed from this box; the token it was keyed with stays stored.",
  empty: "No providers yet",
  emptyHint:
    "Add an API endpoint and token once, instead of pasting it into every machine.",
  applyLabel: "Apply providers",
  applyHintDrafts:
    "Saves the serving order and which providers are enabled, then reloads the gateway.",
  applyHintStale:
    "The gateway is still serving an older set of providers; this reloads it.",
  applyWarning: "The gateway restarts, and requests in flight fail.",
  fieldName: "Name",
  fieldKind: "Kind",
  fieldBaseUrl: "Base URL",
  fieldModels: "Model aliases",
  fieldToken: "API token",
  fieldNewTokenName: "New token name",
  fieldNewTokenValue: "Value",
  baseUrlHint:
    "Leave empty for the service's default; set it for a relay. Match the kind to the protocol the endpoint speaks, not to whose models are behind it — DeepSeek's /anthropic endpoint is Anthropic.",
  modelsHint:
    "One per line, real name first; add = alias when tools should see a different name. Devices are told to ask for the first one.",
  tokenHint: "Pick a stored token, or store a new one.",
  tokenPlaceholder: "Select a token…",
  tokenNewOption: "＋ Store a new token…",
  namePlaceholder: "Anthropic direct",
  cancel: "Cancel",
  save: "Save provider",
  saving: "Saving…",
} as const;

const AI_PROVIDERS_PATH = "/ai/providers";
const TOKENS_PATH = "/credentials/tokens";
const CLIPROXYAPI_APPLY_PATH = "/cliproxyapi/apply";

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

interface AiProvidersSectionProps {
  /** The gateway is running an older set of providers than the stored ones. */
  isServingStale: boolean;
  /** Called once the gateway has been reloaded from the stored providers. */
  onApplied: () => void;
}

export function AiProvidersSection({
  isServingStale,
  onApplied,
}: AiProvidersSectionProps) {
  const resource = useApiResource<AiProvidersResponse>(AI_PROVIDERS_PATH);
  const [saved, setSaved] = useState<AiProviderView[]>([]);
  const [draft, setDraft] = useState<AiProviderView[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [applyNotice, setApplyNotice] = useState<string | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setSaved(resource.data.providers);
      setDraft(resource.data.providers);
    }
  }, [resource.data]);

  const changedProviders = draft.filter(
    (provider) =>
      saved.find((stored) => stored.id === provider.id)?.is_enabled !==
      provider.is_enabled,
  );
  const isOrderDirty =
    draft.map((provider) => provider.id).join("\n") !==
    saved.map((provider) => provider.id).join("\n");
  const hasDrafts = isOrderDirty || changedProviders.length > 0;

  const handleSaved = (savedProvider: AiProviderView) => {
    const fold = (list: AiProviderView[]) =>
      list.some((provider) => provider.id === savedProvider.id)
        ? list.map((provider) =>
            provider.id === savedProvider.id ? savedProvider : provider,
          )
        : [...list, savedProvider];
    setSaved(fold);
    setDraft(fold);
    setIsAdding(false);
    setEditingId(null);
  };

  const handleDeleted = (providerId: string) => {
    const drop = (list: AiProviderView[]) =>
      list.filter((provider) => provider.id !== providerId);
    setSaved(drop);
    setDraft(drop);
  };

  const handleMove = (providerId: string, offset: number) => {
    setDraft((current) => {
      const index = current.findIndex((provider) => provider.id === providerId);
      const target = index + offset;
      if (index < 0 || target < 0 || target >= current.length) {
        return current;
      }
      const reordered = [...current];
      const [moved] = reordered.splice(index, 1);
      if (moved === undefined) {
        return current;
      }
      reordered.splice(target, 0, moved);
      return reordered;
    });
  };

  const handleToggle = (providerId: string, isEnabled: boolean) => {
    setDraft((current) =>
      current.map((provider) =>
        provider.id === providerId
          ? { ...provider, is_enabled: isEnabled }
          : provider,
      ),
    );
  };

  const handleApply = async () => {
    setIsBusy(true);
    setApplyError(null);
    setApplyNotice(null);
    try {
      for (const provider of changedProviders) {
        await apiPut<AiProviderView>(`${AI_PROVIDERS_PATH}/${provider.id}`, {
          is_enabled: provider.is_enabled,
        });
      }
      if (isOrderDirty) {
        await apiPut(`${AI_PROVIDERS_PATH}/order`, {
          provider_ids: draft.map((provider) => provider.id),
        });
      }
      const result = await apiPost<{ message: string }>(CLIPROXYAPI_APPLY_PATH);
      setApplyNotice(result.message);
      resource.reload();
      onApplied();
    } catch (cause: unknown) {
      setApplyError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleReset = () => {
    setDraft(saved);
    setApplyError(null);
    setApplyNotice(null);
  };

  return (
    <section
      className={`settings_group ${hasDrafts ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{WORDING.title}</h2>
        {!isAdding && (
          <button
            type="button"
            className="button credentials_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            {WORDING.addProvider}
          </button>
        )}
      </div>
      <p className="field_hint">{WORDING.hint}</p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {isAdding && (
        <ProviderForm
          onSaved={handleSaved}
          onCancel={() => setIsAdding(false)}
        />
      )}

      {draft.length === 0 && !isAdding ? (
        <div className="keys_empty">
          <Icon name="nodes" size={22} />
          <span className="keys_empty_title">{WORDING.empty}</span>
          <span className="keys_empty_hint">{WORDING.emptyHint}</span>
        </div>
      ) : (
        <div className="ai_providers_list">
          {draft.map((provider, index) =>
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
                position={index + 1}
                isFirst={index === 0}
                isLast={index === draft.length - 1}
                onMoveUp={() => handleMove(provider.id, -1)}
                onMoveDown={() => handleMove(provider.id, 1)}
                onToggle={(isEnabled) => handleToggle(provider.id, isEnabled)}
                onEdit={() => setEditingId(provider.id)}
                onDeleted={handleDeleted}
              />
            ),
          )}
        </div>
      )}

      <ApplyBar
        isDirty={hasDrafts || isServingStale}
        isBusy={isBusy}
        label={WORDING.applyLabel}
        hint={hasDrafts ? WORDING.applyHintDrafts : WORDING.applyHintStale}
        warning={WORDING.applyWarning}
        error={applyError}
        notice={applyNotice}
        onReset={handleReset}
        onApply={() => void handleApply()}
      />
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
        {isEditing ? WORDING.editProvider(initial.name) : WORDING.newProvider}
      </div>
      <div className="credentials_form_row">
        <label className="field">
          <span className="field_label">{WORDING.fieldName}</span>
          <input
            className="input"
            value={name}
            placeholder={WORDING.namePlaceholder}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">{WORDING.fieldKind}</span>
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
        <span className="field_label">{WORDING.fieldBaseUrl}</span>
        <input
          className="input"
          value={baseUrl}
          placeholder={PROVIDER_URL_PLACEHOLDERS[kind]}
          spellCheck={false}
          onChange={(event) => setBaseUrl(event.target.value)}
        />
        <span className="field_hint">{WORDING.baseUrlHint}</span>
      </label>
      <label className="field">
        <span className="field_label">{WORDING.fieldModels}</span>
        <textarea
          className="input"
          rows={3}
          spellCheck={false}
          placeholder={"claude-fable-5\nrelay-model-name = claude-opus-5"}
          value={modelsText}
          onChange={(event) => setModelsText(event.target.value)}
        />
        <span className="field_hint">{WORDING.modelsHint}</span>
      </label>
      <label className="field">
        <span className="field_label">{WORDING.fieldToken}</span>
        <select
          className="input"
          value={secretId}
          onChange={(event) => setSecretId(event.target.value)}
        >
          <option value="">{WORDING.tokenPlaceholder}</option>
          {(tokens.data?.tokens ?? []).map((token) => (
            <option key={token.id} value={token.id}>
              {token.name}
            </option>
          ))}
          <option value={NEW_TOKEN_OPTION}>{WORDING.tokenNewOption}</option>
        </select>
        <span className="field_hint">{WORDING.tokenHint}</span>
      </label>
      {isAddingToken && (
        <div className="credentials_form_row">
          <label className="field">
            <span className="field_label">{WORDING.fieldNewTokenName}</span>
            <input
              className="input"
              value={newTokenName}
              placeholder={`${name.trim() || "provider"} key`}
              onChange={(event) => setNewTokenName(event.target.value)}
            />
          </label>
          <label className="field">
            <span className="field_label">{WORDING.fieldNewTokenValue}</span>
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
          {WORDING.cancel}
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? WORDING.saving : WORDING.save}
        </button>
      </div>
    </div>
  );
}

interface ProviderCardProps {
  value: AiProviderView;
  position: number;
  isFirst: boolean;
  isLast: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onToggle: (isEnabled: boolean) => void;
  onEdit: () => void;
  onDeleted: (providerId: string) => void;
}

function ProviderCard({
  value,
  position,
  isFirst,
  isLast,
  onMoveUp,
  onMoveDown,
  onToggle,
  onEdit,
  onDeleted,
}: ProviderCardProps) {
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const confirm = useConfirm();

  const hasToken = value.secret_id !== null;

  const handleDelete = () =>
    confirm.ask({
      title: WORDING.deleteTitle(value.name),
      body: WORDING.deleteBody,
      confirmLabel: WORDING.delete,
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
    <div className="key_card ai_provider_card">
      <div className="ai_provider_rank">
        <button
          type="button"
          className="ai_rank_button"
          title={WORDING.serveEarlier}
          aria-label={WORDING.serveEarlier}
          disabled={isFirst}
          onClick={onMoveUp}
        >
          <Icon name="arrow_up" size={14} />
        </button>
        <span className="ai_rank_index mono" title={WORDING.position(position)}>
          {position}
        </span>
        <button
          type="button"
          className="ai_rank_button"
          title={WORDING.serveLater}
          aria-label={WORDING.serveLater}
          disabled={isLast}
          onClick={onMoveDown}
        >
          <Icon name="arrow_down" size={14} />
        </button>
      </div>

      <div className="ai_provider_body">
        <div className="key_card_head">
          <span className="credentials_provider_name">{value.name}</span>
          <span className="key_card_type">{value.kind}</span>
        </div>

        <div className="key_card_fingerprint">
          {value.base_url.length > 0 ? value.base_url : WORDING.defaultEndpoint}
        </div>

        <ToggleSwitch
          isOn={value.is_enabled}
          isDisabled={!hasToken}
          label={value.is_enabled ? WORDING.serving : WORDING.notServing}
          description={hasToken ? undefined : WORDING.needsToken}
          onChange={onToggle}
        />

        <div className="key_card_meta">
          <span
            className={`key_card_tag ${hasToken ? "key_card_tag--used" : ""}`}
          >
            <Icon name="lock" size={11} />
            {hasToken ? WORDING.keyed : WORDING.noToken}
          </span>
          {value.created_at.length > 0 && (
            <span className="key_card_added">
              {WORDING.added(formatTimeAgo(value.created_at))}
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
            {WORDING.edit}
          </button>
          <button
            type="button"
            className="button button--ghost button--small button--danger"
            disabled={isBusy}
            onClick={handleDelete}
          >
            <Icon name="trash" size={13} />
            {WORDING.delete}
          </button>
        </div>
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
