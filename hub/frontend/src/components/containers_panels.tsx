import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ApplyBar } from "./apply_bar";
import { JournalPanel } from "./journal_panel";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { ShellTerminal } from "./shell_terminal";
import { StatusDot } from "./status_dot";
import { StringListEditor } from "./string_list_editor";
import { ToggleSwitch } from "./toggle_switch";
import { apiGet, apiPost, apiPut, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  ApplyResult,
  PodmanContainer,
  PodmanContainerState,
  PodmanDeviceView,
} from "../api_types";

import "./containers_panels.css";

/**
 * Containers on one machine, declared and live.
 *
 * A declared container is configuration: it renders to a Quadlet unit, so
 * systemd supervises it and it comes back after a reboot. The live list below
 * shows every container podman knows — including ones started by hand at a
 * shell — each with start/stop/restart and a shell of its own.
 *
 * The knobs stop at image, ports, volumes, environment and autostart, all on
 * the default network. That is the deliberate line: panels that grew custom
 * networks and healthchecks would be compose with worse ergonomics, and
 * anything past the line works fine from a terminal.
 */

const EMPTY_CONTAINER: PodmanContainer = {
  name: "",
  image: "",
  ports: [],
  volumes: [],
  environment: [],
  command: "",
  is_autostart: true,
};

interface ContainersPanelsProps {
  /** The machine this page's shells and journals reach. */
  deviceId: string;
  /** Where this machine's podman answers. */
  basePath: string;
  isEditable: boolean;
}

export function ContainersPanels({
  deviceId,
  basePath,
  isEditable,
}: ContainersPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  // Containers start, stop and crash on their own schedule; the machine's
  // own report is what says so, and its settings are a write like any other.
  const resource = useApiResource<PodmanDeviceView>(basePath, {
    invalidateOn: [
      { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
      { type: HUB_EVENT_CONFIG },
    ],
  });

  const [containers, setContainers] = useState<PodmanContainer[]>([]);
  const [mirrors, setMirrors] = useState<string[]>([]);
  const [isMirrorsBusy, setIsMirrorsBusy] = useState(false);
  const [mirrorsNotice, setMirrorsNotice] = useState<string | null>(null);
  const [mirrorsError, setMirrorsError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [shellTarget, setShellTarget] = useState<string | null>(null);
  const [journalTarget, setJournalTarget] = useState<string | null>(null);

  // The live list refreshes on its own, so the draft is only re-seeded when
  // the *saved declarations* actually changed — otherwise a refresh would
  // wipe an edit in progress, including a freshly added container that exists
  // nowhere else yet.
  const lastSyncedRef = useRef<string | null>(null);
  useEffect(() => {
    if (resource.data === null) {
      return;
    }
    const savedJson = JSON.stringify([
      resource.data.containers,
      resource.data.mirrors,
    ]);
    if (savedJson !== lastSyncedRef.current) {
      lastSyncedRef.current = savedJson;
      setContainers(resource.data.containers);
      setMirrors(resource.data.mirrors);
    }
  }, [resource.data]);

  const saved = resource.data;
  const isDirty =
    saved !== null &&
    JSON.stringify(containers) !== JSON.stringify(saved.containers);
  const filledMirrors = mirrors.filter((mirror) => mirror !== "");
  const isMirrorsDirty =
    saved !== null &&
    JSON.stringify(filledMirrors) !== JSON.stringify(saved.mirrors);

  const applyMirrors = async () => {
    setIsMirrorsBusy(true);
    setMirrorsError(null);
    setMirrorsNotice(null);
    try {
      await apiPut<PodmanDeviceView>(`${basePath}/mirrors`, {
        mirrors: filledMirrors,
      });
      const result = await apiPost<ApplyResult>(`${basePath}/apply`);
      resource.reload();
      if (!result.is_applied) {
        setMirrorsError(result.message);
        return;
      }
      setMirrorsNotice(t("ui.containers.applied"));
    } catch (cause: unknown) {
      setMirrorsError(describeError(cause));
    } finally {
      setIsMirrorsBusy(false);
    }
  };

  const applyContainers = async () => {
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiPut<PodmanDeviceView>(`${basePath}/containers`, { containers });
      const result = await apiPost<ApplyResult>(`${basePath}/apply`);
      resource.reload();
      if (!result.is_applied) {
        setError(result.message);
        return;
      }
      setNotice(t("ui.containers.applied"));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const controlContainer = async (name: string, action: string) => {
    setLiveError(null);
    try {
      const updated = await apiPost<PodmanDeviceView>(
        `${basePath}/containers/${name}/${action}`,
      );
      resource.setData(updated);
    } catch (cause: unknown) {
      setLiveError(describeError(cause));
    }
  };

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  if (saved === null) {
    return <div className="skeleton" style={{ height: 360 }} />;
  }

  return (
    <>
      {!saved.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{t("ui.containers.not_installed")}</div>
        </div>
      )}

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.containers.live_title")}</h2>
          {saved.is_installed && (
            <span className="badge">podman {saved.version}</span>
          )}
          <span className="badge">
            <StatusDot tone="ok" isPulsing />
            {t("state.live")}
          </span>
        </div>
        {liveError !== null && (
          <div className="notice notice--error">
            <Icon name="alert" size={15} />
            <div className="notice_body">{liveError}</div>
          </div>
        )}
        {saved.running.length === 0 ? (
          <p className="field_hint">{t("ui.containers.live_empty")}</p>
        ) : (
          <div className="container_rows">
            {saved.running.map((state) => (
              <div key={state.name}>
                <ContainerRow
                  state={state}
                  onAction={(action) =>
                    void controlContainer(state.name, action)
                  }
                  onShell={() => setShellTarget(state.name)}
                  onJournal={() =>
                    setJournalTarget(
                      journalTarget === state.name ? null : state.name,
                    )
                  }
                />
                <JournalPanel
                  path={`${basePath}/containers/${state.name}/journal`}
                  isOpen={journalTarget === state.name}
                />
              </div>
            ))}
          </div>
        )}
      </section>

      <section
        className={`settings_group ${isMirrorsDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.containers.mirrors_title")}</h2>
        </div>
        <p className="field_hint">{t("ui.containers.mirrors_hint")}</p>
        {mirrors.map((mirror, index) => (
          <div key={index} className="mirror_row">
            <input
              className="input"
              placeholder="mirror.ccs.tencentyun.com"
              value={mirror}
              onChange={(event) =>
                setMirrors((current) =>
                  current.map((entry, at) =>
                    at === index
                      ? event.target.value
                          .replace(/^https?:\/\//, "")
                          .replace(/\/+$/, "")
                      : entry,
                  ),
                )
              }
            />
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() =>
                setMirrors((current) => current.filter((_, at) => at !== index))
              }
            >
              <Icon name="trash" size={13} />
            </button>
          </div>
        ))}
        <div>
          <button
            type="button"
            className="button"
            onClick={() => setMirrors((current) => [...current, ""])}
          >
            <Icon name="plus" size={14} />
            {t("ui.containers.mirror_add")}
          </button>
        </div>
        <ApplyBar
          isDirty={isMirrorsDirty}
          isBusy={isMirrorsBusy}
          label={t("ui.containers.mirrors_apply")}
          hint={t("ui.containers.mirrors_apply_hint")}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
          error={mirrorsError}
          notice={mirrorsNotice}
          onReset={() => setMirrors(saved.mirrors)}
          onApply={() => void applyMirrors()}
        />
      </section>

      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.containers.declared_title")}</h2>
        </div>
        <p className="field_hint">{t("ui.containers.declared_hint")}</p>
        {containers.map((container, index) => (
          <ContainerEditor
            key={index}
            basePath={basePath}
            container={container}
            onChange={(patch) =>
              setContainers((current) =>
                current.map((entry, at) =>
                  at === index ? { ...entry, ...patch } : entry,
                ),
              )
            }
            onRemove={() =>
              setContainers((current) =>
                current.filter((_, at) => at !== index),
              )
            }
          />
        ))}
        <div>
          <button
            type="button"
            className="button"
            onClick={() =>
              setContainers((current) => [...current, EMPTY_CONTAINER])
            }
          >
            <Icon name="plus" size={14} />
            {t("ui.containers.container_add")}
          </button>
        </div>
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy}
          label={t("ui.containers.containers_apply")}
          hint={t("ui.containers.containers_apply_hint")}
          warning={t("ui.containers.containers_apply_warning")}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
          error={error}
          notice={notice}
          onReset={() => setContainers(saved.containers)}
          onApply={() => void applyContainers()}
        />
      </section>

      {shellTarget !== null && (
        <ContainerShellModal
          deviceId={deviceId}
          name={shellTarget}
          onClose={() => setShellTarget(null)}
        />
      )}
    </>
  );
}

/** The image without its tag; the tag chips swap what follows the colon. */
function imageBase(image: string): string {
  const colon = image.lastIndexOf(":");
  return colon > image.lastIndexOf("/") ? image.slice(0, colon) : image;
}

interface ContainerEditorProps {
  basePath: string;
  container: PodmanContainer;
  onChange: (patch: Partial<PodmanContainer>) => void;
  onRemove: () => void;
}

function ContainerEditor({
  basePath,
  container,
  onChange,
  onRemove,
}: ContainerEditorProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [tags, setTags] = useState<string[] | null>(null);
  const [isLoadingTags, setIsLoadingTags] = useState(false);

  const loadTags = async () => {
    setIsLoadingTags(true);
    try {
      const found = await apiGet<{ tags: string[] }>(
        `${basePath}/tags?image=${encodeURIComponent(imageBase(container.image))}`,
      );
      setTags(found.tags);
    } catch {
      setTags([]);
    } finally {
      setIsLoadingTags(false);
    }
  };

  return (
    <div className="container_editor">
      <div className="container_editor_head">
        <span className="container_editor_title">
          <Icon name="services" size={15} />
          {container.name === ""
            ? t("ui.containers.container_new")
            : container.name}
        </span>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={onRemove}
        >
          <Icon name="trash" size={13} />
          {t("ui.containers.container_remove")}
        </button>
      </div>
      <div className="container_editor_fields">
        <label className="field">
          <span className="field_label">{t("ui.containers.name")}</span>
          <input
            className="input"
            placeholder="redis"
            value={container.name}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.containers.image")}</span>
          <input
            className="input"
            placeholder="redis:7"
            value={container.image}
            onChange={(event) => onChange({ image: event.target.value })}
          />
        </label>
      </div>

      {container.image !== "" && (
        <div className="container_tags">
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={isLoadingTags}
            onClick={() => void loadTags()}
          >
            <Icon name="refresh" size={12} />
            {isLoadingTags
              ? t("ui.containers.tag_loading")
              : t("ui.containers.tag_pick")}
          </button>
          {tags !== null && tags.length === 0 && (
            <span className="field_hint">{t("ui.containers.tags_empty")}</span>
          )}
          {tags !== null &&
            tags.map((tag) => (
              <button
                key={tag}
                type="button"
                className={`container_tag_chip ${
                  container.image === `${imageBase(container.image)}:${tag}`
                    ? "container_tag_chip--on"
                    : ""
                }`}
                onClick={() =>
                  onChange({
                    image: `${imageBase(container.image)}:${tag}`,
                  })
                }
              >
                {tag}
              </button>
            ))}
        </div>
      )}
      <div className="container_editor_lists">
        <StringListEditor
          label={t("ui.containers.ports")}
          values={container.ports}
          onChange={(ports) => onChange({ ports })}
          placeholder="8080:80"
          emptyText="host_port:container_port"
        />
        <StringListEditor
          label={t("ui.containers.volumes")}
          values={container.volumes}
          onChange={(volumes) => onChange({ volumes })}
          placeholder="/srv/share:/data"
          emptyText="host_path:container_path"
        />
        <StringListEditor
          label={t("ui.containers.environment")}
          values={container.environment}
          onChange={(environment) => onChange({ environment })}
          placeholder="KEY=value"
          emptyText="KEY=value"
        />
      </div>
      <label className="field">
        <span className="field_label">{t("ui.containers.command")}</span>
        <input
          className="input"
          placeholder="python3 -m http.server 8000"
          value={container.command}
          onChange={(event) => onChange({ command: event.target.value })}
        />
        <span className="field_hint">{t("ui.containers.command_hint")}</span>
      </label>
      <ToggleSwitch
        isOn={container.is_autostart}
        onChange={(isOn) => onChange({ is_autostart: isOn })}
        label={t("ui.containers.autostart")}
        description={t("ui.containers.autostart_hint")}
      />
    </div>
  );
}

interface ContainerRowProps {
  onJournal: () => void;
  state: PodmanContainerState;
  onAction: (action: string) => void;
  onShell: () => void;
}

function ContainerRow({
  state,
  onAction,
  onShell,
  onJournal,
}: ContainerRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <div className="container_row">
      <span className="container_row_name">
        <StatusDot
          tone={state.is_running ? "ok" : "idle"}
          isPulsing={state.is_running}
        />
        {state.name}
      </span>
      <span className="container_row_image">{state.image}</span>
      <span className="container_row_status">{state.status}</span>
      {state.is_declared ? (
        <span className="badge badge--accent">{t("state.declared")}</span>
      ) : (
        <span className="badge">{t("state.ad_hoc")}</span>
      )}
      <div className="container_row_actions">
        <button
          type="button"
          className="button button--small"
          onClick={onJournal}
        >
          <Icon name="file" size={12} />
          {t("ui.containers.row_journal")}
        </button>
        {state.is_running ? (
          <>
            <button
              type="button"
              className="button button--small"
              onClick={onShell}
            >
              <Icon name="terminal" size={12} />
              {t("ui.containers.row_shell")}
            </button>
            <button
              type="button"
              className="button button--small"
              onClick={() => onAction("restart")}
            >
              <Icon name="refresh" size={12} />
              {t("ui.containers.row_restart")}
            </button>
            <button
              type="button"
              className="button button--small"
              onClick={() => onAction("stop")}
            >
              <Icon name="stop" size={12} />
              {t("ui.containers.row_stop")}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="button button--small"
            onClick={() => onAction("start")}
          >
            <Icon name="play" size={12} />
            {t("ui.containers.row_start")}
          </button>
        )}
      </div>
    </div>
  );
}

interface ContainerShellModalProps {
  deviceId: string;
  name: string;
  onClose: () => void;
}

function ContainerShellModal({
  deviceId,
  name,
  onClose,
}: ContainerShellModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [failedCode, setFailedCode] = useState<number | null>(null);
  // A portal, so no ancestor may capture the fixed backdrop.
  return createPortal(
    <div className="container_shell_backdrop" role="dialog" aria-modal="true">
      <div className="container_shell">
        <div className="container_shell_head">
          <div className="container_shell_title">
            <Icon name="terminal" size={15} />
            <span className="container_shell_target">{name}</span>
          </div>
          <div className="container_shell_actions">
            <button
              type="button"
              className="button button--small"
              onClick={onClose}
            >
              <Icon name="close" size={13} />
              {t("ui.containers.shell_close")}
            </button>
          </div>
        </div>
        <div className="container_shell_surface">
          <ShellTerminal
            socketPath={`/ws/agent_container/${deviceId}/${name}`}
            onExit={(code) => {
              // A clean exit closes like every other terminal here; a
              // failing shell stays, because its last words are the
              // diagnosis.
              if (code === 0) {
                onClose();
              } else {
                setFailedCode(code ?? -1);
              }
            }}
          />
        </div>
        <div
          className={
            failedCode !== null
              ? "container_shell_status container_shell_status--warn"
              : "container_shell_status"
          }
        >
          {failedCode !== null
            ? t("ui.containers.shell_failed", { code: failedCode })
            : t("ui.containers.shell_hint")}
        </div>
      </div>
    </div>,
    document.body,
  );
}
