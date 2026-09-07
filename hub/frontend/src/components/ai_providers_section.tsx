import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { ToggleSwitch } from "./toggle_switch";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
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
 * bar commits, because a drag is a rearrangement of the whole list and
 * committing each step of it would restart the gateway. The records
 * themselves — adding, editing and deleting a provider — write where they are
 * entered, the way every other record list in the panel does.
 */

const WORDING = {
  title: "Providers",
  hint: "The endpoints the gateway forwards to, each keyed with a stored token. The list is the serving order: the first enabled provider answers first.",
  addProvider: "Add provider",
  newProvider: "New provider",
  editProvider: (name: string) => `Edit ${name}`,
  reorder: "Drag to reorder",
  serving: "Serving",
  notServing: "Not serving",
  needsToken: "Needs a token before it can serve",
  defaultEndpoint: "default endpoint",
  noToken: "no key",
  keyed: "keyed",
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
    "The gateway is serving an older configuration; applying reloads it.",
  applyWarning: "The gateway restarts, and requests in flight fail.",
  fieldName: "Name",
  fieldKind: "Kind",
  fieldBaseUrl: "Base URL",
  fieldModels: "Model aliases",
  fieldToken: "API token",
  fieldNewTokenName: "New token name",
  fieldNewTokenValue: "Value",
  baseUrlHint:
    "Leave empty for the service's default; set it for a relay. Match the kind to the protocol the endpoint speaks, not to whose models are behind it: DeepSeek's /anthropic endpoint is Anthropic.",
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

/** One drag in flight, measured from the list as it stood when it started. */
interface ProviderDragState {
  providerId: string;
  pointerId: number;
  fromIndex: number;
  toIndex: number;
  startY: number;
  deltaY: number;
  /** How far a passed-over row travels: the dragged row plus the list gap. */
  stepY: number;
  /** Every row's centre before the drag, in viewport coordinates. */
  centersY: number[];
  minDeltaY: number;
  maxDeltaY: number;
}

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
  const [drag, setDrag] = useState<ProviderDragState | null>(null);
  const rowNodes = useRef(new Map<string, HTMLDivElement>());

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

  // A row under the edit form is not a row to drag, and one provider has
  // nowhere to go.
  const isReorderable = draft.length > 1 && editingId === null;

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
    setDrag(null);
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

  const handleGripDown = (
    providerId: string,
    event: ReactPointerEvent<HTMLSpanElement>,
  ) => {
    const fromIndex = draft.findIndex((provider) => provider.id === providerId);
    if (!isReorderable || fromIndex < 0 || drag !== null) {
      return;
    }
    const rects: DOMRect[] = [];
    for (const provider of draft) {
      const node = rowNodes.current.get(provider.id);
      if (node === undefined) {
        return;
      }
      rects.push(node.getBoundingClientRect());
    }
    const first = rects[0];
    const last = rects[rects.length - 1];
    const dragged = rects[fromIndex];
    if (first === undefined || last === undefined || dragged === undefined) {
      return;
    }
    const second = rects[1];
    const gap = second === undefined ? 0 : second.top - first.bottom;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({
      providerId,
      pointerId: event.pointerId,
      fromIndex,
      toIndex: fromIndex,
      startY: event.clientY,
      deltaY: 0,
      stepY: dragged.height + gap,
      centersY: rects.map((rect) => rect.top + rect.height / 2),
      minDeltaY: first.top - dragged.top,
      maxDeltaY: last.bottom - dragged.bottom,
    });
  };

  const handleGripMove = (event: ReactPointerEvent<HTMLSpanElement>) => {
    if (drag === null || event.pointerId !== drag.pointerId) {
      return;
    }
    const deltaY = Math.min(
      Math.max(event.clientY - drag.startY, drag.minDeltaY),
      drag.maxDeltaY,
    );
    const centerY = (drag.centersY[drag.fromIndex] ?? 0) + deltaY;
    setDrag({ ...drag, deltaY, toIndex: nearestIndex(drag.centersY, centerY) });
  };

  const handleGripUp = (event: ReactPointerEvent<HTMLSpanElement>) => {
    if (drag === null || event.pointerId !== drag.pointerId) {
      return;
    }
    if (drag.toIndex !== drag.fromIndex) {
      setDraft((current) =>
        moveProvider(current, drag.fromIndex, drag.toIndex),
      );
    }
    setDrag(null);
  };

  const handleGripCancel = (event: ReactPointerEvent<HTMLSpanElement>) => {
    if (drag !== null && event.pointerId === drag.pointerId) {
      setDrag(null);
    }
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
    setDrag(null);
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
              <ProviderRow
                key={provider.id}
                value={provider}
                rowRef={(node) => {
                  registerRow(rowNodes.current, provider.id, node);
                }}
                isReorderable={isReorderable}
                isDragging={drag?.providerId === provider.id}
                shiftY={rowShiftY(drag, index)}
                onGripDown={(event) => handleGripDown(provider.id, event)}
                onGripMove={handleGripMove}
                onGripUp={handleGripUp}
                onGripCancel={handleGripCancel}
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

interface ProviderRowProps {
  value: AiProviderView;
  rowRef: (node: HTMLDivElement | null) => void;
  isReorderable: boolean;
  isDragging: boolean;
  shiftY: number;
  onGripDown: (event: ReactPointerEvent<HTMLSpanElement>) => void;
  onGripMove: (event: ReactPointerEvent<HTMLSpanElement>) => void;
  onGripUp: (event: ReactPointerEvent<HTMLSpanElement>) => void;
  onGripCancel: (event: ReactPointerEvent<HTMLSpanElement>) => void;
  onToggle: (isEnabled: boolean) => void;
  onEdit: () => void;
  onDeleted: (providerId: string) => void;
}

function ProviderRow({
  value,
  rowRef,
  isReorderable,
  isDragging,
  shiftY,
  onGripDown,
  onGripMove,
  onGripUp,
  onGripCancel,
  onToggle,
  onEdit,
  onDeleted,
}: ProviderRowProps) {
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const confirm = useConfirm();

  const hasToken = value.secret_id !== null;
  const endpoint =
    value.base_url.length > 0 ? value.base_url : WORDING.defaultEndpoint;
  const servingLabel = value.is_enabled ? WORDING.serving : WORDING.notServing;

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
    <div
      ref={rowRef}
      className={`ai_provider_row ${isDragging ? "ai_provider_row--dragging" : ""}`}
      style={
        shiftY === 0 ? undefined : { transform: `translateY(${shiftY}px)` }
      }
    >
      <div className="ai_provider_line">
        <span
          className={`ai_provider_grip ${isReorderable ? "" : "ai_provider_grip--idle"}`}
          title={isReorderable ? WORDING.reorder : undefined}
          onPointerDown={isReorderable ? onGripDown : undefined}
          onPointerMove={onGripMove}
          onPointerUp={onGripUp}
          onPointerCancel={onGripCancel}
        >
          <GripGlyph />
        </span>

        <span className="ai_provider_name">{value.name}</span>
        <span className="key_card_type">{value.kind}</span>
        <span
          className={`key_card_tag ${hasToken ? "key_card_tag--used" : ""}`}
        >
          <Icon name="lock" size={11} />
          {hasToken ? WORDING.keyed : WORDING.noToken}
        </span>
        <span className="ai_provider_url mono" title={endpoint}>
          {endpoint}
        </span>

        <div className="ai_provider_actions">
          <span
            className="ai_provider_toggle"
            title={hasToken ? servingLabel : WORDING.needsToken}
          >
            <ToggleSwitch
              isOn={value.is_enabled}
              isDisabled={!hasToken}
              label={servingLabel}
              onChange={onToggle}
            />
          </span>
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

      {error !== null && <span className="field_error">{error}</span>}
      {confirm.modal}
    </div>
  );
}

/** Six dots: the grip a pointer presses to carry a row up or down the list. */
function GripGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      width={14}
      height={14}
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="9" cy="5" r="1.7" />
      <circle cx="15" cy="5" r="1.7" />
      <circle cx="9" cy="12" r="1.7" />
      <circle cx="15" cy="12" r="1.7" />
      <circle cx="9" cy="19" r="1.7" />
      <circle cx="15" cy="19" r="1.7" />
    </svg>
  );
}

function registerRow(
  nodes: Map<string, HTMLDivElement>,
  providerId: string,
  node: HTMLDivElement | null,
): void {
  if (node === null) {
    nodes.delete(providerId);
  } else {
    nodes.set(providerId, node);
  }
}

/**
 * The slot the dragged row has reached: the one whose centre it is nearest,
 * so a row trades places once it is more than half way over its neighbour.
 */
function nearestIndex(centersY: number[], centerY: number): number {
  let nearest = 0;
  let shortest = Number.POSITIVE_INFINITY;
  centersY.forEach((slotCenterY, index) => {
    const distance = Math.abs(centerY - slotCenterY);
    if (distance < shortest) {
      shortest = distance;
      nearest = index;
    }
  });
  return nearest;
}

/**
 * Where one row sits while a drag is in flight.
 *
 * The dragged row follows the pointer; every row it has passed over travels
 * one step the other way, which is what opens the slot it will land in.
 */
function rowShiftY(drag: ProviderDragState | null, index: number): number {
  if (drag === null) {
    return 0;
  }
  if (index === drag.fromIndex) {
    return drag.deltaY;
  }
  if (
    drag.fromIndex < drag.toIndex &&
    index > drag.fromIndex &&
    index <= drag.toIndex
  ) {
    return -drag.stepY;
  }
  if (
    drag.fromIndex > drag.toIndex &&
    index >= drag.toIndex &&
    index < drag.fromIndex
  ) {
    return drag.stepY;
  }
  return 0;
}

function moveProvider(
  list: AiProviderView[],
  fromIndex: number,
  toIndex: number,
): AiProviderView[] {
  const reordered = [...list];
  const [moved] = reordered.splice(fromIndex, 1);
  if (moved === undefined) {
    return list;
  }
  reordered.splice(toIndex, 0, moved);
  return reordered;
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
