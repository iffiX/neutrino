import { useId, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Picker } from "./picker";
import { apiPost, describeApplyFailure, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { gpuName } from "../ollama_gpus";
import { useDraft } from "../use_draft";
import { isFailing, useSettledApply } from "../use_settled_apply";
import type { ReportedModule } from "../use_settled_apply";
import type {
  ApplyResult,
  DeviceGpuInfo,
  OllamaDeviceView,
  OllamaGpuSetting,
  OllamaSettingsUpdate,
} from "../api_types";

import "./ollama_settings.css";

/**
 * **Settings** of the Ollama module on one machine: how long a model a
 * request loaded stays in memory, the most tokens a loaded model holds,
 * and which of the machine's GPUs the server uses, one checkbox per GPU of
 * its last report. Applying stores them and restarts the server, and holds
 * until the machine reports the module where the hub asks it.
 */

/** The idle unload times, as `OLLAMA_KEEP_ALIVE` spells them. */
const KEEP_ALIVE_CHOICES: { id: string; key: string }[] = [
  { id: "5m", key: "ui.ollama.keep_alive_5m" },
  { id: "30m", key: "ui.ollama.keep_alive_30m" },
  { id: "1h", key: "ui.ollama.keep_alive_1h" },
  { id: "4h", key: "ui.ollama.keep_alive_4h" },
  { id: "-1", key: "ui.ollama.keep_alive_never" },
];

/** The least and the most context length, in tokens. */
const CONTEXT_LENGTH_MIN = 4096;
const CONTEXT_LENGTH_MAX = 262144;

/** The system whose one GPU is Apple's and takes no choice. */
const DARWIN = "darwin";

/** What an agent older than the module reports for it. */
const STATE_UNSUPPORTED = "unsupported";

/** The state of a module whose server runs, which an apply restarts. */
const STATE_RUNNING = "running";

/** The `want` of a module a person pressed Start on. */
const WANT_RUNNING = "running";

interface OllamaSettingsProps {
  /** The machine Ollama runs on. */
  deviceId: string;
  /** Where the module answers: `/agent/module/ollama`. */
  basePath: string;
  /** The Ollama view: the stored settings and the machine's GPUs. */
  saved: OllamaDeviceView;
  /** Why nothing here can be applied, or null while it can. */
  blockedHint: string | null;
  /** The machine's system: `linux`, `windows` or `darwin`. */
  platformOs: string;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
  /** Takes the view the stored settings give. */
  onSaved: (view: OllamaDeviceView) => void;
}

/** The form's own fields: the idle time, the context length's field text
 * and one tick per reported GPU. */
interface SettingsDraft {
  keep_alive: string;
  context_length: string;
  ticks: boolean[];
}

export function OllamaSettings({
  deviceId,
  basePath,
  saved,
  blockedHint,
  platformOs,
  want,
  onSaved,
}: OllamaSettingsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { draft, setDraft, isDirty, reset } = useDraft(saved, draftOf);
  const gpusLabelId = useId();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const report: ReportedModule = { state: saved.state, instances: [] };
  const settle = useSettledApply(report, want);

  if (draft === null) {
    return null;
  }

  const gpus = saved.resources.gpus;
  const isGpuShown = platformOs !== DARWIN && gpus.length > 0;
  const isUnsupported = saved.state === STATE_UNSUPPORTED;
  const contextLength = contextLengthOf(draft.context_length);
  const contextLengthError =
    contextLength === null
      ? t("code.ollama_context_length_invalid", {
          min: CONTEXT_LENGTH_MIN,
          max: CONTEXT_LENGTH_MAX,
        })
      : null;

  const apply = async () => {
    if (contextLength === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    settle.clear();
    const request: OllamaSettingsUpdate = {
      device_id: deviceId,
      keep_alive: draft.keep_alive,
      context_length: contextLength,
      gpus: gpuSettings(gpus, draft.ticks),
    };
    try {
      onSaved(await apiPost<OllamaDeviceView>(`${basePath}/set`, request));
      const result = await apiPost<ApplyResult>(`${basePath}/apply`, {
        device_id: deviceId,
      });
      if (!result.is_applied) {
        setError(describeApplyFailure(result));
        return;
      }
      settle.begin();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.ollama.settings_title")}</h2>
      </div>
      <div className="ollama_settings_fields">
        <Picker
          options={KEEP_ALIVE_CHOICES.map((choice) => ({
            id: choice.id,
            name: t(choice.key),
          }))}
          value={draft.keep_alive}
          onChange={(keepAlive) => {
            setDraft({ ...draft, keep_alive: keepAlive });
          }}
          label={t("ui.ollama.keep_alive")}
          isDisabled={blockedHint !== null || isUnsupported}
        />
        <label className="field">
          <span className="field_label">{t("ui.ollama.context_length")}</span>
          <input
            className="input"
            type="number"
            inputMode="numeric"
            min={CONTEXT_LENGTH_MIN}
            max={CONTEXT_LENGTH_MAX}
            step={1}
            value={draft.context_length}
            disabled={blockedHint !== null || isUnsupported}
            onChange={(event) => {
              setDraft({ ...draft, context_length: event.target.value });
            }}
          />
          {contextLengthError !== null && (
            <span className="field_error">{contextLengthError}</span>
          )}
        </label>
        {isGpuShown && (
          <div
            className="field ollama_settings_gpus"
            role="group"
            aria-labelledby={gpusLabelId}
          >
            <span className="field_label" id={gpusLabelId}>
              {t("ui.ollama.gpus")}
            </span>
            {gpus.map((gpu, place) => (
              <label key={place} className="ollama_settings_gpu">
                <input
                  type="checkbox"
                  checked={draft.ticks[place] ?? true}
                  disabled={blockedHint !== null || isUnsupported}
                  onChange={(event) => {
                    const ticks = [...draft.ticks];
                    ticks[place] = event.target.checked;
                    setDraft({ ...draft, ticks });
                  }}
                />
                <span>{gpuName(gpu, place)}</span>
              </label>
            ))}
          </div>
        )}
      </div>
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy || settle.isSettling}
        label={t("ui.ollama.settings_apply")}
        hint={
          want !== WANT_RUNNING
            ? t("ui.modules.stopped_hint")
            : t("ui.ollama.settings_apply_hint")
        }
        warning={
          isDirty && saved.state === STATE_RUNNING
            ? t("ui.ollama.settings_restart_warning")
            : undefined
        }
        blockedHint={blockedHint}
        isApplyDisabled={isUnsupported || contextLengthError !== null}
        error={error}
        notice={
          settle.isApplied && !isFailing(report) ? t("ui.api.applied") : null
        }
        onReset={() => {
          reset();
          setError(null);
          settle.clear();
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** What the form starts from: the stored idle time and context length, and
 * a tick per GPU of the report, every card ticked while no list is stored,
 * otherwise the stored card at the same place and of the same vendor, a
 * card the list does not name unticked. */
function draftOf(view: OllamaDeviceView): SettingsDraft {
  const stored = view.gpus;
  return {
    keep_alive: view.keep_alive,
    context_length: String(view.context_length),
    ticks: view.resources.gpus.map((gpu, place) => {
      if (stored === null) {
        return true;
      }
      const held = stored[place];
      return held !== undefined && held.vendor === gpu.vendor && held.is_used;
    }),
  };
}

/** The context length a field's text names: a whole number of tokens
 * within the bounds, null for any other text. */
function contextLengthOf(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) {
    return null;
  }
  const value = Number(text.trim());
  return value >= CONTEXT_LENGTH_MIN && value <= CONTEXT_LENGTH_MAX
    ? value
    : null;
}

/** The GPUs as the settings store them: null while every card is ticked,
 * otherwise each card of the report with its tick. */
function gpuSettings(
  gpus: DeviceGpuInfo[],
  ticks: boolean[],
): OllamaGpuSetting[] | null {
  if (gpus.every((_gpu, place) => ticks[place] ?? true)) {
    return null;
  }
  return gpus.map((gpu, place) => ({
    vendor: gpu.vendor,
    is_used: ticks[place] ?? true,
  }));
}
