import { useEffect, useState } from "react";

import { ErrorPanel } from "./error_panel";
import { Meter } from "./meter";
import { apiPath, apiPost, describeCode, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { formatBytes } from "../format_bytes";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { useConfirm } from "../use_confirm";
import { usePolledResource } from "../use_polled_resource";
import type {
  OllamaDeviceView,
  OllamaModel,
  OllamaModelRequest,
  OllamaPull,
} from "../api_types";

import "./ollama_panels.css";

/**
 * **Models** of the Ollama module on one machine, which Configure opens:
 * the count and the size of the models, a field to pull any name Ollama
 * takes, the pulls the hub runs for the machine, and one row per pulled
 * model with its size, its place in memory, **Unload** and **Remove**.
 *
 * Each press acts at once. A pull is the hub's own task: the page shows the
 * queue the view carries, whenever it is opened. While the server does not
 * run, or the machine is offline, the panel shows that state alone.
 */

interface OllamaPanelsProps {
  /** The machine Ollama runs on. */
  deviceId: string;
  /** Where the module answers: `/agent/module/ollama`. */
  basePath: string;
  isEditable: boolean;
}

/** How often the view is read while a pull runs or waits, and otherwise. */
const PULL_POLL_INTERVAL_MS = 2000;
const IDLE_POLL_INTERVAL_MS = 15000;

/** The placeholder of the pull field: a model name. */
const NAME_PLACEHOLDER = "qwen2.5:7b";

/** The states of a pull in the queue. */
const PULL_RUNNING = "running";
const PULL_QUEUED = "queued";
const PULL_FAILED = "failed";

/** The word of a module that is not running, by its state. */
const STATE_KEYS: Record<string, string> = {
  stopped: "state.stopped",
  installed: "state.installed",
  absent: "state.absent",
};

export function OllamaPanels({
  deviceId,
  basePath,
  isEditable,
}: OllamaPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isPulling, setIsPulling] = useState(false);
  const resource = usePolledResource<OllamaDeviceView>(
    apiPath(basePath, { device_id: deviceId }),
    isPulling ? PULL_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS,
  );
  const saved = resource.data;
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();

  useEffect(() => {
    setIsPulling(
      saved !== null && saved.pulls.some((pull) => pull.state !== PULL_FAILED),
    );
  }, [saved]);

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null) {
    return <div className="skeleton" style={{ height: 160 }} />;
  }

  const act = async (path: string, model: string, key: string) => {
    setBusy(key);
    setError(null);
    const request: OllamaModelRequest = { device_id: deviceId, name: model };
    try {
      resource.setData(
        await apiPost<OllamaDeviceView>(`${basePath}/${path}`, request),
      );
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
      <span>{t("ui.ollama.models_title")}</span>
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

  return (
    <section className="settings_group">
      {title}
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
          onRetry={resource.reload}
        />
      )}
      {!isUnreachable &&
        saved.pulls.length === 0 &&
        saved.models.length === 0 && (
          <div className="placeholder">
            <span className="faint">{t("ui.ollama.models_empty")}</span>
          </div>
        )}
      {(saved.pulls.length > 0 || saved.models.length > 0) && (
        <div className="ollama_list">
          <div className="ollama_row ollama_row--head faint">
            <span>{t("ui.ollama.col_name")}</span>
            <span>{t("ui.ollama.col_parameters")}</span>
            <span>{t("ui.ollama.col_quantization")}</span>
            <span>{t("ui.ollama.col_size")}</span>
            <span>{t("ui.ollama.col_modified")}</span>
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
      )}
      {confirm.modal}
    </section>
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
      <span className="ollama_row_name mono">{pull.name}</span>
      {pull.state === PULL_FAILED ? (
        <span className="ollama_row_failure field_error">
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
  onUnload: () => void;
  onRemove: () => void;
}

/** One pulled model: its name, size and details, its memory, and its presses. */
function ModelRow({ model, isDisabled, onUnload, onRemove }: ModelRowProps) {
  const modified = model.modified_at ? formatTimeAgo(model.modified_at) : "";
  return (
    <div className="ollama_row">
      <span className="ollama_row_name">
        <span className="mono">{model.name}</span>
        {model.is_loaded && (
          <span className="ollama_row_loaded">
            {model.vram_bytes > 0
              ? t("ui.ollama.loaded_vram", {
                  memory: formatBytes(model.memory_bytes),
                  vram: formatBytes(model.vram_bytes),
                })
              : t("ui.ollama.loaded", {
                  memory: formatBytes(model.memory_bytes),
                })}
          </span>
        )}
      </span>
      <span className="ollama_row_fact">{model.parameter_size}</span>
      <span className="ollama_row_fact mono">{model.quantization}</span>
      <span className="ollama_row_fact">{formatBytes(model.size_bytes)}</span>
      <span className="ollama_row_fact">{modified}</span>
      <span className="ollama_row_actions">
        {model.is_loaded && (
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={onUnload}
            disabled={isDisabled}
          >
            {t("ui.ollama.unload")}
          </button>
        )}
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
