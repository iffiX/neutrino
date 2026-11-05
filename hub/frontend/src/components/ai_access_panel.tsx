import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import { Picker } from "./picker";
import type { PickerOption } from "./picker";
import { apiPost, describeError } from "../api_client";
import { copyText } from "../copy_text";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { useConfirm } from "../use_confirm";
import type {
  AiUsageKey,
  CliproxyApiKeyView,
  CliproxyApiStatusView,
} from "../api_types";

import "./ai_access_panel.css";

/**
 * The keys machines reach the gateway with.
 *
 * An enrolled client is handed its own key over its channel and is named on
 * its row, so what is distributed by hand here is the rest: a tool on the
 * hub's machine, or one using an SSH tunnel to it. The gateway generates these
 * keys rather than being given them, so each is shown to its owner — masked
 * in the list, and expanded once at the top the moment it is generated, which
 * is when somebody is holding the machine that needs it.
 *
 * Generating and revoking write where they are pressed: a revocation never
 * waits behind an apply bar. The default model is the panel's draft, which
 * its apply bar writes.
 */

const KEY_ADD_PATH = "/hub/ai/gateway/key/add";
const GATEWAY_SET_PATH = "/hub/ai/gateway/set";
const MASKED_KEY = "•".repeat(24);
const COPIED_CLEAR_MS = 1600;

interface AiAccessPanelProps {
  /** Where the keys are pointed, shown as the copy row above them. */
  endpoint: string;
  keys: CliproxyApiKeyView[];
  /** The usage feed's per-key rows, for last-used and the owning client. */
  usageKeys: AiUsageKey[];
  /** The names the gateway serves now, by name. */
  servedModels: string[];
  /** The saved default model; empty while none is saved. */
  defaultModel: string;
  /** The status view a generate, a revoke or an apply answered with. */
  onChanged: (view: CliproxyApiStatusView) => void;
}

export function AiAccessPanel({
  endpoint,
  keys,
  usageKeys,
  servedModels,
  defaultModel,
  onChanged,
}: AiAccessPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [isNaming, setIsNaming] = useState(false);
  const [name, setName] = useState("");
  const [freshKeyId, setFreshKeyId] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The picked default model; null until a row is picked.
  const [pickedModel, setPickedModel] = useState<string | null>(null);
  const [isModelBusy, setIsModelBusy] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [modelNotice, setModelNotice] = useState<string | null>(null);

  const isSavedServed =
    defaultModel === "" || servedModels.includes(defaultModel);
  const savedRow = defaultModel || (servedModels[0] ?? "");
  const shownRow = pickedModel ?? savedRow;
  const isModelDirty = pickedModel !== null && pickedModel !== savedRow;
  const modelOptions: PickerOption[] = [
    ...(isSavedServed
      ? []
      : [
          {
            id: defaultModel,
            name: defaultModel,
            detail: t("ui.ai.default_model_not_served"),
          },
        ]),
    ...servedModels.map((model) => ({ id: model, name: model })),
  ];

  const usageByKeyId = new Map(usageKeys.map((entry) => [entry.key_id, entry]));
  const ordered =
    freshKeyId === null
      ? keys
      : [
          ...keys.filter((key) => key.id === freshKeyId),
          ...keys.filter((key) => key.id !== freshKeyId),
        ];

  const handleGenerate = async () => {
    setIsBusy(true);
    setError(null);
    try {
      const known = new Set(keys.map((key) => key.id));
      const next = await apiPost<CliproxyApiStatusView>(KEY_ADD_PATH, {
        name: name.trim() || t("ui.ai.key_default_name"),
      });
      const created = next.client_keys.find((key) => !known.has(key.id));
      onChanged(next);
      setFreshKeyId(created?.id ?? null);
      setName("");
      setIsNaming(false);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    setIsBusy(true);
    setError(null);
    try {
      onChanged(
        await apiPost<CliproxyApiStatusView>("/hub/ai/gateway/key/remove", {
          key_id: keyId,
        }),
      );
      if (freshKeyId === keyId) {
        setFreshKeyId(null);
      }
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleApplyModel = async () => {
    setIsModelBusy(true);
    setModelError(null);
    setModelNotice(null);
    try {
      onChanged(
        await apiPost<CliproxyApiStatusView>(GATEWAY_SET_PATH, {
          default_model: pickedModel,
        }),
      );
      setPickedModel(null);
      setModelNotice(t("ui.api.applied"));
    } catch (cause: unknown) {
      setModelError(describeError(cause));
    } finally {
      setIsModelBusy(false);
    }
  };

  const askRevoke = (value: CliproxyApiKeyView, clientName: string | null) => {
    confirm.ask({
      title: t("ui.ai.revoke_title", { name: value.name }),
      body:
        clientName === null
          ? t("ui.ai.revoke_body")
          : t("ui.ai.revoke_client_body", { client: clientName }),
      confirmLabel: t("ui.ai.revoke"),
      onConfirm: () => void handleRevoke(value.id),
    });
  };

  return (
    <section
      className={`settings_group ${isModelDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.ai.access_title")}</h2>
        {!isNaming && (
          <button
            type="button"
            className="button credentials_section_action"
            disabled={isBusy}
            onClick={() => {
              setIsNaming(true);
            }}
          >
            <Icon name="plus" size={14} />
            {t("ui.ai.generate_key")}
          </button>
        )}
      </div>
      <p className="field_hint">{t("ui.ai.access_hint")}</p>

      <CopyRow label={t("ui.ai.endpoint")} value={endpoint} />

      <Picker
        options={modelOptions}
        value={shownRow === "" ? null : shownRow}
        onChange={(model) => {
          setPickedModel(model);
          setModelNotice(null);
        }}
        label={t("ui.ai.default_model")}
        isDisabled={servedModels.length === 0 || isModelBusy}
      />

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      {isNaming && (
        <div className="ai_key_add">
          <input
            className="input"
            placeholder={t("ui.ai.key_name_placeholder")}
            value={name}
            autoFocus
            onChange={(event) => {
              setName(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleGenerate();
              }
            }}
          />
          <div className="ai_key_add_actions">
            <button
              type="button"
              className="button button--ghost"
              onClick={() => {
                setIsNaming(false);
                setName("");
              }}
            >
              {t("ui.ai.cancel")}
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={isBusy}
              onClick={() => void handleGenerate()}
            >
              <Icon name="check" size={14} />
              {t("ui.ai.generate")}
            </button>
          </div>
        </div>
      )}

      {keys.length === 0 ? (
        <div className="placeholder">
          <span>{t("ui.ai.keys_empty")}</span>
          <span className="faint">{t("ui.ai.keys_empty_hint")}</span>
        </div>
      ) : (
        <div className="ai_keys">
          {ordered.map((value) =>
            value.id === freshKeyId ? (
              <FreshKeyRow
                key={value.id}
                value={value}
                onDismiss={() => {
                  setFreshKeyId(null);
                }}
              />
            ) : (
              <KeyRow
                key={value.id}
                value={value}
                usage={usageByKeyId.get(value.id) ?? null}
                isBusy={isBusy}
                onRevoke={() => {
                  askRevoke(
                    value,
                    usageByKeyId.get(value.id)?.client_name ?? null,
                  );
                }}
              />
            ),
          )}
        </div>
      )}
      <ApplyBar
        isDirty={isModelDirty}
        isBusy={isModelBusy}
        label={t("ui.ai.access_apply")}
        hint={t("ui.ai.access_apply_hint")}
        warning={t("ui.ai.access_apply_warning")}
        error={modelError}
        notice={modelNotice}
        onReset={() => {
          setPickedModel(null);
          setModelError(null);
          setModelNotice(null);
        }}
        onApply={() => void handleApplyModel()}
      />
      {confirm.modal}
    </section>
  );
}

interface FreshKeyRowProps {
  value: CliproxyApiKeyView;
  onDismiss: () => void;
}

/** The key as it lands: at the top, spelled out, with the copy to hand. */
function FreshKeyRow({ value, onDismiss }: FreshKeyRowProps) {
  const handleCopy = async () => {
    try {
      await copyText(value.key);
    } catch {
      // The value is on screen; copying by hand still works.
    }
    onDismiss();
  };

  return (
    <div className="ai_key_fresh">
      <div className="ai_key_fresh_head">
        <span className="ai_key_name">{value.name}</span>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={onDismiss}
        >
          {t("ui.ai.dismiss")}
        </button>
      </div>
      <div className="ai_key_fresh_value mono">{value.key}</div>
      <div className="ai_key_fresh_foot">
        <span className="field_hint">{t("ui.ai.fresh_key_hint")}</span>
        <button
          type="button"
          className="button button--primary"
          onClick={() => void handleCopy()}
        >
          <Icon name="file" size={14} />
          {t("ui.ai.copy_key")}
        </button>
      </div>
    </div>
  );
}

interface KeyRowProps {
  value: CliproxyApiKeyView;
  usage: AiUsageKey | null;
  isBusy: boolean;
  onRevoke: () => void;
}

function KeyRow({ value, usage, isBusy, onRevoke }: KeyRowProps) {
  const [isRevealed, setIsRevealed] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  const hasUsage = usage !== null && usage.requests > 0;
  const clientName = usage?.client_name ?? null;

  const handleCopy = async () => {
    try {
      await copyText(value.key);
      setIsCopied(true);
      window.setTimeout(() => {
        setIsCopied(false);
      }, COPIED_CLEAR_MS);
    } catch {
      // The value can be revealed and copied by hand.
    }
  };

  return (
    <div className="ai_key_row">
      <span className="ai_key_name">{value.name}</span>
      <span className="ai_key_value mono">
        {isRevealed ? value.key : MASKED_KEY}
      </span>
      <span className="ai_key_meta">
        <span className="ai_key_used">
          {hasUsage
            ? t("ui.ai.key_used", { ago: formatTimeAgo(usage.last_seen_at) })
            : t("ui.ai.key_never_used")}
        </span>
        {clientName !== null && (
          <span className="ai_key_device mono">{clientName}</span>
        )}
      </span>
      <span className="ai_key_actions">
        <button
          type="button"
          className="ai_key_action"
          title={isRevealed ? t("ui.ai.hide") : t("ui.ai.reveal")}
          aria-label={isRevealed ? t("ui.ai.hide") : t("ui.ai.reveal")}
          onClick={() => {
            setIsRevealed((current) => !current);
          }}
        >
          <Icon name={isRevealed ? "eye_off" : "eye"} size={13} />
        </button>
        <button
          type="button"
          className="ai_key_action"
          title={isCopied ? t("ui.ai.copied") : t("ui.ai.copy")}
          aria-label={isCopied ? t("ui.ai.copied") : t("ui.ai.copy")}
          onClick={() => void handleCopy()}
        >
          <Icon name={isCopied ? "check" : "file"} size={13} />
        </button>
        <button
          type="button"
          className="ai_key_action ai_key_action--danger"
          title={t("ui.ai.revoke")}
          aria-label={t("ui.ai.revoke")}
          disabled={isBusy}
          onClick={onRevoke}
        >
          <Icon name="trash" size={13} />
        </button>
      </span>
    </div>
  );
}

interface CopyRowProps {
  label: string;
  value: string;
}

function CopyRow({ label, value }: CopyRowProps) {
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await copyText(value);
      setIsCopied(true);
      window.setTimeout(() => {
        setIsCopied(false);
      }, COPIED_CLEAR_MS);
    } catch {
      // The value is visible; copying by hand still works.
    }
  };

  return (
    <div className="ai_copy_row">
      <span className="ai_copy_label">{label}</span>
      <span className="ai_copy_value">{value}</span>
      <button
        type="button"
        className="button button--small"
        onClick={() => void handleCopy()}
      >
        <Icon name={isCopied ? "check" : "file"} size={13} />
        {isCopied ? t("ui.ai.copied") : t("ui.ai.copy")}
      </button>
    </div>
  );
}
