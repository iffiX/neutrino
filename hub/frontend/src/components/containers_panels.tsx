import { useState } from "react";
import { createPortal } from "react-dom";

import { ApplyBar } from "./apply_bar";
import { ContainersRunSettings } from "./containers_run_settings";
import { DirectoryPickerModal } from "./directory_picker_modal";
import { JournalPanel } from "./journal_panel";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Picker } from "./picker";
import { ShellTerminal } from "./shell_terminal";
import { StatusDot } from "./status_dot";
import { StringListEditor } from "./string_list_editor";
import { ToggleSwitch } from "./toggle_switch";
import {
  apiGet,
  apiPath,
  apiPost,
  describeApplyFailure,
  describeError,
} from "../api_client";
import { t, useLanguage } from "../i18n";
import { moduleTitle } from "../module_title";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import { isFailing, useSettledApply } from "../use_settled_apply";
import type { ReportedModule, SettledApply } from "../use_settled_apply";
import type {
  ApplyResult,
  PodmanContainer,
  PodmanContainerSource,
  PodmanContainerState,
  PodmanDeviceView,
  PodmanHubContainer,
  PodmanService,
  PodmanServiceKind,
  PodmanServiceProtocol,
  PodmanServiceScheme,
} from "../api_types";

import "./containers_panels.css";

/**
 * Containers on one machine, declared and live.
 *
 * A declared container is configuration: it renders to a systemd unit, so
 * systemd supervises it and it comes back after a reboot. The live list below
 * shows every container podman knows — including ones started by hand at a
 * shell — each with start/stop/restart and a shell of its own.
 *
 * The knobs stop at image, ports, volumes, environment and autostart, all on
 * the default network. That is the deliberate line: panels that grew custom
 * networks and healthchecks would be compose with worse ergonomics, and
 * anything past the line works fine from a terminal.
 *
 * A container one of the hub's modules runs is listed read only under Hub
 * containers, and its live row names the module and offers its journal
 * alone. Every live row ends with where its container comes from.
 *
 * On Windows and macOS the containers run in one account's Podman machine,
 * and the Run settings that name it come first; until they name an account
 * the panels under them hold nothing to apply. An apply holds until the
 * machine reports the module where the hub asks it, on Windows and macOS
 * with the account's machine running.
 */

const EMPTY_CONTAINER: PodmanContainer = {
  name: "",
  image: "",
  ports: [],
  volumes: [],
  environment: [],
  command: "",
  is_autostart: true,
  services: [],
};

// One host port of a Ports row, `host:container` with an optional protocol.
const PORT_MAPPING_PATTERN = /^(\d{1,5}):\d{1,5}(?:\/(tcp|udp))?$/;

interface ServiceChoice<T> {
  id: T;
  labelKey: string;
}

const SERVICE_KINDS: ServiceChoice<PodmanServiceKind>[] = [
  { id: "auto", labelKey: "ui.containers.service_auto" },
  { id: "web", labelKey: "ui.containers.service_web" },
  { id: "port", labelKey: "ui.containers.service_port" },
];

const SERVICE_SCHEMES: ServiceChoice<PodmanServiceScheme>[] = [
  { id: "http", labelKey: "ui.containers.service_http" },
  { id: "https", labelKey: "ui.containers.service_https" },
];

const SERVICE_PROTOCOLS: ServiceChoice<PodmanServiceProtocol>[] = [
  { id: "tcp", labelKey: "ui.containers.service_tcp" },
  { id: "udp", labelKey: "ui.containers.service_udp" },
];

/** Where a container comes from, worded at the end of its row. */
const SOURCE_KEYS: Record<PodmanContainerSource, string> = {
  hub: "ui.containers.source_hub",
  declared: "ui.containers.source_declared",
  manual: "ui.containers.source_manual",
};
// A module of the hub's in the accent, the person's own in the secondary.
const SOURCE_TONES: Record<PodmanContainerSource, string> = {
  hub: "badge--accent",
  declared: "badge--secondary",
  manual: "badge--secondary",
};

/** How many characters of a digest's hex a hub container's row shows. */
const DIGEST_SHOWN_CHARS = 12;

/** The systems whose containers run in an account's Podman machine. */
const MACHINE_RUN_OS = ["windows", "darwin"];

/** The system whose machine starts with the account's Windows login. */
const WINDOWS_OS = "windows";

/** A volume in each system's own form, shown in the empty add field. */
const VOLUME_PLACEHOLDER_KEYS: Record<string, string> = {
  linux: "ui.containers.volume_placeholder_linux",
  windows: "ui.containers.volume_placeholder_windows",
  darwin: "ui.containers.volume_placeholder_darwin",
};
const VOLUME_PLACEHOLDER_DEFAULT_KEY = "ui.containers.volume_placeholder_linux";

interface ContainersPanelsProps {
  /** The machine this page's shells and journals reach. */
  deviceId: string;
  /** Where podman answers: `/agent/module/podman`. */
  basePath: string;
  isEditable: boolean;
  /** The system the machine's agent reports: `linux`, `windows`, `darwin`. */
  platformOs: string;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
  /** Each module's title as its manifest gives it, by name. */
  manifestTitles: Record<string, string>;
}

export function ContainersPanels({
  deviceId,
  basePath,
  isEditable,
  platformOs,
  want,
  manifestTitles,
}: ContainersPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  // Containers start, stop and crash on their own schedule; the machine's
  // own report is what says so, and its settings are a write like any other.
  const resource = useApiResource<PodmanDeviceView>(
    apiPath(basePath, { device_id: deviceId }),
    {
      invalidateOn: [
        { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
        { type: HUB_EVENT_CONFIG },
      ],
    },
  );

  const saved = resource.data;
  const containersDraft = useDraft(saved, containersOf);
  const mirrorsDraft = useDraft(saved, mirrorsOf);
  const containers = containersDraft.draft ?? [];
  const setContainers = containersDraft.setDraft;
  const mirrors = mirrorsDraft.draft ?? [];
  const setMirrors = mirrorsDraft.setDraft;
  const [isMirrorsBusy, setIsMirrorsBusy] = useState(false);
  const [mirrorsError, setMirrorsError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [shellTarget, setShellTarget] = useState<string | null>(null);
  const [journalTarget, setJournalTarget] = useState<string | null>(null);
  const isMachineRun = MACHINE_RUN_OS.includes(platformOs);
  const report = saved === null ? null : podmanReport(saved, isMachineRun);
  const mirrorsSettle = useSettledApply(report, want);
  const containersSettle = useSettledApply(report, want);

  const isDirty = containersDraft.isDirty;
  const filledMirrors = mirrors.filter((mirror) => mirror !== "");
  const isMirrorsDirty =
    saved !== null &&
    JSON.stringify(filledMirrors) !== JSON.stringify(saved.mirrors);

  const applyMirrors = async () => {
    setIsMirrorsBusy(true);
    setMirrorsError(null);
    mirrorsSettle.clear();
    try {
      resource.setData(
        await apiPost<PodmanDeviceView>(`${basePath}/mirror/set`, {
          device_id: deviceId,
          mirrors: filledMirrors,
        }),
      );
      const result = await apiPost<ApplyResult>(`${basePath}/apply`, {
        device_id: deviceId,
      });
      if (!result.is_applied) {
        setMirrorsError(describeApplyFailure(result));
        return;
      }
      mirrorsSettle.begin();
    } catch (cause: unknown) {
      setMirrorsError(describeError(cause));
    } finally {
      setIsMirrorsBusy(false);
    }
  };

  const applyContainers = async () => {
    setIsBusy(true);
    setError(null);
    containersSettle.clear();
    try {
      resource.setData(
        await apiPost<PodmanDeviceView>(`${basePath}/container/set`, {
          device_id: deviceId,
          containers,
        }),
      );
      const result = await apiPost<ApplyResult>(`${basePath}/apply`, {
        device_id: deviceId,
      });
      if (!result.is_applied) {
        setError(describeApplyFailure(result));
        return;
      }
      containersSettle.begin();
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
        `${basePath}/container/${action}`,
        { device_id: deviceId, name },
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

  const isRunNeeded = isMachineRun && (saved.machine?.account ?? "") === "";

  return (
    <>
      {!saved.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{t("ui.containers.not_installed")}</div>
        </div>
      )}

      {isMachineRun && (
        <ContainersRunSettings
          deviceId={deviceId}
          basePath={basePath}
          saved={saved}
          isEditable={isEditable}
          isWindows={platformOs === WINDOWS_OS}
          want={want}
          report={report}
          onSaved={resource.setData}
        />
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
        {isRunNeeded ? (
          <p className="field_hint">{t("ui.containers.run_needed")}</p>
        ) : saved.running.length === 0 ? (
          <p className="field_hint">{t("ui.containers.live_empty")}</p>
        ) : (
          <div className="container_rows">
            {saved.running.map((state) => (
              <div key={state.name}>
                <ContainerRow
                  state={state}
                  moduleLabel={moduleTitle(
                    state.module,
                    manifestTitles[state.module] ?? state.module,
                  )}
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
                  path={apiPath(`${basePath}/container/journal`, {
                    device_id: deviceId,
                    name: state.name,
                  })}
                  isOpen={journalTarget === state.name}
                />
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.containers.hub_title")}</h2>
        </div>
        <p className="field_hint">{t("ui.containers.hub_hint")}</p>
        {saved.hub_containers.length === 0 ? (
          <p className="field_hint">{t("ui.containers.hub_empty")}</p>
        ) : (
          <div className="container_rows">
            {saved.hub_containers.map((container) => (
              <HubContainerRow
                key={container.name}
                container={container}
                moduleLabel={moduleTitle(
                  container.module,
                  manifestTitles[container.module] ?? container.module,
                )}
              />
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
        {isRunNeeded ? (
          <p className="field_hint">{t("ui.containers.run_needed")}</p>
        ) : (
          <>
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
                    setMirrors((current) =>
                      current.filter((_, at) => at !== index),
                    )
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
          </>
        )}
        <ApplyBar
          isDirty={isMirrorsDirty}
          isBusy={isMirrorsBusy || mirrorsSettle.isSettling}
          label={t("ui.containers.mirrors_apply")}
          hint={t("ui.containers.mirrors_apply_hint")}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
          isApplyDisabled={isRunNeeded}
          error={mirrorsError}
          notice={appliedNotice(mirrorsSettle, report)}
          onReset={() => {
            mirrorsDraft.reset();
            mirrorsSettle.clear();
          }}
          onApply={() => void applyMirrors()}
        />
      </section>

      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.containers.declared_title")}</h2>
        </div>
        {isRunNeeded ? (
          <p className="field_hint">{t("ui.containers.run_needed")}</p>
        ) : (
          <>
            {containers.map((container, index) => (
              <ContainerEditor
                key={index}
                deviceId={deviceId}
                basePath={basePath}
                platformOs={platformOs}
                container={container}
                state={saved.running.find(
                  (state) => state.name === container.name,
                )}
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
          </>
        )}
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy || containersSettle.isSettling}
          label={t("ui.containers.containers_apply")}
          hint={t("ui.containers.containers_apply_hint")}
          warning={t("ui.containers.containers_apply_warning")}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
          isApplyDisabled={isRunNeeded}
          error={error}
          notice={appliedNotice(containersSettle, report)}
          onReset={() => {
            containersDraft.reset();
            containersSettle.clear();
          }}
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

function containersOf(view: PodmanDeviceView): PodmanContainer[] {
  return view.containers;
}

function mirrorsOf(view: PodmanDeviceView): string[] {
  return view.mirrors;
}

/** The module as the machine reports it, for an apply to wait on; on
 * Windows and macOS the stored account's machine is its one instance. */
function podmanReport(
  view: PodmanDeviceView,
  isMachineRun: boolean,
): ReportedModule {
  const account = view.machine?.account ?? "";
  const reported = view.machine_state;
  const isMachineUp =
    reported !== null && reported.account === account && reported.is_running;
  return {
    state: view.state,
    instances:
      isMachineRun && account !== ""
        ? [{ is_running: isMachineUp, code: "" }]
        : [],
  };
}

/** `Applied.` once an apply settled on a module that does not fail. */
function appliedNotice(
  settle: SettledApply,
  report: ReportedModule | null,
): string | null {
  return settle.isApplied && report !== null && !isFailing(report)
    ? t("ui.api.applied")
    : null;
}

/** A hub container's image as its row names it: the first source and the
 * start of the digest. */
function hubImage(container: PodmanHubContainer): string {
  const source = container.image.sources[0] ?? "";
  const hex = container.image.digest.replace(/^sha256:/, "");
  return `${source}@${hex.slice(0, DIGEST_SHOWN_CHARS)}`;
}

/** The image without its tag; the tag chips swap what follows the colon. */
function imageBase(image: string): string {
  const colon = image.lastIndexOf(":");
  return colon > image.lastIndexOf("/") ? image.slice(0, colon) : image;
}

/** The host ports the Ports rows publish, each once, in their order. */
function hostPorts(ports: string[]): number[] {
  const found: number[] = [];
  for (const mapping of ports) {
    const match = PORT_MAPPING_PATTERN.exec(mapping);
    const port = match === null ? 0 : Number(match[1]);
    if (port > 0 && !found.includes(port)) {
      found.push(port);
    }
  }
  return found;
}

/** The protocols the Ports rows publish one host port on. */
function publishedProtocols(
  ports: string[],
  port: number,
): PodmanServiceProtocol[] {
  const found = new Set<PodmanServiceProtocol>();
  for (const mapping of ports) {
    const match = PORT_MAPPING_PATTERN.exec(mapping);
    if (match !== null && Number(match[1]) === port) {
      found.add(match[2] === "udp" ? "udp" : "tcp");
    }
  }
  return SERVICE_PROTOCOLS.map((choice) => choice.id).filter((id) =>
    found.has(id),
  );
}

/** One port's service, `auto` for a port the list does not name. */
function serviceOf(container: PodmanContainer, port: number): PodmanService {
  return (
    container.services.find((service) => service.port === port) ?? {
      port,
      kind: "auto",
      scheme: "http",
      protocols: ["tcp"],
    }
  );
}

/** What Auto shows: the type the machine detected on the TCP port. */
function detectedWords(
  state: PodmanContainerState | undefined,
  port: number,
): string {
  const binding = state?.is_running
    ? state.host_bindings.find(
        (entry) =>
          entry.port === port &&
          entry.protocol === "tcp" &&
          entry.detected !== "",
      )
    : undefined;
  return binding === undefined
    ? t("ui.containers.service_pending")
    : t("ui.containers.service_detected", { kind: binding.detected });
}

interface ContainerEditorProps {
  deviceId: string;
  basePath: string;
  /** The system the machine's agent reports: `linux`, `windows`, `darwin`. */
  platformOs: string;
  container: PodmanContainer;
  /** The container as the machine last reported it, by its saved name. */
  state: PodmanContainerState | undefined;
  onChange: (patch: Partial<PodmanContainer>) => void;
  onRemove: () => void;
}

/** A Browse… waiting on the path window: where it opens, and what takes
 * the folder chosen. */
interface FolderBrowse {
  startPath: string;
  pick: (folder: string) => void;
}

function ContainerEditor({
  deviceId,
  basePath,
  platformOs,
  container,
  state,
  onChange,
  onRemove,
}: ContainerEditorProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [tags, setTags] = useState<string[] | null>(null);
  const [isLoadingTags, setIsLoadingTags] = useState(false);
  const [browse, setBrowse] = useState<FolderBrowse | null>(null);

  const ports = hostPorts(container.ports);

  const setPorts = (next: string[]) => {
    const kept = hostPorts(next);
    onChange({
      ports: next,
      services: container.services.filter((service) =>
        kept.includes(service.port),
      ),
    });
  };

  // The list keeps the Ports order and names no auto port.
  const setService = (service: PodmanService) => {
    onChange({
      services: ports
        .map((port) =>
          port === service.port ? service : serviceOf(container, port),
        )
        .filter((entry) => entry.kind !== "auto"),
    });
  };

  const setKind = (port: number, id: string) => {
    const kind = SERVICE_KINDS.find((choice) => choice.id === id)?.id;
    if (kind === undefined) {
      return;
    }
    const current = serviceOf(container, port);
    setService({
      ...current,
      kind,
      protocols:
        kind === "port"
          ? publishedProtocols(container.ports, port)
          : current.protocols,
    });
  };

  const setScheme = (port: number, id: string) => {
    const scheme = SERVICE_SCHEMES.find((choice) => choice.id === id)?.id;
    if (scheme !== undefined) {
      setService({ ...serviceOf(container, port), scheme });
    }
  };

  const setProtocol = (
    port: number,
    protocol: PodmanServiceProtocol,
    isOn: boolean,
  ) => {
    const current = serviceOf(container, port);
    setService({
      ...current,
      protocols: SERVICE_PROTOCOLS.map((choice) => choice.id).filter((id) =>
        id === protocol ? isOn : current.protocols.includes(id),
      ),
    });
  };

  const loadTags = async () => {
    setIsLoadingTags(true);
    try {
      const found = await apiGet<{ tags: string[] }>(`${basePath}/tag`, {
        device_id: deviceId,
        image: imageBase(container.image),
      });
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
          onChange={setPorts}
          placeholder="8080:80"
          emptyText="host_port:container_port"
        />
        <StringListEditor
          label={t("ui.containers.volumes")}
          values={container.volumes}
          onChange={(volumes) => onChange({ volumes })}
          placeholder={t(
            VOLUME_PLACEHOLDER_KEYS[platformOs] ??
              VOLUME_PLACEHOLDER_DEFAULT_KEY,
          )}
          emptyText="host_path:container_path"
          onBrowse={(startPath, pick) => setBrowse({ startPath, pick })}
          browseLabel={t("ui.containers.browse")}
        />
        <StringListEditor
          label={t("ui.containers.environment")}
          values={container.environment}
          onChange={(environment) => onChange({ environment })}
          placeholder="KEY=value"
          emptyText="KEY=value"
        />
      </div>
      {ports.length > 0 && (
        <div className="container_services">
          <span className="field_label">{t("ui.containers.services")}</span>
          {ports.map((port) => {
            const service = serviceOf(container, port);
            return (
              <div key={port} className="container_service">
                <span className="container_service_port">{port}</span>
                <Picker
                  className="container_service_choice"
                  options={SERVICE_KINDS.map((choice) => ({
                    id: choice.id,
                    name: t(choice.labelKey),
                  }))}
                  value={service.kind}
                  onChange={(id) => setKind(port, id)}
                  label={t("ui.containers.services")}
                  isLabelHidden
                />
                {service.kind === "auto" &&
                  publishedProtocols(container.ports, port).includes("tcp") && (
                    <span className="field_hint">
                      {detectedWords(state, port)}
                    </span>
                  )}
                {service.kind === "web" && (
                  <Picker
                    className="container_service_choice"
                    options={SERVICE_SCHEMES.map((choice) => ({
                      id: choice.id,
                      name: t(choice.labelKey),
                    }))}
                    value={service.scheme}
                    onChange={(id) => setScheme(port, id)}
                    label={t("ui.containers.service_web")}
                    isLabelHidden
                  />
                )}
                {service.kind === "port" &&
                  SERVICE_PROTOCOLS.map((choice) => {
                    const isOn = service.protocols.includes(choice.id);
                    return (
                      <label
                        key={choice.id}
                        className="container_service_protocol"
                      >
                        <input
                          type="checkbox"
                          checked={isOn}
                          disabled={isOn && service.protocols.length === 1}
                          onChange={(event) =>
                            setProtocol(port, choice.id, event.target.checked)
                          }
                        />
                        {t(choice.labelKey)}
                      </label>
                    );
                  })}
              </div>
            );
          })}
          <span className="field_hint">{t("ui.containers.services_hint")}</span>
        </div>
      )}
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
      {browse !== null && (
        <DirectoryPickerModal
          deviceId={deviceId}
          startPath={browse.startPath}
          onPick={(folder) => {
            browse.pick(folder);
            setBrowse(null);
          }}
          onCancel={() => setBrowse(null)}
        />
      )}
    </div>
  );
}

interface ContainerRowProps {
  onJournal: () => void;
  state: PodmanContainerState;
  /** The title of the module that runs it, for a hub container. */
  moduleLabel: string;
  onAction: (action: string) => void;
  onShell: () => void;
}

function ContainerRow({
  state,
  moduleLabel,
  onAction,
  onShell,
  onJournal,
}: ContainerRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const isHub = state.source === "hub";
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
      {isHub && <span className="container_row_module">{moduleLabel}</span>}
      <div className="container_row_actions">
        <button
          type="button"
          className="button button--small"
          onClick={onJournal}
        >
          <Icon name="file" size={12} />
          {t("ui.containers.row_journal")}
        </button>
        {!isHub && state.is_running && (
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
        )}
        {!isHub && !state.is_running && (
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
      <span className={`badge ${SOURCE_TONES[state.source]}`}>
        {t(SOURCE_KEYS[state.source])}
      </span>
    </div>
  );
}

interface HubContainerRowProps {
  container: PodmanHubContainer;
  /** The title of the module that runs it. */
  moduleLabel: string;
}

/** One hub container as the hub composes it, read only. */
function HubContainerRow({ container, moduleLabel }: HubContainerRowProps) {
  return (
    <div className="container_row">
      <span className="container_row_name">{container.name}</span>
      <span className="container_row_module">{moduleLabel}</span>
      <span className="container_row_image">{hubImage(container)}</span>
      {container.ports.length > 0 && (
        <span className="container_row_status">
          {container.ports.join(", ")}
        </span>
      )}
      {container.volumes.length > 0 && (
        <span className="container_row_status">
          {container.volumes.join(", ")}
        </span>
      )}
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
            socketPath={apiPath("/ws/agent/terminal", {
              device_id: deviceId,
              container: name,
            })}
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
        {failedCode !== null && (
          <div className="container_shell_status container_shell_status--warn">
            {t("ui.containers.shell_failed", { code: failedCode })}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
