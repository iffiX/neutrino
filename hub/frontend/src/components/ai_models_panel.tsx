import { useState } from "react";
import { Link } from "react-router-dom";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Picker } from "./picker";
import { providerLabel } from "../ai_provider_labels";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
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
 * given for it. A cloud name's length and its input and output price per
 * million tokens are the panel's draft. An Ollama name's length is
 * read-only, with each machine of its pool under it, and it has no price.
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

/** The typed values of each cloud name. */
type ModelTexts = Record<string, ModelText>;

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

function textsOf(view: AiModelResponse): ModelTexts {
  return Object.fromEntries(
    view.cloud.map((row) => [row.model, textOfRow(row)]),
  );
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
 * The price a row's fields give: a set price, null for no price, or
 * undefined while the fields hold no valid price.
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
  const { draft, setDraft, reset } = useDraft(resource.data, textsOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const view = resource.data;
  const cloud = view?.cloud ?? [];
  const ollama = view?.ollama ?? [];
  const texts = draft ?? {};
  const textOf = (row: AiCloudModelView) => texts[row.model] ?? textOfRow(row);
  const lengthChanged = cloud.filter((row) =>
    isLengthChanged(row, textOf(row)),
  );
  const priceChanged = cloud.filter((row) => isPriceChanged(row, textOf(row)));
  const isDirty = lengthChanged.length > 0 || priceChanged.length > 0;
  const isValid = cloud.every(
    (row) =>
      parsedLength(textOf(row).length) !== null &&
      draftPrice(row, textOf(row)) !== undefined,
  );

  const handleApply = async () => {
    const lengths: NonNullable<AiModelUpdate["lengths"]> = {};
    for (const row of lengthChanged) {
      const length = parsedLength(textOf(row).length);
      if (length === null) {
        return;
      }
      lengths[row.model] =
        length === row.default_context_length ? null : length;
    }
    const prices: NonNullable<AiModelUpdate["prices"]> = {};
    for (const row of priceChanged) {
      const price = draftPrice(row, textOf(row));
      if (price === undefined) {
        return;
      }
      prices[row.model] =
        price === null || isDefaultPrice(row, price) ? null : price;
    }
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      resource.setData(
        await apiPost<AiModelResponse>(MODEL_SET_PATH, { lengths, prices }),
      );
      setNotice(t("ui.api.applied"));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const changeText = (row: AiCloudModelView, change: Partial<ModelText>) => {
    setDraft((current) => ({
      ...current,
      [row.model]: { ...(current[row.model] ?? textOfRow(row)), ...change },
    }));
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
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
              <span className="ai_models_head_number">
                {t("ui.ai.context_col_tokens")}
              </span>
              <span className="ai_models_head_number">
                {t("ui.ai.price_col_input")}
              </span>
              <span className="ai_models_head_number">
                {t("ui.ai.price_col_output")}
              </span>
              <span className="ai_models_head_unit">
                {t("ui.ai.price_unit")}
              </span>
            </div>
            {cloud.map((row) => (
              <CloudModelRow
                key={row.model}
                row={row}
                text={textOf(row)}
                isDisabled={isBusy}
                onChange={(change) => {
                  changeText(row, change);
                }}
              />
            ))}
            {ollama.map((row) => (
              <OllamaModelRow key={row.model} row={row} />
            ))}
          </div>
        ))}

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        isApplyDisabled={!isValid}
        label={t("ui.ai.models_apply")}
        hint={t("ui.ai.models_apply_hint")}
        error={error}
        notice={notice}
        onReset={() => {
          reset();
          setError(null);
          setNotice(null);
        }}
        onApply={() => void handleApply()}
      />
    </section>
  );
}

interface CloudModelRowProps {
  row: AiCloudModelView;
  text: ModelText;
  isDisabled: boolean;
  onChange: (change: Partial<ModelText>) => void;
}

/** A cloud name: its sources, its length and its price as fields, each
 * with the way back to its default while it holds another value. */
function CloudModelRow({
  row,
  text,
  isDisabled,
  onChange,
}: CloudModelRowProps) {
  const fallback = row.default_price;
  const isDefaultLength =
    text.length.trim() === String(row.default_context_length);
  const isLengthValid = parsedLength(text.length) !== null;
  const isPriceValid = draftPrice(row, text) !== undefined;
  const isPriceDefault =
    fallback === null ||
    (text.input.trim() === String(fallback.input) &&
      text.output.trim() === String(fallback.output) &&
      text.currency === fallback.currency);
  return (
    <div className="ai_models_row">
      <span className="ai_models_model mono" title={row.model}>
        {row.model}
      </span>
      <SourceChips sources={row.sources} />
      <span className="ai_models_field ai_models_length">
        {!isDefaultLength && (
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={isDisabled}
            onClick={() => {
              onChange({ length: String(row.default_context_length) });
            }}
          >
            {t("ui.ai.context_reset", { length: row.default_context_length })}
          </button>
        )}
        <input
          className="input ai_models_input ai_models_input--length"
          inputMode="numeric"
          aria-label={t("ui.ai.context_length_of", { model: row.model })}
          value={text.length}
          disabled={isDisabled}
          onChange={(event) => {
            onChange({ length: event.target.value });
          }}
        />
      </span>
      <div className="ai_models_prices">
        <span className="ai_models_field">
          {!isPriceDefault && fallback !== null && (
            <button
              type="button"
              className="button button--ghost button--small"
              disabled={isDisabled}
              onClick={() => {
                onChange({
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
          <span className="ai_models_field_word">
            {t("ui.ai.price_col_input")}
          </span>
          <input
            className="input ai_models_input"
            inputMode="decimal"
            aria-label={t("ui.ai.price_input_of", { model: row.model })}
            placeholder={t("ui.ai.no_price")}
            value={text.input}
            disabled={isDisabled}
            onChange={(event) => {
              onChange({ input: event.target.value });
            }}
          />
        </span>
        <span className="ai_models_field">
          <span className="ai_models_field_word">
            {t("ui.ai.price_col_output")}
          </span>
          <input
            className="input ai_models_input"
            inputMode="decimal"
            aria-label={t("ui.ai.price_output_of", { model: row.model })}
            placeholder={t("ui.ai.no_price")}
            value={text.output}
            disabled={isDisabled}
            onChange={(event) => {
              onChange({ output: event.target.value });
            }}
          />
        </span>
        <Picker
          className="ai_models_currency"
          options={CURRENCY_OPTIONS.map((option) => ({
            id: option.id,
            name: t(option.labelKey),
          }))}
          value={text.currency}
          onChange={(id) => {
            onChange({ currency: id as AiPriceCurrency });
          }}
          label={t("ui.ai.price_currency_of", { model: row.model })}
          isLabelHidden
          isDisabled={isDisabled}
        />
      </div>
      {!isLengthValid && (
        <span className="field_error ai_models_error">
          {t("code.context_length_invalid", {
            min: CONTEXT_LENGTH_MIN,
            max: CONTEXT_LENGTH_MAX,
          })}
        </span>
      )}
      {!isPriceValid && (
        <span className="field_error ai_models_error">
          {t("code.price_invalid", { min: PRICE_MIN, max: PRICE_MAX })}
        </span>
      )}
    </div>
  );
}

/** An Ollama name: the Ollama chip and its cloud sources, its length, and
 * under it one line per machine of its pool. */
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
