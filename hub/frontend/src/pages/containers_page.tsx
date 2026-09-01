import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ApplyBar } from "../components/apply_bar";
import { ErrorPanel } from "../components/error_panel";
import { ServiceStateBadge } from "../components/service_state_badge";
import { Icon } from "../components/icon";
import { ShellTerminal } from "../components/shell_terminal";
import { StatusDot } from "../components/status_dot";
import { StringListEditor } from "../components/string_list_editor";
import { ToggleSwitch } from "../components/toggle_switch";
import { apiGet, apiPost, apiPut, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import type {
  ApplyResult,
  PodmanContainer,
  PodmanContainerState,
  PodmanSettings,
} from "../api_types";

import "../components/terminal_modal.css";
import "./containers_page.css";

/**
 * Containers, declared and live.
 *
 * A declared container is configuration: it renders to a Quadlet unit, so
 * systemd supervises it and it comes back after a reboot. The live list below
 * shows every container podman knows — including ones started by hand at a
 * shell — each with start/stop/restart and a shell of its own.
 *
 * The knobs stop at image, ports, volumes, environment and autostart, all on
 * the default network. That is the deliberate line: a page that grew custom
 * networks and healthchecks would be compose with worse ergonomics, and
 * anything past the line works fine from the Terminal.
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

export function ContainersPage() {
  const resource = useApiResource<PodmanSettings>("/podman");

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

  // The live list polls every few seconds, so resource.data changes identity
  // constantly. The draft is only re-seeded when the *saved declarations*
  // actually changed — otherwise every poll would wipe an edit in progress,
  // including a freshly added container that exists nowhere else yet.
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

  // The live list follows along: containers start, stop and crash on their
  // own schedule, not the page's.
  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [reload]);

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
      await apiPut<PodmanSettings>("/podman/mirrors", {
        mirrors: filledMirrors,
      });
      const result = await apiPost<ApplyResult>("/podman/apply");
      resource.reload();
      if (!result.is_applied) {
        setMirrorsError(result.message);
        return;
      }
      setMirrorsNotice(result.message);
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
      await apiPut<PodmanSettings>("/podman/containers", { containers });
      const result = await apiPost<ApplyResult>("/podman/apply");
      resource.reload();
      if (!result.is_applied) {
        setError(result.message);
        return;
      }
      setNotice(result.message);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const controlContainer = async (name: string, action: string) => {
    setLiveError(null);
    try {
      const updated = await apiPost<PodmanSettings>(
        `/podman/containers/${name}/${action}`,
      );
      resource.setData(updated);
    } catch (cause: unknown) {
      setLiveError(describeError(cause));
    }
  };

  if (resource.error !== null && saved === null) {
    return (
      <div className="page">
        <h1>Containers</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (saved === null) {
    return (
      <div className="page">
        <h1>Containers</h1>
        <div className="skeleton" style={{ height: 360 }} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>Containers</h1>
          <ServiceStateBadge name="podman" />
          {saved.is_installed && (
            <span className="badge">podman {saved.version}</span>
          )}
        </div>
      </div>

      {!saved.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            The container engine is not installed. Install podman from the
            Services page first.
          </div>
        </div>
      )}

      <section
        className={`settings_group ${isMirrorsDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>Registry mirrors</h2>
        </div>
        <p className="field_hint">Tried in order before docker.io.</p>
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
            Add mirror
          </button>
        </div>
        <ApplyBar
          isDirty={isMirrorsDirty}
          isBusy={isMirrorsBusy}
          label="Apply mirrors"
          hint="Takes effect on the next pull; nothing restarts."
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
          <h2>Declared containers</h2>
        </div>
        <p className="field_hint">
          Each becomes a systemd unit on the default network.
        </p>
        {containers.map((container, index) => (
          <ContainerEditor
            key={index}
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
            Add container
          </button>
        </div>
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy}
          label="Apply containers"
          hint="First starts pull the image, which can take a while."
          warning="Recreates changed containers; files outside volumes are lost."
          error={error}
          notice={notice}
          onReset={() => setContainers(saved.containers)}
          onApply={() => void applyContainers()}
        />
      </section>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>Running now</h2>
          <span className="badge">
            <StatusDot tone="ok" isPulsing />
            live
          </span>
        </div>
        {liveError !== null && (
          <div className="notice notice--error">
            <Icon name="alert" size={15} />
            <div className="notice_body">{liveError}</div>
          </div>
        )}
        {saved.running.length === 0 ? (
          <p className="field_hint">
            No containers exist yet. Declared ones appear here after Apply.
          </p>
        ) : (
          <div className="container_rows">
            {saved.running.map((state) => (
              <ContainerRow
                key={state.name}
                state={state}
                onAction={(action) => void controlContainer(state.name, action)}
                onShell={() => setShellTarget(state.name)}
              />
            ))}
          </div>
        )}
      </section>

      {shellTarget !== null && (
        <ContainerShellModal
          name={shellTarget}
          onClose={() => setShellTarget(null)}
        />
      )}
    </div>
  );
}

/** The image without its tag; the tag chips swap what follows the colon. */
function imageBase(image: string): string {
  const colon = image.lastIndexOf(":");
  return colon > image.lastIndexOf("/") ? image.slice(0, colon) : image;
}

interface ContainerEditorProps {
  container: PodmanContainer;
  onChange: (patch: Partial<PodmanContainer>) => void;
  onRemove: () => void;
}

function ContainerEditor({
  container,
  onChange,
  onRemove,
}: ContainerEditorProps) {
  const [tags, setTags] = useState<string[] | null>(null);
  const [isLoadingTags, setIsLoadingTags] = useState(false);

  const loadTags = async () => {
    setIsLoadingTags(true);
    try {
      const found = await apiGet<{ tags: string[] }>(
        `/podman/tags?image=${encodeURIComponent(imageBase(container.image))}`,
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
          {container.name === "" ? "new container" : container.name}
        </span>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={onRemove}
        >
          <Icon name="trash" size={13} />
          Remove
        </button>
      </div>
      <div className="container_editor_fields">
        <label className="field">
          <span className="field_label">Name</span>
          <input
            className="input"
            placeholder="redis"
            value={container.name}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">Image tag</span>
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
            {isLoadingTags ? "Loading tags…" : "Pick a tag"}
          </button>
          {tags !== null && tags.length === 0 && (
            <span className="field_hint">
              No tags found. Type one, e.g. :latest.
            </span>
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
          label="Ports"
          values={container.ports}
          onChange={(ports) => onChange({ ports })}
          placeholder="8080:80"
          emptyText="host_port:container_port"
        />
        <StringListEditor
          label="Volumes"
          values={container.volumes}
          onChange={(volumes) => onChange({ volumes })}
          placeholder="/srv/share:/data"
          emptyText="host_path:container_path"
        />
        <StringListEditor
          label="Environment"
          values={container.environment}
          onChange={(environment) => onChange({ environment })}
          placeholder="KEY=value"
          emptyText="KEY=value"
        />
      </div>
      <label className="field">
        <span className="field_label">Command (optional)</span>
        <input
          className="input"
          placeholder="python3 -m http.server 8000"
          value={container.command}
          onChange={(event) => onChange({ command: event.target.value })}
        />
        <span className="field_hint">
          Empty uses the image's command; base images need a long-running one.
        </span>
      </label>
      <ToggleSwitch
        isOn={container.is_autostart}
        onChange={(isOn) => onChange({ is_autostart: isOn })}
        label="Start with the box"
        description="Off, it stays declared but only starts when asked."
      />
    </div>
  );
}

interface ContainerRowProps {
  state: PodmanContainerState;
  onAction: (action: string) => void;
  onShell: () => void;
}

function ContainerRow({ state, onAction, onShell }: ContainerRowProps) {
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
        <span className="badge badge--accent">declared</span>
      ) : (
        <span className="badge">ad hoc</span>
      )}
      <div className="container_row_actions">
        {state.is_running ? (
          <>
            <button
              type="button"
              className="button button--small"
              onClick={onShell}
            >
              <Icon name="terminal" size={12} />
              Shell
            </button>
            <button
              type="button"
              className="button button--small"
              onClick={() => onAction("restart")}
            >
              <Icon name="refresh" size={12} />
              Restart
            </button>
            <button
              type="button"
              className="button button--small"
              onClick={() => onAction("stop")}
            >
              <Icon name="stop" size={12} />
              Stop
            </button>
          </>
        ) : (
          <button
            type="button"
            className="button button--small"
            onClick={() => onAction("start")}
          >
            <Icon name="play" size={12} />
            Start
          </button>
        )}
      </div>
    </div>
  );
}

interface ContainerShellModalProps {
  name: string;
  onClose: () => void;
}

function ContainerShellModal({ name, onClose }: ContainerShellModalProps) {
  // A portal, same as the device terminal: no ancestor may capture it.
  return createPortal(
    <div className="terminal_modal_backdrop" role="dialog" aria-modal="true">
      <div className="terminal_modal">
        <div className="terminal_modal_head">
          <div className="terminal_modal_title">
            <Icon name="terminal" size={15} />
            <span className="terminal_modal_target">{name}</span>
          </div>
          <div className="terminal_modal_actions">
            <button
              type="button"
              className="button button--small"
              onClick={onClose}
            >
              <Icon name="close" size={13} />
              Close
            </button>
          </div>
        </div>
        <div className="terminal_modal_surface">
          <ShellTerminal
            socketPath={`/ws/container/${name}`}
            onExit={onClose}
          />
        </div>
        <div className="terminal_modal_status">Shell inside the container.</div>
      </div>
    </div>,
    document.body,
  );
}
