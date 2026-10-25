import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";

import { apiPath, apiPost, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { AiToolsPanel } from "../components/ai_tools_panel";
import { ContainersPanels } from "../components/containers_panels";
import { DevicePick } from "../components/device_pick";
import { ErrorPanel } from "../components/error_panel";
import { GiteaPanels } from "../components/gitea_panels";
import { Icon } from "../components/icon";
import { InstancesPanel } from "../components/instances_panel";
import { ModuleIcon } from "../components/module_icon";
import { ModuleLog } from "../components/module_log";
import { ModulePicker } from "../components/module_picker";
import { RemoteDesktopPanels } from "../components/remote_desktop_panels";
import { SambaPanels } from "../components/samba_panels";
import { Spinner } from "../components/spinner";
import { StatusDot } from "../components/status_dot";
import { TerminalPanels } from "../components/terminal_panels";
import { VscodeTerms } from "../components/vscode_terms";
import { ZfsPanels } from "../components/zfs_panels";
import { hasWord, t, useLanguage } from "../i18n";
import { MODULE_DESCRIPTORS } from "../module_descriptors";
import { moduleTitle, withModuleTitle } from "../module_title";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import {
  HUB_EVENT_CONFIG,
  HUB_EVENT_DEVICE_REPORT,
  HUB_EVENT_DEVICES,
  HUB_EVENT_TASK,
} from "../use_hub_events";
import { usePageMemory } from "../use_page_memory";
import type { IconName } from "../components/icon";
import type { PickableModule } from "../components/module_picker";
import type { StatusTone } from "../components/status_dot";
import type { ModuleDescriptor } from "../module_descriptors";
import type {
  DeviceModuleListView,
  DeviceModuleRequest,
  DeviceModuleView,
  DeviceOnlineView,
  DeviceRequest,
  DevicesOnlineResponse,
  TaskStarted,
  VscodeDeviceView,
} from "../api_types";

import "./modules_page.css";

/**
 * Every module a machine hosts, on one page.
 *
 * The page opens on a machine the way Terminals and Files do. The Module
 * configuration panel is split: down the left, one row per module the
 * machine's page shows, its glyph, its title and the dot of the state its
 * agent last reported, with a `+` at the end that picks which modules the
 * page shows for this machine; a module the machine's system cannot run is
 * greyed out in the picker and never listed. On the right, the picked
 * module: its state line, its own panels while Configure holds them open,
 * its output, the lines the agent sends up while it installs or uninstalls
 * and the tail of its own journal on the machine the rest of the time,
 * polled while the page is open, and the presses at the right edge: the four
 * that write what the hub wants of the module, and Configure, which opens
 * the module's own panels and closes them on the next press. The first
 * Configure on a module the hub holds no configuration for imports what the
 * machine already has, so the first push changes nothing on it. VS Code
 * shows Microsoft's terms on top, and nothing else until they are accepted
 * for the machine. The programs run as an account are drawn by one panel
 * from the descriptor table. A module installing with a code shows its words
 * on top, and an install waiting on a restart offers one. The machine, the
 * module and the sections open are kept between visits, until a reload.
 */

/** The machine a module's own panels are pointed at. */
interface PanelTarget {
  deviceId: string;
  /** Where the module answers: `/agent/module/<module>`. */
  basePath: string;
  /** Whether anything here can be applied. Offline machines take no orders. */
  isEditable: boolean;
  /** The system the machine's agent reports: `linux`, `windows`, `darwin`. */
  platformOs: string;
  /** Whether the machine reports the module installing. */
  isInstalling: boolean;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
  /** Each module's title as its manifest gives it, by name. */
  manifestTitles: Record<string, string>;
}

/** The modules this page has panels for, in tab order. */
const MODULE_PANELS: Record<string, (target: PanelTarget) => ReactNode> = {
  samba: (target) => (
    <SambaPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
      isWindows={target.platformOs === WINDOWS_OS}
      isSystemServer={
        target.platformOs !== "" && target.platformOs !== LINUX_OS
      }
    />
  ),
  gitea: (target) => (
    <GiteaPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
    />
  ),
  podman: (target) => (
    <ContainersPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
      platformOs={target.platformOs}
      want={target.want}
      manifestTitles={target.manifestTitles}
    />
  ),
  ...Object.fromEntries(
    Object.values(MODULE_DESCRIPTORS).map((descriptor) => [
      descriptor.name,
      instancesPanel(descriptor),
    ]),
  ),
  terminal: (target) => (
    <TerminalPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
    />
  ),
  remote_desktop: (target) => (
    <RemoteDesktopPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
    />
  ),
  zfs: (target) => (
    <ZfsPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
    />
  ),
};

/** The tabs' order: the modules every system runs first. */
const TAB_ORDER = [
  "samba",
  "terminal",
  "remote_desktop",
  "gitea",
  "vscode",
  "code_server",
  "cloudcli",
  "codeg",
  "podman",
  "zfs",
];
const PAGE_MODULES = TAB_ORDER.filter((name) => name in MODULE_PANELS);

/** The method of a module the agent's package carries: always a tab, never in
 * the picker, and none of the four presses. */
const CARRIED_METHOD = "agent";

/** The one system whose file share is Samba; the others serve with their own. */
const LINUX_OS = "linux";

/** The system that starts a program run as an account only with its login. */
const WINDOWS_OS = "windows";

/** The module whose tab opens only once its terms are accepted. */
const TERMS_MODULE = "vscode";

/** The modules whose block imports what the machine already has. */
const IMPORTING_MODULES = ["samba", "gitea", "podman"];

/** The word each state wears on its tab; a token outside the table reads as
 * a machine that has not reported. */
const STATE_KEYS: Record<string, string> = {
  absent: "state.absent",
  installed: "state.installed",
  stopped: "state.stopped",
  running: "state.running",
  installing: "state.installing",
  uninstalling: "state.uninstalling",
  queued: "state.queued",
  failed: "state.failed",
  install_failed: "state.install_failed",
  unsupported: "state.unsupported",
};
const STATE_NEVER_REPORTED_KEY = "state.never_reported";

/** The states in which the software is on the machine. */
const PRESENT_STATES = ["installed", "stopped", "running"];

/** The states of a module whose last step failed: the tab shows the code's
 * words, and Uninstall is live. */
const FAILED_STATES = ["failed", "install_failed"];

/** The wants under which the machine applies the hub's configuration, so a
 * `failed` row under one of them is a refused configuration. */
const CONFIGURING_WANTS = ["running", "stopped"];

/** The states in transit: the tab turns a spinner beside its word and
 * every button of the tab is disabled. */
const BUSY_STATES = ["installing", "uninstalling", "queued"];

/** The transient a press shows until the machine reports otherwise. */
const PRESSED_STATES: Record<ModuleAction | "configure", string> = {
  install: "installing",
  uninstall: "uninstalling",
  start: "queued",
  stop: "queued",
  configure: "queued",
};

/** The states whose code the tab words as a notice at its top: what holds
 * up an install, and what is missing of software that is partly there. */
const NOTICED_STATES = ["installing", "absent"];

/** The code of an install that goes on only after the machine restarts. */
const REBOOT_REQUIRED_CODE = "reboot_required";

/** The route that restarts a managed machine, as the device drawer's Reboot. */
const REBOOT_PATH = "/hub/device/reboot";

/** How long a press's transient holds before the machine's own report, or
 * its silence, takes over. */
const PRESSED_HOLD_MS = 2 * 60 * 1000;

/** The four presses, each the route it writes with. */
type ModuleAction = "install" | "start" | "stop" | "uninstall";

const ACTION_ICONS: Record<ModuleAction, IconName> = {
  install: "download",
  start: "play",
  stop: "stop",
  uninstall: "trash",
};

const ACTION_KEYS: Record<ModuleAction, string> = {
  install: "ui.modules.install",
  start: "ui.modules.start",
  stop: "ui.modules.stop",
  uninstall: "ui.modules.uninstall",
};

/** What the chips move on: an agent's channel opening or ending. */
const ONLINE_INVALIDATE_ON = [{ type: HUB_EVENT_DEVICES }];

/** The query a page link carries to open on one machine. */
const DEVICE_QUERY = "device";
/** The query a link opens a tab with, as the device drawer's desktop line does. */
const MODULE_QUERY = "module";

/** How tall the panel is while the first list is still on its way. */
const SKELETON_HEIGHT_PX = 120;

/** The size of a module's glyph in its row. */
const ROW_ICON_PX = 16;

/** The panel one program run as an account is drawn with, from its descriptor. */
function instancesPanel(
  descriptor: ModuleDescriptor,
): (target: PanelTarget) => ReactNode {
  return (target) => (
    <InstancesPanel
      descriptor={descriptor}
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
      want={target.want}
      isWindows={target.platformOs === WINDOWS_OS}
      isInstalling={target.isInstalling}
    />
  );
}

export function ModulesPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const online = useApiResource<DevicesOnlineResponse>("/hub/device/online", {
    invalidateOn: ONLINE_INVALIDATE_ON,
  });
  const [searchParams] = useSearchParams();
  // The machine, the tab and the open sections are kept between visits.
  const [selectedId, setSelectedId] = usePageMemory<string | null>(
    "modules.device",
    null,
  );
  const [activeModule, setActiveModule] = usePageMemory<string | null>(
    "modules.tab",
    null,
  );
  const [busyAction, setBusyAction] = useState<string | null>(null);
  // `<device>:<module>` to the transient a press shows, the state the module
  // was in at the press, and when the press was made.
  const [presses, setPresses] = useState<Record<string, Press>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  // The `<device>:<module>` pairs whose configuration section is open.
  const [configuredKeys, setConfiguredKeys] = usePageMemory<string[]>(
    "modules.configured",
    [],
  );
  const confirm = useConfirm();

  // A link from a device's drawer names the machine it came from.
  const askedDeviceId = searchParams.get(DEVICE_QUERY);
  useEffect(() => {
    if (askedDeviceId !== null) {
      setSelectedId(askedDeviceId);
    }
  }, [askedDeviceId, setSelectedId]);
  // The tab a link asked for, opened once the machine's tabs include it.
  const askedModule = useRef(searchParams.get(MODULE_QUERY));

  const devices = online.data?.devices ?? [];
  const selectedDevice =
    devices.find((device) => device.device_id === selectedId) ?? null;
  const deviceId = selectedDevice?.device_id ?? null;

  const modules = useApiResource<DeviceModuleListView>(
    deviceId === null
      ? null
      : apiPath("/agent/module", { device_id: deviceId }),
    {
      invalidateOn:
        deviceId === null
          ? []
          : [
              { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
              { type: HUB_EVENT_CONFIG },
              { type: HUB_EVENT_TASK },
            ],
    },
  );

  // VS Code's terms, read while its tab is the current one.
  const terms = useApiResource<VscodeDeviceView>(
    deviceId === null || activeModule !== TERMS_MODULE
      ? null
      : apiPath(`/agent/module/${TERMS_MODULE}`, { device_id: deviceId }),
    { invalidateOn: [{ type: HUB_EVENT_CONFIG }] },
  );

  const reportedRows = rowsByName(modules.data);
  const rows = withPresses(reportedRows, deviceId, presses);
  const shownNames = shownModules(selectedDevice, rows);
  const shownKey = shownNames.join(",");

  // Whichever tab is current has to still be one the page shows.
  useEffect(() => {
    const shown = shownKey === "" ? [] : shownKey.split(",");
    const asked = askedModule.current;
    if (asked !== null && shown.includes(asked)) {
      askedModule.current = null;
      setActiveModule(asked);
      return;
    }
    setActiveModule((current) =>
      current !== null && shown.includes(current)
        ? current
        : (shown[0] ?? null),
    );
  }, [shownKey, setActiveModule]);

  const activeRow = activeModule === null ? undefined : rows[activeModule];
  const isAgentOnline = modules.data?.is_agent_online ?? false;

  // With one machine there is nothing to pick.
  const onlyDeviceId =
    devices.length === 1 ? (devices[0]?.device_id ?? null) : null;
  useEffect(() => {
    if (onlyDeviceId !== null && askedDeviceId === null) {
      setSelectedId(onlyDeviceId);
    }
  }, [onlyDeviceId, askedDeviceId, setSelectedId]);

  const noteShown = (shown: string[]) => {
    if (online.data === null || deviceId === null) {
      return;
    }
    online.setData({
      devices: online.data.devices.map((device) =>
        device.device_id === deviceId
          ? { ...device, shown_module: shown }
          : device,
      ),
    });
  };

  // A press is answered once the machine reports the module in another
  // state, or after the hold.
  useEffect(() => {
    if (deviceId === null) {
      return;
    }
    setPresses((current) =>
      dropAnswered(current, deviceId, rowsByName(modules.data), Date.now()),
    );
  }, [deviceId, modules.data]);

  useEffect(() => {
    const times = Object.values(presses).map((press) => press.at);
    if (times.length === 0) {
      return;
    }
    const wait = Math.max(0, Math.min(...times) + PRESSED_HOLD_MS - Date.now());
    const timer = window.setTimeout(() => {
      setPresses((current) => dropExpired(current, Date.now()));
    }, wait);
    return () => window.clearTimeout(timer);
  }, [presses]);

  const notePress = (module: string, action: ModuleAction | "configure") => {
    if (deviceId === null) {
      return;
    }
    const from = reportedRows[module]?.state ?? "";
    // Configure on a running module changes no state the tab could wait on.
    if (action === "configure" && from === "running") {
      return;
    }
    setPresses((current) => ({
      ...current,
      [configuredKey(deviceId, module)]: {
        state: PRESSED_STATES[action],
        from,
        at: Date.now(),
      },
    }));
  };

  const act = async (action: ModuleAction) => {
    if (deviceId === null || activeModule === null) {
      return;
    }
    setBusyAction(action);
    setActionError(null);
    const request: DeviceModuleRequest = {
      device_id: deviceId,
      module: activeModule,
    };
    try {
      const answer = await apiPost<DeviceModuleListView>(
        `/agent/module/${action}`,
        request,
      );
      notePress(activeModule, action);
      modules.setData(answer);
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setBusyAction(null);
    }
  };

  // Configure wants the module running, and imports what the machine has
  // first where the hub holds nothing for it yet. Pressed while its section
  // is open, it closes the section and asks nothing of the machine.
  const configure = async () => {
    if (deviceId === null || activeModule === null || activeRow === undefined) {
      return;
    }
    const key = configuredKey(deviceId, activeModule);
    if (configuredKeys.includes(key)) {
      setConfiguredKeys((current) => current.filter((held) => held !== key));
      return;
    }
    setBusyAction("configure");
    setActionError(null);
    const request: DeviceModuleRequest = {
      device_id: deviceId,
      module: activeModule,
    };
    try {
      if (
        !activeRow.is_configured &&
        IMPORTING_MODULES.includes(activeModule)
      ) {
        const imported: DeviceRequest = { device_id: deviceId };
        await apiPost(`/agent/module/${activeModule}/import`, imported);
      }
      const answer = await apiPost<DeviceModuleListView>(
        "/agent/module/start",
        request,
      );
      notePress(activeModule, "configure");
      modules.setData(answer);
      setConfiguredKeys((current) =>
        current.includes(key) ? current : [...current, key],
      );
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setBusyAction(null);
    }
  };

  const restart = async () => {
    if (deviceId === null) {
      return;
    }
    setBusyAction("restart");
    setActionError(null);
    const request: DeviceRequest = { device_id: deviceId };
    try {
      await apiPost<TaskStarted>(REBOOT_PATH, request);
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setBusyAction(null);
    }
  };

  const askRestart = () => {
    if (selectedDevice === null) {
      return;
    }
    confirm.ask({
      title: t("ui.modules.restart_title", { device: selectedDevice.name }),
      body: t("ui.modules.restart_body"),
      confirmLabel: t("ui.modules.restart_confirm"),
      onConfirm: () => void restart(),
    });
  };

  const askUninstall = () => {
    if (selectedDevice === null || activeRow === undefined) {
      return;
    }
    confirm.ask({
      title: t("ui.modules.uninstall_title", {
        module: moduleTitle(activeRow.name, activeRow.title),
        device: selectedDevice.name,
      }),
      body: activeRow.is_data_kept
        ? t("ui.modules.uninstall_body")
        : t("ui.modules.uninstall_body_data"),
      confirmLabel: t("ui.modules.uninstall"),
      onConfirm: () => void act("uninstall"),
    });
  };

  if (online.error !== null && devices.length === 0) {
    return (
      <div className="page">
        <h1>{t("ui.nav.modules")}</h1>
        <ErrorPanel message={online.error} onRetry={online.reload} />
      </div>
    );
  }

  const panels =
    activeModule === null ? undefined : MODULE_PANELS[activeModule];
  const isCarriedRow = activeRow !== undefined && isCarried(activeRow);
  const isConfiguring =
    deviceId !== null &&
    activeModule !== null &&
    (isCarriedRow ||
      configuredKeys.includes(configuredKey(deviceId, activeModule)));
  const isBusy = busyAction !== null;
  const isInTransit =
    activeRow !== undefined && BUSY_STATES.includes(activeRow.state);
  const canAct =
    activeRow !== undefined && isAgentOnline && !isBusy && !isInTransit;
  const isPresent =
    activeRow !== undefined && PRESENT_STATES.includes(activeRow.state);
  const isConfigRefused =
    activeRow !== undefined &&
    activeRow.state === "failed" &&
    CONFIGURING_WANTS.includes(activeRow.want);
  const termsView =
    terms.data !== null && terms.data.device_id === deviceId
      ? terms.data
      : null;
  const isTermsGated =
    activeModule === TERMS_MODULE && termsView?.is_terms_accepted !== true;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{t("ui.nav.modules")}</h1>
        </div>
      </div>

      <DevicePick
        devices={devices}
        isLoading={online.isLoading}
        selected={selectedId}
        onSelect={setSelectedId}
      />

      {deviceId !== null && <AiToolsPanel deviceId={deviceId} />}

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.modules.tabs_title")}</h2>
        </div>
        {selectedDevice === null || deviceId === null ? (
          <div className="placeholder">
            <span>{t("ui.modules.no_pick")}</span>
            <span className="faint">{t("ui.modules.no_pick_hint")}</span>
          </div>
        ) : modules.error !== null && modules.data === null ? (
          <ErrorPanel message={modules.error} onRetry={modules.reload} />
        ) : modules.data === null ? (
          <div className="skeleton" style={{ height: SKELETON_HEIGHT_PX }} />
        ) : (
          <div className="modules_split">
            <div
              className="modules_list"
              role="tablist"
              aria-label={t("ui.modules.tabs_label")}
            >
              {shownNames.length === 0 && (
                <span className="faint">{t("ui.modules.no_tabs")}</span>
              )}
              {shownNames
                .map((name) => rows[name])
                .filter((row) => row !== undefined)
                .map((row) => (
                  <ModuleListRow
                    key={row.name}
                    row={row}
                    isOn={row.name === activeModule}
                    onSelect={setActiveModule}
                  />
                ))}
              <div className="modules_list_add">
                <ModulePicker
                  deviceId={deviceId}
                  modules={pickable(rows)}
                  shown={shownNames}
                  onChanged={noteShown}
                />
              </div>
            </div>

            {activeRow !== undefined && (
              <div className="modules_detail">
                <div className="modules_detail_head">
                  <h3>{moduleTitle(activeRow.name, activeRow.title)}</h3>
                  {BUSY_STATES.includes(activeRow.state) && (
                    <Spinner size={11} />
                  )}
                  <StatusDot
                    tone={dotTone(activeRow)}
                    label={stateWord(activeRow)}
                  />
                </div>

                {activeModule === TERMS_MODULE && (
                  <>
                    {termsView !== null ? (
                      <VscodeTerms
                        deviceId={deviceId}
                        view={termsView}
                        onRecorded={terms.setData}
                      />
                    ) : terms.error !== null ? (
                      <ErrorPanel
                        message={terms.error}
                        onRetry={terms.reload}
                      />
                    ) : (
                      <div
                        className="skeleton"
                        style={{ height: SKELETON_HEIGHT_PX }}
                      />
                    )}
                  </>
                )}

                {!isTermsGated && (
                  <>
                    {!isAgentOnline && (
                      <div className="notice notice--warn">
                        <Icon name="alert" size={15} />
                        <div className="notice_body">
                          {t("ui.modules.agent_offline")}
                        </div>
                      </div>
                    )}
                    {NOTICED_STATES.includes(activeRow.state) &&
                      activeRow.code !== "" && (
                        <div className="notice notice--warn modules_install_notice">
                          <Icon name="alert" size={15} />
                          <div className="notice_body">
                            <span>
                              {wordedCode(activeRow) ?? activeRow.code}
                            </span>
                            {activeRow.code === REBOOT_REQUIRED_CODE && (
                              <button
                                type="button"
                                className="button button--small"
                                disabled={!isAgentOnline || isBusy}
                                onClick={askRestart}
                              >
                                {busyAction === "restart" ? (
                                  <Spinner size={13} />
                                ) : (
                                  <Icon name="refresh" size={13} />
                                )}
                                {t("ui.modules.restart_now")}
                              </button>
                            )}
                          </div>
                        </div>
                      )}
                    {FAILED_STATES.includes(activeRow.state) && (
                      <div className="notice notice--error">
                        <Icon name="alert" size={15} />
                        <div className="notice_body">
                          {describeFailure(activeRow)}
                        </div>
                      </div>
                    )}
                    {panels !== undefined && isConfiguring && (
                      <fieldset
                        className="modules_config"
                        disabled={!isAgentOnline}
                      >
                        {panels({
                          deviceId,
                          basePath: `/agent/module/${activeModule}`,
                          isEditable: isAgentOnline,
                          platformOs: selectedDevice.platform.os ?? "",
                          isInstalling: activeRow.state === "installing",
                          want: activeRow.want,
                          manifestTitles: manifestTitlesOf(modules.data),
                        })}
                      </fieldset>
                    )}
                    {!isCarriedRow && (
                      <ModuleLog
                        key={`${deviceId}:${activeRow.name}`}
                        deviceId={deviceId}
                        row={activeRow}
                        isAgentOnline={isAgentOnline}
                      />
                    )}
                    {!isCarriedRow && (
                      <div className="modules_actions">
                        <ActionButton
                          action="install"
                          isEnabled={
                            canAct &&
                            (activeRow.state === "absent" ||
                              activeRow.state === "install_failed" ||
                              isRetried(activeRow, "installed"))
                          }
                          disabledReason={
                            isPresent
                              ? t("ui.modules.install_present")
                              : undefined
                          }
                          isBusy={busyAction === "install"}
                          onClick={() => void act("install")}
                        />
                        <ActionButton
                          action="start"
                          isEnabled={
                            canAct &&
                            (activeRow.state === "installed" ||
                              activeRow.state === "stopped" ||
                              isUnclaimed(activeRow) ||
                              isRetried(activeRow, "running"))
                          }
                          isBusy={busyAction === "start"}
                          onClick={() => void act("start")}
                        />
                        <ActionButton
                          action="stop"
                          isEnabled={
                            canAct &&
                            (activeRow.state === "running" ||
                              (activeRow.state === "installed" &&
                                activeRow.is_active) ||
                              isRetried(activeRow, "stopped"))
                          }
                          isBusy={busyAction === "stop"}
                          onClick={() => void act("stop")}
                        />
                        <ActionButton
                          action="uninstall"
                          isEnabled={
                            canAct &&
                            (isPresent ||
                              FAILED_STATES.includes(activeRow.state))
                          }
                          disabledReason={
                            activeRow.state === "absent"
                              ? t("ui.modules.uninstall_absent")
                              : undefined
                          }
                          isBusy={busyAction === "uninstall"}
                          onClick={askUninstall}
                        />
                        <button
                          type="button"
                          className={
                            isConfiguring ? "button" : "button button--primary"
                          }
                          disabled={!canAct || !(isPresent || isConfigRefused)}
                          aria-expanded={isConfiguring}
                          onClick={() => void configure()}
                        >
                          {busyAction === "configure" ? (
                            <Spinner size={13} />
                          ) : (
                            <Icon name="settings" size={14} />
                          )}
                          {t(
                            isConfiguring
                              ? "ui.modules.configure_close"
                              : "ui.modules.configure",
                          )}
                        </button>
                      </div>
                    )}

                    {actionError !== null && (
                      <div className="notice notice--error">
                        <Icon name="alert" size={15} />
                        <div className="notice_body">{actionError}</div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      {confirm.modal}
    </div>
  );
}

interface ActionButtonProps {
  action: ModuleAction;
  isEnabled: boolean;
  /** Why the press is dead, shown on hover while it is. */
  disabledReason?: string;
  isBusy: boolean;
  onClick: () => void;
}

function ActionButton({
  action,
  isEnabled,
  disabledReason,
  isBusy,
  onClick,
}: ActionButtonProps) {
  return (
    <button
      type="button"
      className={`button ${action === "uninstall" ? "button--danger" : ""}`}
      disabled={!isEnabled}
      title={isEnabled ? undefined : disabledReason}
      onClick={onClick}
    >
      {isBusy ? (
        <Spinner size={13} />
      ) : (
        <Icon name={ACTION_ICONS[action]} size={14} />
      )}
      {t(ACTION_KEYS[action])}
    </button>
  );
}

/** The page's modules, by name, out of everything the device could run. */
function rowsByName(
  list: DeviceModuleListView | null,
): Record<string, DeviceModuleView> {
  const rows: Record<string, DeviceModuleView> = {};
  for (const row of list?.modules ?? []) {
    if (PAGE_MODULES.includes(row.name)) {
      rows[row.name] = row;
    }
  }
  return rows;
}

/** Every module's title as its manifest gives it, by name. */
function manifestTitlesOf(
  list: DeviceModuleListView | null,
): Record<string, string> {
  return Object.fromEntries(
    (list?.modules ?? []).map((row) => [row.name, row.title]),
  );
}

/** Which tabs the page shows: what the row stores, else what the machine
 * reports; never a module the machine's system cannot run. */
function shownModules(
  device: DeviceOnlineView | null,
  rows: Record<string, DeviceModuleView>,
): string[] {
  if (device === null) {
    return [];
  }
  const runnable = PAGE_MODULES.filter(
    (name) => rows[name]?.is_supported !== false,
  );
  if (device.shown_module.length > 0) {
    return runnable.filter(
      (name) => isCarried(rows[name]) || device.shown_module.includes(name),
    );
  }
  return runnable.filter(
    (name) => isCarried(rows[name]) || rows[name]?.state !== "unknown",
  );
}

/** Whether the machine has the module and the hub holds no want for it, as
 * after a reset or a new join: Start gives it one. */
function isUnclaimed(row: DeviceModuleView): boolean {
  return (
    row.want === "" &&
    (row.state === "installed" ||
      row.state === "stopped" ||
      row.state === "running")
  );
}

/** Whether the agent's own package carries the module. */
function isCarried(row: DeviceModuleView | undefined): boolean {
  return row?.method === CARRIED_METHOD;
}

/** Whether a failed module's own press tries again: the one of what it was
 * asked for. */
function isRetried(row: DeviceModuleView, want: string): boolean {
  return row.state === "failed" && row.want === want;
}

/** Every module the picker can show, named by the catalog's title for it
 * and otherwise by its manifest's. */
function pickable(rows: Record<string, DeviceModuleView>): PickableModule[] {
  return PAGE_MODULES.filter((name) => !isCarried(rows[name])).map((name) => ({
    name,
    title: moduleTitle(name, rows[name]?.title ?? name),
    isSupported: rows[name]?.is_supported !== false,
  }));
}

interface ModuleListRowProps {
  row: DeviceModuleView;
  isOn: boolean;
  onSelect: (name: string) => void;
}

/** One row of the module list: the module's glyph, its title and a dot. */
function ModuleListRow({ row, isOn, onSelect }: ModuleListRowProps) {
  const title = moduleTitle(row.name, row.title);
  return (
    <button
      type="button"
      role="tab"
      aria-selected={isOn}
      className={`modules_list_row ${isOn ? "modules_list_row--on" : ""}`}
      title={title}
      onClick={() => onSelect(row.name)}
    >
      <ModuleIcon name={row.name} size={ROW_ICON_PX} />
      <span className="modules_list_row_title">{title}</span>
      {BUSY_STATES.includes(row.state) && <Spinner size={11} />}
      <StatusDot tone={dotTone(row)} />
    </button>
  );
}

/** The word a module's state wears; a token outside the table reads as a
 * machine that has not reported. */
function stateWord(row: DeviceModuleView): string {
  return t(STATE_KEYS[row.state] ?? STATE_NEVER_REPORTED_KEY);
}

function dotTone(row: DeviceModuleView): StatusTone {
  if (row.state === "running" || (row.state === "installed" && row.is_active)) {
    return "ok";
  }
  if (BUSY_STATES.includes(row.state)) {
    return "warn";
  }
  if (FAILED_STATES.includes(row.state) || row.state === "stopped") {
    return "error";
  }
  return "idle";
}

/** A press the machine has not answered yet. */
interface Press {
  /** The transient the tab shows meanwhile. */
  state: string;
  /** The module's reported state at the press. */
  from: string;
  /** When the press was made, in milliseconds. */
  at: number;
}

/** The rows as the page shows them: a module pressed and not yet answered
 * wears the press's transient. */
function withPresses(
  rows: Record<string, DeviceModuleView>,
  deviceId: string | null,
  presses: Record<string, Press>,
): Record<string, DeviceModuleView> {
  if (deviceId === null) {
    return rows;
  }
  const shown: Record<string, DeviceModuleView> = {};
  for (const [name, row] of Object.entries(rows)) {
    const press = presses[configuredKey(deviceId, name)];
    shown[name] =
      press !== undefined && row.state === press.from
        ? { ...row, state: press.state, code: "", params: {} }
        : row;
  }
  return shown;
}

/** The presses still waiting: one whose module the machine reports in
 * another state is answered, and one past the hold has expired. */
function dropAnswered(
  presses: Record<string, Press>,
  deviceId: string,
  rows: Record<string, DeviceModuleView>,
  now: number,
): Record<string, Press> {
  const kept: Record<string, Press> = {};
  for (const [key, press] of Object.entries(presses)) {
    const name = key.slice(deviceId.length + 1);
    const isThisDevice = key.startsWith(`${deviceId}:`);
    const row = isThisDevice ? rows[name] : undefined;
    const isAnswered = row !== undefined && row.state !== press.from;
    if (!isAnswered && now - press.at < PRESSED_HOLD_MS) {
      kept[key] = press;
    }
  }
  return Object.keys(kept).length === Object.keys(presses).length
    ? presses
    : kept;
}

function dropExpired(
  presses: Record<string, Press>,
  now: number,
): Record<string, Press> {
  const kept: Record<string, Press> = {};
  for (const [key, press] of Object.entries(presses)) {
    if (now - press.at < PRESSED_HOLD_MS) {
      kept[key] = press;
    }
  }
  return kept;
}

/** The `<device>:<module>` pair whose configuration section is open. */
function configuredKey(deviceId: string, module: string): string {
  return `${deviceId}:${module}`;
}

/** A failed step, worded from the code the agent reported. */
function describeFailure(row: DeviceModuleView): string {
  if (row.code === "") {
    return t("ui.modules.failed");
  }
  return wordedCode(row) ?? t("ui.modules.failed_code", { code: row.code });
}

/** The code the agent reported, in words; null for one the catalog lacks. */
function wordedCode(row: DeviceModuleView): string | null {
  const key = `code.${row.code}`;
  if (row.code === "" || !hasWord(key)) {
    return null;
  }
  return t(
    key,
    withModuleTitle(codeParams(row.params), { [row.name]: row.title }),
  );
}
