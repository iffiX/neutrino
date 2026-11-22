import { useEffect, useState } from "react";

import { ErrorPanel } from "./error_panel";
import { Meter } from "./meter";
import { OllamaSettings } from "./ollama_settings";
import { apiPath, apiPost, describeCode, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { formatBytes } from "../format_bytes";
import { formatTimeAgo } from "../format_duration";
import { gpuName } from "../ollama_gpus";
import { t, useLanguage } from "../i18n";
import { useConfirm } from "../use_confirm";
import { usePolledResource } from "../use_polled_resource";
import type { MeterTone } from "./meter";
import type {
  OllamaDeviceView,
  OllamaModel,
  OllamaModelRequest,
  OllamaPull,
} from "../api_types";

import "./ollama_panels.css";

/**
 * The Ollama module's Configure on one machine: **Settings**, then
 * **Models**, both drawn from one view read every few seconds. A person's
 * Ollama app on Windows or macOS takes no setting and has **Models** alone.
 *
 * **Models** opens with the machine's GPUs and memory, then a field to pull
 * any name Ollama takes, the pulls the hub runs for the machine, and one
 * list of the pulled models whose head and rows share their columns: name,
 * parameters, quantization, size, modified, memory and the buttons. A model
 * in memory shows how it splits between GPU and CPU; **Load** keeps a model
 * in memory until **Unload**. Each press acts at once. While the server
 * does not run, or the machine is offline, the panel shows that state
 * alone.
 */

interface OllamaPanelsProps {
  /** The machine Ollama runs on. */
  deviceId: string;
  /** Where the module answers: `/agent/module/ollama`. */
  basePath: string;
  isEditable: boolean;
  /** The machine's system: `linux`, `windows` or `darwin`. */
  platformOs: string;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
}

/** How often the view is read while a pull or a load runs, and otherwise. */
const BUSY_POLL_INTERVAL_MS = 2000;
const IDLE_POLL_INTERVAL_MS = 5000;

/** The placeholder of the pull field: a model name. */
const NAME_PLACEHOLDER = "qwen2.5:7b";

/** The states of a pull in the queue. */
const PULL_RUNNING = "running";
const PULL_QUEUED = "queued";
const PULL_FAILED = "failed";

/** What `details.found` says of a person's own Ollama app. */
const FOUND_APP = "app";

/** The word of a module that is not running, by its state. */
const STATE_KEYS: Record<string, string> = {
  stopped: "state.stopped",
  installed: "state.installed",
  absent: "state.absent",
};

/** The tones of the GPU's part of memory and of the system's. */
const GPU_TONE: MeterTone = "accent";
const SYSTEM_TONE: MeterTone = "secondary";

/** MiB in bytes, for the report's memory readings. */
const BYTES_PER_MIB = 1024 * 1024;

export function OllamaPanels({
  deviceId,
  basePath,
  isEditable,
  platformOs,
  want,
}: OllamaPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isBusy, setIsBusy] = useState(false);
  const resource = usePolledResource<OllamaDeviceView>(
    apiPath(basePath, { device_id: deviceId }),
    isBusy ? BUSY_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS,
  );
  const saved = resource.data;

  useEffect(() => {
    setIsBusy(
      saved !== null &&
        (saved.pulls.some((pull) => pull.state !== PULL_FAILED) ||
          saved.models.some((model) => model.is_loading)),
    );
  }, [saved]);

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null) {
    return <div className="skeleton" style={{ height: 160 }} />;
  }

  return (
    <>
      {saved.details.found !== FOUND_APP && (
        <OllamaSettings
          deviceId={deviceId}
          basePath={basePath}
          saved={saved}
          isEditable={isEditable}
          platformOs={platformOs}
          want={want}
          onSaved={resource.setData}
        />
      )}
      <OllamaModels
        deviceId={deviceId}
        basePath={basePath}
        saved={saved}
        isEditable={isEditable}
        onView={resource.setData}
        onRetry={resource.reload}
      />
    </>
  );
}

interface OllamaModelsProps {
  deviceId: string;
  basePath: string;
  saved: OllamaDeviceView;
  isEditable: boolean;
  /** Takes the view a press answered. */
  onView: (view: OllamaDeviceView) => void;
  onRetry: () => void;
}

/** **Models**: the machine's resources, the pull form and the one list. */
function OllamaModels({
  deviceId,
  basePath,
  saved,
  isEditable,
  onView,
  onRetry,
}: OllamaModelsProps) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();

  const act = async (path: string, model: string, key: string) => {
    setBusy(key);
    setError(null);
    const request: OllamaModelRequest = { device_id: deviceId, name: model };
    try {
      onView(await apiPost<OllamaDeviceView>(`${basePath}/${path}`, request));
      return true;
    } catch (cause: unknown) {
      setError(describeError(cause));
      return false;
    } finally {
      setBusy(null);
    }
  };

  const title = (
    <div className="settings_group_title ollama_models_title">
      <h2>{t("ui.ollama.models_title")}</h2>
      {saved.is_running && (
        <span className="faint ollama_models_summary">
          {t(
            saved.models.length === 1
              ? "ui.ollama.models_summary_one"
              : "ui.ollama.models_summary",
            {
              count: saved.models.length,
              size: formatBytes(saved.total_bytes),
            },
          )}
        </span>
      )}
    </div>
  );

  if (!saved.is_online || !saved.is_running) {
    const stateKey = saved.is_online
      ? (STATE_KEYS[saved.state] ?? "state.stopped")
      : "ui.device_monitor.waiting";
    return (
      <section className="settings_group">
        {title}
        <p className="field_hint">{t(stateKey)}</p>
      </section>
    );
  }

  const isUnreachable = saved.code === "ollama_unreachable";
  const isDisabled = !isEditable || busy !== null;
  const hasRows = saved.pulls.length > 0 || saved.models.length > 0;

  return (
    <section className="settings_group">
      {title}
      <Resources saved={saved} />
      <form
        className="ollama_pull_form"
        onSubmit={(event) => {
          event.preventDefault();
          const model = name.trim();
          if (model === "") {
            return;
          }
          void act("model/add", model, "pull").then((isDone) => {
            if (isDone) {
              setName("");
            }
          });
        }}
      >
        <input
          className="input mono"
          value={name}
          placeholder={NAME_PLACEHOLDER}
          spellCheck={false}
          autoComplete="off"
          aria-label={t("ui.ollama.col_name")}
          onChange={(event) => {
            setName(event.target.value);
          }}
          disabled={!isEditable}
        />
        <button
          type="submit"
          className="button"
          disabled={isDisabled || name.trim() === ""}
        >
          {t("ui.ollama.pull")}
        </button>
      </form>
      {error !== null && <span className="field_error">{error}</span>}
      {isUnreachable && (
        <ErrorPanel
          message={describeCode({
            code: saved.code,
            params: codeParams(saved.params),
          })}
          onRetry={onRetry}
        />
      )}
      {!isUnreachable && !hasRows && (
        <div className="placeholder">
          <span className="faint">{t("ui.ollama.models_empty")}</span>
        </div>
      )}
      {hasRows && (
        <div className="ollama_list_frame">
          <div className="ollama_list">
            <div className="ollama_row ollama_row--head faint">
              <span>{t("ui.ollama.col_name")}</span>
              <span className="ollama_facts">
                <span>{t("ui.ollama.col_parameters")}</span>
                <span>{t("ui.ollama.col_quantization")}</span>
                <span>{t("ui.ollama.col_size")}</span>
                <span>{t("ui.ollama.col_modified")}</span>
              </span>
              <span>{t("ui.ollama.col_memory")}</span>
              <span />
            </div>
            {saved.pulls.map((pull) => (
              <PullRow
                key={`pull:${pull.name}`}
                pull={pull}
                isDisabled={isDisabled}
                onCancel={() => {
                  void act("pull/remove", pull.name, `cancel:${pull.name}`);
                }}
              />
            ))}
            {saved.models.map((model) => (
              <ModelRow
                key={`model:${model.name}`}
                model={model}
                isDisabled={isDisabled}
                onLoad={() => {
                  void act("loaded/add", model.name, `load:${model.name}`);
                }}
                onUnload={() => {
                  void act("loaded/remove", model.name, `unload:${model.name}`);
                }}
                onRemove={() => {
                  confirm.ask({
                    title: t("ui.ollama.remove_title", { name: model.name }),
                    body: t("ui.ollama.remove_body", {
                      size: formatBytes(model.size_bytes),
                    }),
                    confirmLabel: t("ui.ollama.remove"),
                    isDanger: true,
                    onConfirm: () => {
                      void act(
                        "model/remove",
                        model.name,
                        `remove:${model.name}`,
                      );
                    },
                  });
                }}
              />
            ))}
          </div>
        </div>
      )}
      {confirm.modal}
    </section>
  );
}

/** The machine's GPUs and its memory, each its memory used over its total. */
function Resources({ saved }: { saved: OllamaDeviceView }) {
  const { gpus, memory_used_mb, memory_total_mb } = saved.resources;
  return (
    <div className="ollama_resources_frame">
      <div className="ollama_resources">
        {gpus.map((gpu, place) => (
          <ResourceLine
            key={place}
            name={gpuName(gpu, place)}
            usedMib={gpu.memory_used_mb}
            totalMib={gpu.memory_total_mb}
            tone={GPU_TONE}
          />
        ))}
        <ResourceLine
          name={t("ui.ollama.system_memory")}
          usedMib={memory_used_mb}
          totalMib={memory_total_mb}
          tone={SYSTEM_TONE}
        />
      </div>
    </div>
  );
}

interface ResourceLineProps {
  name: string;
  usedMib: number | null;
  totalMib: number | null;
  tone: MeterTone;
}

/** One line of the resources: the name, its bar and its numbers, or the
 * name alone while the report lacks them. */
function ResourceLine({ name, usedMib, totalMib, tone }: ResourceLineProps) {
  const isRead = usedMib !== null && totalMib !== null && totalMib > 0;
  return (
    <div className="ollama_resource">
      <span className="ollama_resource_name">{name}</span>
      {isRead && (
        <>
          <Meter percent={(100 * usedMib) / totalMib} tone={tone} />
          <span className="faint ollama_resource_numbers">
            {t("ui.ollama.memory_used", {
              used: formatBytes(usedMib * BYTES_PER_MIB),
              total: formatBytes(totalMib * BYTES_PER_MIB),
            })}
          </span>
        </>
      )}
    </div>
  );
}

/** A model's name in two lines when a source stands in front of it: the
 * source up to its last `/`, small and muted, then the model's own name.
 * A narrow column breaks the source after a `/` and the name after a `-`,
 * never inside a word. */
function ModelName({ name }: { name: string }) {
  const cut = name.lastIndexOf("/") + 1;
  const parts = name.slice(0, cut).split("/").slice(0, -1);
  return (
    <span className="ollama_row_name">
      {cut > 0 && (
        <span className="ollama_row_source">
          {parts.map((part, place) => (
            <span key={place}>
              {part}/<wbr />
            </span>
          ))}
        </span>
      )}
      <span className="ollama_row_model">{name.slice(cut)}</span>
    </span>
  );
}

interface PullRowProps {
  pull: OllamaPull;
  isDisabled: boolean;
  onCancel: () => void;
}

/** One pull: its name, its bar and bytes, or its failure, and **Cancel**. */
function PullRow({ pull, isDisabled, onCancel }: PullRowProps) {
  const percent =
    pull.total_bytes > 0 ? (100 * pull.completed_bytes) / pull.total_bytes : 0;
  let progress = t("ui.ollama.pull_preparing");
  if (pull.state === PULL_QUEUED) {
    progress = t("state.queued");
  } else if (pull.total_bytes > 0) {
    progress = t("ui.ollama.pull_progress", {
      done: formatBytes(pull.completed_bytes),
      total: formatBytes(pull.total_bytes),
      speed: formatBytes(pull.speed_bytes),
    });
  }
  return (
    <div className="ollama_row">
      <ModelName name={pull.name} />
      {pull.state === PULL_FAILED ? (
        <span className="ollama_row_progress field_error">
          {describeCode({ code: pull.code, params: codeParams(pull.params) })}
        </span>
      ) : (
        <span className="ollama_row_progress">
          {pull.state === PULL_RUNNING && (
            <Meter percent={percent} tone="accent" />
          )}
          <span className="faint">{progress}</span>
        </span>
      )}
      <span className="ollama_row_actions">
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={onCancel}
          disabled={isDisabled}
        >
          {t("ui.ollama.cancel")}
        </button>
      </span>
    </div>
  );
}

interface ModelRowProps {
  model: OllamaModel;
  isDisabled: boolean;
  onLoad: () => void;
  onUnload: () => void;
  onRemove: () => void;
}

/** One pulled model: its name and facts, its memory, and its presses. */
function ModelRow({
  model,
  isDisabled,
  onLoad,
  onUnload,
  onRemove,
}: ModelRowProps) {
  const modified = model.modified_at ? formatTimeAgo(model.modified_at) : "";
  return (
    <div className="ollama_row">
      <ModelName name={model.name} />
      <span className="ollama_facts">
        <span>{model.parameter_size}</span>
        <span className="mono">{model.quantization}</span>
        <span>{formatBytes(model.size_bytes)}</span>
        <span>{modified}</span>
      </span>
      <MemoryCell model={model} />
      <span className="ollama_row_actions">
        <button
          type="button"
          className="button button--ghost button--small ollama_row_toggle"
          onClick={model.is_loaded ? onUnload : onLoad}
          disabled={isDisabled || model.is_loading}
        >
          {t(model.is_loaded ? "ui.ollama.unload" : "ui.ollama.load")}
        </button>
        <button
          type="button"
          className="button button--ghost button--small button--danger"
          onClick={onRemove}
          disabled={isDisabled}
        >
          {t("ui.ollama.remove")}
        </button>
      </span>
    </div>
  );
}

/** A model's memory: for one in memory a bar of its GPU part and its
 * system part, its total and its share as `ollama ps` words it; `loading`
 * while the hub loads it; nothing otherwise. */
function MemoryCell({ model }: { model: OllamaModel }) {
  if (!model.is_loaded) {
    return (
      <span className="ollama_memory faint">
        {model.is_loading ? t("ui.ollama.loading") : ""}
      </span>
    );
  }
  const total = model.memory_bytes;
  const gpu = Math.min(model.vram_bytes, total);
  const gpuPercent = total > 0 ? (100 * gpu) / total : 0;
  return (
    <span className="ollama_memory">
      <span className="ollama_memory_bar" aria-hidden="true">
        <span
          className="ollama_memory_gpu"
          style={{ width: `${gpuPercent}%` }}
        />
        <span
          className="ollama_memory_cpu"
          style={{ width: `${100 - gpuPercent}%` }}
        />
      </span>
      <span className="ollama_memory_numbers">
        <span>{formatBytes(total)}</span>
        <span className="faint">{memoryShare(total, gpu)}</span>
      </span>
    </span>
  );
}

/** The share of a model on a GPU and in system memory, as `ollama ps`
 * words it. */
function memoryShare(total: number, gpu: number): string {
  if (gpu <= 0) {
    return t("ui.ollama.memory_cpu", { percent: 100 });
  }
  if (gpu >= total) {
    return t("ui.ollama.memory_gpu", { percent: 100 });
  }
  const cpu = Math.round((100 * (total - gpu)) / total);
  return t("ui.ollama.memory_split", { cpu, gpu: 100 - cpu });
}
