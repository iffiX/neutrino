import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { DialogFrame } from "./dialog_frame";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Picker } from "./picker";
import { Spinner } from "./spinner";
import { providerLabel } from "../ai_provider_labels";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_AI_USAGE, HUB_EVENT_CONFIG } from "../use_hub_events";
import type {
  AiCloudModelView,
  AiModelPrice,
  AiModelResponse,
  AiModelSourceView,
  AiModelUpdate,
  AiOllamaModelView,
  AiPriceCurrency,
} from "../api_types";

import "./ai_models_panel.css";

/**
 * The Models panel of the AI page: one row for each name the gateway
 * serves, the cloud names by name and then the Ollama names by name, each
 * with where it comes from and the length every machine's AI tools are
 * given for it. A cloud row's Configure opens a dialog with the name's
 * length and its input and output price per million tokens, and its Save
 * writes that one name. An Ollama name's length is read-only, with each
 * machine of its pool under the name, and it has no price.
 */

const MODEL_PATH = "/hub/ai/model";
const MODEL_SET_PATH = "/hub/ai/model/set";
// What moves the lengths and the prices: the gateway's counters or served
// list, and any write under config/.
const MODEL_INVALIDATE_ON = [
  { type: HUB_EVENT_AI_USAGE },
  { type: HUB_EVENT_CONFIG },
];
/** The lengths a person may set. */
const CONTEXT_LENGTH_MIN = 4096;
const CONTEXT_LENGTH_MAX = 10_000_000;
/** The prices a person may set, per million tokens. */
const PRICE_MIN = 0;
const PRICE_MAX = 10_000;
/** A number from 0 with at most 6 decimals. */
const PRICE_PATTERN = /^\d+(\.\d{1,6})?$/;
/** The currency of every default price. */
const DEFAULT_CURRENCY: AiPriceCurrency = "USD";

const CURRENCY_OPTIONS: { id: AiPriceCurrency; labelKey: string }[] = [
  { id: "USD", labelKey: "ui.ai.currency_usd" },
  { id: "CNY", labelKey: "ui.ai.currency_cny" },
];
const CURRENCY_SIGNS: Record<AiPriceCurrency, string> = { USD: "$", CNY: "¥" };

/** A cloud name's typed length and price. */
interface ModelText {
  length: string;
  input: string;
  output: string;
  currency: AiPriceCurrency;
}

/** The length in force for a cloud name: the one set, else the default. */
function lengthOf(row: AiCloudModelView): number {
  return row.context_length ?? row.default_context_length;
}

/** The values in force for a cloud name, as the fields show them. */
function textOfRow(row: AiCloudModelView): ModelText {
  const price = row.price ?? row.default_price;
  return {
    length: String(lengthOf(row)),
    input: price === null ? "" : String(price.input),
    output: price === null ? "" : String(price.output),
    currency: price?.currency ?? DEFAULT_CURRENCY,
  };
}

/** A typed length as a number, or null while it is no whole number in range. */
function parsedLength(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) {
    return null;
  }
  const length = Number(trimmed);
  return length >= CONTEXT_LENGTH_MIN && length <= CONTEXT_LENGTH_MAX
    ? length
    : null;
}

/** A typed price number, or null while it is no number in range. */
function parsedPrice(text: string): number | null {
  const trimmed = text.trim();
  if (!PRICE_PATTERN.test(trimmed)) {
    return null;
  }
  const price = Number(trimmed);
  return price >= PRICE_MIN && price <= PRICE_MAX ? price : null;
}

/**
 * The price the fields give: a set price, null for no price, or undefined
 * while the fields hold no valid price.
 *
 * Both fields empty are no price on a name with no default alone.
 */
function draftPrice(
  row: AiCloudModelView,
  text: ModelText,
): AiModelPrice | null | undefined {
  if (text.input.trim() === "" && text.output.trim() === "") {
    return row.default_price === null ? null : undefined;
  }
  const input = parsedPrice(text.input);
  const output = parsedPrice(text.output);
  if (input === null || output === null) {
    return undefined;
  }
  return { input, output, currency: text.currency };
}

/** Whether a price is the name's default, in the default's currency. */
function isDefaultPrice(row: AiCloudModelView, price: AiModelPrice): boolean {
  const fallback = row.default_price;
  return (
    fallback !== null &&
    price.input === fallback.input &&
    price.output === fallback.output &&
    price.currency === fallback.currency
  );
}

function isLengthChanged(row: AiCloudModelView, text: ModelText): boolean {
  return text.length.trim() !== String(lengthOf(row));
}

function isPriceChanged(row: AiCloudModelView, text: ModelText): boolean {
  const saved = textOfRow(row);
  return (
    text.input.trim() !== saved.input ||
    text.output.trim() !== saved.output ||
    text.currency !== saved.currency
  );
}

/** A price with its sign: two decimals, or more where it has them. */
function formatPrice(currency: AiPriceCurrency, value: number): string {
  const cents = value * 100;
  const digits =
    Math.abs(cents - Math.round(cents)) < 1e-9
      ? value.toFixed(2)
      : String(value);
  return `${CURRENCY_SIGNS[currency]}${digits}`;
}

/** A source's chip: an account's service name, or a provider's name. */
function sourceLabel(source: AiModelSourceView): string {
  return source.origin === "account" ? providerLabel(source.name) : source.name;
}

/** The machine page on its Ollama tab, with its panels open. */
function ollamaSettingsPath(deviceId: string): string {
  return `/agents/${encodeURIComponent(deviceId)}?module=ollama&configure=1`;
}

export function AiModelsPanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<AiModelResponse>(MODEL_PATH, {
    invalidateOn: MODEL_INVALIDATE_ON,
  });
  const [configuring, setConfiguring] = useState<string | null>(null);

  const view = resource.data;
  const cloud = view?.cloud ?? [];
  const ollama = view?.ollama ?? [];
  const configured = cloud.find((row) => row.model === configuring) ?? null;

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.ai.models_title")}</h2>
      </div>

      {resource.error !== null && view === null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {view === null && resource.error === null && (
        <div className="skeleton" style={{ height: 160 }} />
      )}

      {view !== null &&
        (cloud.length === 0 && ollama.length === 0 ? (
          <div className="placeholder">
            <span>{t("ui.ai.context_empty")}</span>
          </div>
        ) : (
          <div className="ai_models_list">
            <div className="ai_models_head">
              <span>{t("ui.ai.context_col_model")}</span>
              <span>{t("ui.ai.context_col_source")}</span>
              <span className="ai_models_head_tokens">
                {t("ui.ai.context_col_tokens")}
              </span>
            </div>
            {cloud.map((row) => (
              <div key={row.model} className="ai_models_row">
                <span className="ai_models_model mono" title={row.model}>
                  {row.model}
                </span>
                <SourceChips sources={row.sources} />
                <span className="ai_models_value mono">{lengthOf(row)}</span>
                <button
                  type="button"
                  className="button button--ghost button--small ai_models_configure"
                  onClick={() => {
                    setConfiguring(row.model);
                  }}
                >
                  {t("ui.ai.model_configure")}
                </button>
              </div>
            ))}
            {ollama.map((row) => (
              <OllamaModelRow key={row.model} row={row} />
            ))}
          </div>
        ))}

      {configured !== null && (
        <ModelDialog
          row={configured}
          onSaved={(saved) => {
            resource.setData(saved);
            setConfiguring(null);
          }}
          onCancel={() => {
            setConfiguring(null);
          }}
        />
      )}
    </section>
  );
}

interface ModelDialogProps {
  row: AiCloudModelView;
  /** The write landed, with the view it returned. */
  onSaved: (view: AiModelResponse) => void;
  onCancel: () => void;
}

/** A cloud name's dialog: its length and its price, each with the way back
 * to its default, written for that one name by Save. */
function ModelDialog({ row, onSaved, onCancel }: ModelDialogProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const lengthId = useId();
  const [text, setText] = useState<ModelText>(() => textOfRow(row));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fallback = row.default_price;
  const length = parsedLength(text.length);
  const price = draftPrice(row, text);
  const isLengthValid = length !== null;
  const isPriceValid = price !== undefined;
  const isChanged = isLengthChanged(row, text) || isPriceChanged(row, text);
  const isDefaultLength =
    text.length.trim() === String(row.default_context_length);
  const isPriceDefault =
    fallback === null ||
    (text.input.trim() === String(fallback.input) &&
      text.output.trim() === String(fallback.output) &&
      text.currency === fallback.currency);

  const change = (next: Partial<ModelText>) => {
    setText((current) => ({ ...current, ...next }));
  };

  const handleSave = async () => {
    if (length === null || price === undefined) {
      return;
    }
    const update: AiModelUpdate = {};
    if (isLengthChanged(row, text)) {
      update.lengths = {
        [row.model]: length === row.default_context_length ? null : length,
      };
    }
    if (isPriceChanged(row, text)) {
      update.prices = {
        [row.model]:
          price === null || isDefaultPrice(row, price) ? null : price,
      };
    }
    setIsSaving(true);
    setError(null);
    try {
      onSaved(await apiPost<AiModelResponse>(MODEL_SET_PATH, update));
    } catch (cause: unknown) {
      setError(describeError(cause));
      setIsSaving(false);
    }
  };

  return (
    <DialogFrame
      title={t("ui.ai.model_configure_title", { model: row.model })}
      hasHeadClose={false}
      onClose={onCancel}
      foot={
        <>
          <button
            type="button"
            className="button button--ghost"
            onClick={onCancel}
          >
            {t("ui.ai.cancel")}
          </button>
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={!isChanged || !isLengthValid || !isPriceValid || isSaving}
            onClick={() => void handleSave()}
          >
            {isSaving ? <Spinner size={13} /> : <Icon name="check" size={14} />}
            {isSaving ? t("ui.ai.saving") : t("ui.ai.model_save")}
          </button>
        </>
      }
    >
      <div className="field">
        <label className="field_label" htmlFor={lengthId}>
          {t("ui.ai.model_context_length")}
        </label>
        <div className="ai_model_dialog_line">
          <input
            id={lengthId}
            className="input ai_model_dialog_length"
            inputMode="numeric"
            value={text.length}
            autoFocus
            onChange={(event) => {
              change({ length: event.target.value });
            }}
          />
          {!isDefaultLength && (
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() => {
                change({ length: String(row.default_context_length) });
              }}
            >
              {t("ui.ai.context_reset", {
                length: row.default_context_length,
              })}
            </button>
          )}
        </div>
        {!isLengthValid && (
          <span className="field_error">
            {t("code.context_length_invalid", {
              min: CONTEXT_LENGTH_MIN,
              max: CONTEXT_LENGTH_MAX,
            })}
          </span>
        )}
      </div>

      <div className="field">
        <div className="ai_model_dialog_prices">
          <label className="field">
            <span className="field_label">{t("ui.ai.price_input")}</span>
            <input
              className="input"
              inputMode="decimal"
              placeholder={t("ui.ai.no_price")}
              value={text.input}
              onChange={(event) => {
                change({ input: event.target.value });
              }}
            />
          </label>
          <label className="field">
            <span className="field_label">{t("ui.ai.price_output")}</span>
            <input
              className="input"
              inputMode="decimal"
              placeholder={t("ui.ai.no_price")}
              value={text.output}
              onChange={(event) => {
                change({ output: event.target.value });
              }}
            />
          </label>
          <Picker
            options={CURRENCY_OPTIONS.map((option) => ({
              id: option.id,
              name: t(option.labelKey),
            }))}
            value={text.currency}
            onChange={(id) => {
              change({ currency: id as AiPriceCurrency });
            }}
            label={t("ui.ai.price_currency")}
          />
        </div>
        <div className="ai_model_dialog_line ai_model_dialog_line--hint">
          <span className="field_hint">{t("ui.ai.price_unit")}</span>
          {!isPriceDefault && fallback !== null && (
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() => {
                change({
                  input: String(fallback.input),
                  output: String(fallback.output),
                  currency: fallback.currency,
                });
              }}
            >
              {t("ui.ai.price_reset", {
                price: `${formatPrice(fallback.currency, fallback.input)} / ${formatPrice(fallback.currency, fallback.output)}`,
              })}
            </button>
          )}
        </div>
        {!isPriceValid && (
          <span className="field_error">
            {t("code.price_invalid", { min: PRICE_MIN, max: PRICE_MAX })}
          </span>
        )}
      </div>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
    </DialogFrame>
  );
}

/** An Ollama name: the Ollama chip and its cloud sources, its length, and
 * under the name one line per machine of its pool. */
function OllamaModelRow({ row }: { row: AiOllamaModelView }) {
  const valueClass = (length: number) =>
    `ai_models_source mono ${length === row.context_length ? "ai_models_source--in_force" : ""}`;
  return (
    <div className="ai_models_row">
      <span className="ai_models_model mono" title={row.model}>
        {row.model}
      </span>
      <SourceChips sources={row.sources} isOllama />
      <span className="ai_models_value mono">{row.context_length}</span>
      <span className="ai_models_machines">
        {row.machines.map((machine) => (
          <span key={machine.device_id} className="ai_models_machine">
            <Link
              to={ollamaSettingsPath(machine.device_id)}
              className="ai_models_machine_name"
            >
              {machine.name}
            </Link>
            <span className={valueClass(machine.setting_context_length)}>
              {t("ui.ai.context_setting", {
                length: machine.setting_context_length,
              })}
            </span>
            {machine.trained_context_length > 0 ? (
              <span className={valueClass(machine.trained_context_length)}>
                {t("ui.ai.context_trained", {
                  length: machine.trained_context_length,
                })}
              </span>
            ) : (
              <span />
            )}
          </span>
        ))}
      </span>
    </div>
  );
}

interface SourceChipsProps {
  sources: AiModelSourceView[];
  /** Whether the Ollama chip comes first. */
  isOllama?: boolean;
}

/** One chip per source, the accounts and then the providers. */
function SourceChips({ sources, isOllama = false }: SourceChipsProps) {
  return (
    <span className="ai_models_sources">
      {isOllama && (
        <span className="key_card_type">{t("ui.module_title.ollama")}</span>
      )}
      {sources.map((source) => (
        <span key={`${source.origin}:${source.id}`} className="key_card_type">
          {sourceLabel(source)}
        </span>
      ))}
    </span>
  );
}
