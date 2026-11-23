import { useState } from "react";
import { Link } from "react-router-dom";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { providerLabel } from "../ai_provider_labels";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { HUB_EVENT_AI_USAGE, HUB_EVENT_CONFIG } from "../use_hub_events";
import type {
  AiCloudContextView,
  AiContextResponse,
  AiContextSourceView,
  AiContextUpdate,
  AiOllamaContextView,
} from "../api_types";

import "./ai_context_panel.css";

/**
 * The Context length panel of the AI page: one row for each name the
 * gateway serves, the cloud names by name and then the Ollama names by
 * name, each with where it comes from and the length every machine's AI
 * tools are given for it. A cloud name's length is the panel's draft; an
 * Ollama name's is read-only, with each machine of its pool under it.
 */

const CONTEXT_PATH = "/hub/ai/context";
const CONTEXT_SET_PATH = "/hub/ai/context/set";
// What moves the lengths: the gateway's counters or served list, and any
// write under config/.
const CONTEXT_INVALIDATE_ON = [
  { type: HUB_EVENT_AI_USAGE },
  { type: HUB_EVENT_CONFIG },
];
/** The lengths a person may set. */
const CONTEXT_LENGTH_MIN = 4096;
const CONTEXT_LENGTH_MAX = 10_000_000;

/** The typed length of each cloud name. */
type ContextTexts = Record<string, string>;

/** The length in force for a cloud name: the one set, else the default. */
function lengthOf(row: AiCloudContextView): number {
  return row.context_length ?? row.default_context_length;
}

function textsOf(view: AiContextResponse): ContextTexts {
  return Object.fromEntries(
    view.cloud.map((row) => [row.model, String(lengthOf(row))]),
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

/** A source's chip: an account's service name, or a provider's name. */
function sourceLabel(source: AiContextSourceView): string {
  return source.origin === "account" ? providerLabel(source.name) : source.name;
}

/** The machine page on its Ollama tab, with its panels open. */
function ollamaSettingsPath(deviceId: string): string {
  return `/agents/${encodeURIComponent(deviceId)}?module=ollama&configure=1`;
}

export function AiContextPanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<AiContextResponse>(CONTEXT_PATH, {
    invalidateOn: CONTEXT_INVALIDATE_ON,
  });
  const { draft, setDraft, reset } = useDraft(resource.data, textsOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const view = resource.data;
  const cloud = view?.cloud ?? [];
  const ollama = view?.ollama ?? [];
  const texts = draft ?? {};
  const textOf = (row: AiCloudContextView) =>
    texts[row.model] ?? String(lengthOf(row));
  const changed = cloud.filter(
    (row) => textOf(row).trim() !== String(lengthOf(row)),
  );
  const isValid = cloud.every((row) => parsedLength(textOf(row)) !== null);

  const handleApply = async () => {
    const lengths: AiContextUpdate["lengths"] = {};
    for (const row of changed) {
      const length = parsedLength(textOf(row));
      if (length === null) {
        return;
      }
      lengths[row.model] =
        length === row.default_context_length ? null : length;
    }
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      resource.setData(
        await apiPost<AiContextResponse>(CONTEXT_SET_PATH, { lengths }),
      );
      setNotice(t("ui.api.applied"));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section
      className={`settings_group ${changed.length > 0 ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.ai.context_title")}</h2>
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
          <div className="ai_context_list">
            <div className="ai_context_head">
              <span>{t("ui.ai.context_col_model")}</span>
              <span>{t("ui.ai.context_col_source")}</span>
              <span className="ai_context_head_tokens">
                {t("ui.ai.context_col_tokens")}
              </span>
            </div>
            {cloud.map((row) => (
              <CloudContextRow
                key={row.model}
                row={row}
                text={textOf(row)}
                isDisabled={isBusy}
                onChange={(text) => {
                  setDraft((current) => ({ ...current, [row.model]: text }));
                }}
              />
            ))}
            {ollama.map((row) => (
              <OllamaContextRow key={row.model} row={row} />
            ))}
          </div>
        ))}

      <ApplyBar
        isDirty={changed.length > 0}
        isBusy={isBusy}
        isApplyDisabled={!isValid}
        label={t("ui.ai.context_apply")}
        hint={t("ui.ai.context_apply_hint")}
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

interface CloudContextRowProps {
  row: AiCloudContextView;
  text: string;
  isDisabled: boolean;
  onChange: (text: string) => void;
}

/** A cloud name: its sources, and its length as a field, with the way back
 * to the default while it holds another number. */
function CloudContextRow({
  row,
  text,
  isDisabled,
  onChange,
}: CloudContextRowProps) {
  const isDefault = text.trim() === String(row.default_context_length);
  const isValid = parsedLength(text) !== null;
  return (
    <div className="ai_context_row">
      <span className="ai_context_model mono" title={row.model}>
        {row.model}
      </span>
      <SourceChips sources={row.sources} />
      <span className="ai_context_field">
        {!isDefault && (
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={isDisabled}
            onClick={() => {
              onChange(String(row.default_context_length));
            }}
          >
            {t("ui.ai.context_reset", { length: row.default_context_length })}
          </button>
        )}
        <input
          className="input ai_context_input"
          inputMode="numeric"
          aria-label={t("ui.ai.context_length_of", { model: row.model })}
          value={text}
          disabled={isDisabled}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      </span>
      {!isValid && (
        <span className="field_error ai_context_error">
          {t("code.context_length_invalid", {
            min: CONTEXT_LENGTH_MIN,
            max: CONTEXT_LENGTH_MAX,
          })}
        </span>
      )}
    </div>
  );
}

/** An Ollama name: the Ollama chip and its cloud sources, its length, and
 * under it one line per machine of its pool. */
function OllamaContextRow({ row }: { row: AiOllamaContextView }) {
  const valueClass = (length: number) =>
    `ai_context_source mono ${length === row.context_length ? "ai_context_source--in_force" : ""}`;
  return (
    <div className="ai_context_row">
      <span className="ai_context_model mono" title={row.model}>
        {row.model}
      </span>
      <SourceChips sources={row.sources} isOllama />
      <span className="ai_context_value mono">{row.context_length}</span>
      <span className="ai_context_machines">
        {row.machines.map((machine) => (
          <span key={machine.device_id} className="ai_context_machine">
            <Link
              to={ollamaSettingsPath(machine.device_id)}
              className="ai_context_machine_name"
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
  sources: AiContextSourceView[];
  /** Whether the Ollama chip comes first. */
  isOllama?: boolean;
}

/** One chip per source, the accounts and then the providers. */
function SourceChips({ sources, isOllama = false }: SourceChipsProps) {
  return (
    <span className="ai_context_sources">
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
