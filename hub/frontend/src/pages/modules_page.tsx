import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";

import { apiPath, apiPost, describeError } from "../api_client";
import { CloudcliPanels } from "../components/cloudcli_panels";
import { ContainersPanels } from "../components/containers_panels";
import { DevicePick } from "../components/device_pick";
import { ErrorPanel } from "../components/error_panel";
import { GiteaPanels } from "../components/gitea_panels";
import { Icon } from "../components/icon";
import { ModuleLog } from "../components/module_log";
import { ModulePicker } from "../components/module_picker";
import { SambaPanels } from "../components/samba_panels";
import { Spinner } from "../components/spinner";
import { TabStrip } from "../components/tab_strip";
import { VscodePanels } from "../components/vscode_panels";
import { ZfsPanels } from "../components/zfs_panels";
import { hasWord, t, useLanguage } from "../i18n";
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
import type { StripTab } from "../components/tab_strip";
import type {
  DeviceModuleListView,
  DeviceModuleRequest,
  DeviceModuleView,
  DeviceOnlineView,
  DeviceRequest,
  DevicesOnlineResponse,
} from "../api_types";

import "./modules_page.css";

/**
 * Every module a machine hosts, on one page.
 *
 * The page opens on a machine the way Terminals and Files do. Under the
 * chips, one small tab per module the machine's page shows, each wearing the
 * state its agent last reported, and a `+` that picks which modules the page
 * shows for this machine. A module the machine's system cannot run is greyed
 * out in the picker and never shown as a tab. Under the current tab sits the module's output: the
 * lines the agent sends up while it installs or uninstalls, and the tail of
 * the module's own journal on the machine the rest of the time, polled while
 * the page is open. Then the four presses that write what the hub wants of
 * the module, and Configure, which opens the module's own panels and closes
 * them on the next press. The first Configure on a
 * module the hub holds no configuration for imports what the machine already
 * has, so the first push changes nothing on it. The machine, the tab and the
 * sections open are kept between visits, until a reload.
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
    />
  ),
  vscode: (target) => (
    <VscodePanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
      want={target.want}
      isWindows={target.platformOs === WINDOWS_OS}
    />
  ),
  cloudcli: (target) => (
    <CloudcliPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
      want={target.want}
      isWindows={target.platformOs === WINDOWS_OS}
      isInstalling={target.isInstalling}
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

const PAGE_MODULES = Object.keys(MODULE_PANELS);

/** The one system whose file share is Samba; the others serve with their own. */
const LINUX_OS = "linux";

/** The system that starts VS Code and CloudCLI as an account only with its login. */
const WINDOWS_OS = "windows";

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
  failed: "state.failed",
  unsupported: "state.unsupported",
};
const STATE_NEVER_REPORTED_KEY = "state.never_reported";

/** The tone of the pill beside the name; a state with no entry is drawn plain. */
const TAG_TONES: Record<string, StripTab["tagTone"]> = {
  running: "accent",
  stopped: "error",
  installing: "warn",
  uninstalling: "warn",
  failed: "error",
};

/** The states in which the software is on the machine. */
const PRESENT_STATES = ["installed", "stopped", "running"];

/** The states whose tab turns a spinner beside its word. */
const BUSY_STATES = ["installing", "uninstalling"];

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

/** How tall the tab row is while the first list is still on its way. */
const SKELETON_HEIGHT_PX = 120;

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

  const rows = rowsByName(modules.data);
  const shownNames = shownModules(selectedDevice, rows);
  const shownKey = shownNames.join(",");

  // Whichever tab is current has to still be one the page shows.
  useEffect(() => {
    const shown = shownKey === "" ? [] : shownKey.split(",");
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
      modules.setData(
        await apiPost<DeviceModuleListView>(`/agent/module/${action}`, request),
      );
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
      modules.setData(
        await apiPost<DeviceModuleListView>("/agent/module/start", request),
      );
      setConfiguredKeys((current) =>
        current.includes(key) ? current : [...current, key],
      );
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setBusyAction(null);
    }
  };

  const askUninstall = () => {
    if (selectedDevice === null || activeRow === undefined) {
      return;
    }
    confirm.ask({
      title: t("ui.modules.uninstall_title", {
        module: activeRow.title,
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
  const isConfiguring =
    deviceId !== null &&
    activeModule !== null &&
    configuredKeys.includes(configuredKey(deviceId, activeModule));
  const isBusy = busyAction !== null;
  const canAct = activeRow !== undefined && isAgentOnline && !isBusy;
  const isPresent =
    activeRow !== undefined && PRESENT_STATES.includes(activeRow.state);

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
          <>
            <div className="modules_tab_row">
              {shownNames.length === 0 ? (
                <span className="faint">{t("ui.modules.no_tabs")}</span>
              ) : (
                <TabStrip
                  label={t("ui.modules.tabs_label")}
                  tabs={shownNames
                    .map((name) => rows[name])
                    .filter((row) => row !== undefined)
                    .map(toTab)}
                  selected={activeModule}
                  onSelect={setActiveModule}
                />
              )}
              <ModulePicker
                deviceId={deviceId}
                modules={pickable(rows)}
                shown={shownNames}
                onChanged={noteShown}
              />
            </div>

            {activeRow !== undefined && (
              <>
                {!isAgentOnline && (
                  <div className="notice notice--warn">
                    <Icon name="alert" size={15} />
                    <div className="notice_body">
                      {t("ui.modules.agent_offline")}
                    </div>
                  </div>
                )}
                {activeRow.state === "failed" && (
                  <div className="notice notice--error">
                    <Icon name="alert" size={15} />
                    <div className="notice_body">
                      {describeFailure(activeRow)}
                    </div>
                  </div>
                )}
                <ModuleLog
                  key={`${deviceId}:${activeRow.name}`}
                  deviceId={deviceId}
                  row={activeRow}
                  isAgentOnline={isAgentOnline}
                />
                <div className="modules_actions">
                  <ActionButton
                    action="install"
                    isEnabled={canAct && activeRow.state === "absent"}
                    disabledReason={
                      isPresent || activeRow.state === "failed"
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
                        activeRow.state === "stopped")
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
                          activeRow.is_active))
                    }
                    isBusy={busyAction === "stop"}
                    onClick={() => void act("stop")}
                  />
                  <ActionButton
                    action="uninstall"
                    isEnabled={
                      canAct && (isPresent || activeRow.state === "failed")
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
                    disabled={!canAct || !isPresent}
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

                {actionError !== null && (
                  <div className="notice notice--error">
                    <Icon name="alert" size={15} />
                    <div className="notice_body">{actionError}</div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </section>

      {deviceId !== null && panels !== undefined && isConfiguring && (
        <fieldset className="modules_config" disabled={!isAgentOnline}>
          {panels({
            deviceId,
            basePath: `/agent/module/${activeModule}`,
            isEditable: isAgentOnline,
            platformOs: selectedDevice?.platform.os ?? "",
            isInstalling: activeRow?.state === "installing",
            want: activeRow?.want ?? "",
          })}
        </fieldset>
      )}

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
    return runnable.filter((name) => device.shown_module.includes(name));
  }
  return runnable.filter((name) => rows[name]?.state !== "unknown");
}

/** Every module the picker can show, named as its manifest names it. */
function pickable(rows: Record<string, DeviceModuleView>): PickableModule[] {
  return PAGE_MODULES.map((name) => ({
    name,
    title: rows[name]?.title ?? name,
    isSupported: rows[name]?.is_supported !== false,
  }));
}

/** One module as the tab strip wants it: its name, its state, and a dot. */
function toTab(row: DeviceModuleView): StripTab {
  const key = STATE_KEYS[row.state];
  return {
    key: row.name,
    name: row.title,
    tag: t(key ?? STATE_NEVER_REPORTED_KEY),
    tagTone: TAG_TONES[row.state],
    dotTone: dotTone(row),
    isBusy: BUSY_STATES.includes(row.state),
  };
}

function dotTone(row: DeviceModuleView): StatusTone {
  if (row.state === "running" || (row.state === "installed" && row.is_active)) {
    return "ok";
  }
  if (row.state === "installing" || row.state === "uninstalling") {
    return "warn";
  }
  if (row.state === "failed" || row.state === "stopped") {
    return "error";
  }
  return "idle";
}

/** The `<device>:<module>` pair whose configuration section is open. */
function configuredKey(deviceId: string, module: string): string {
  return `${deviceId}:${module}`;
}

/** A failed step, worded from the code the agent reported. */
function describeFailure(row: DeviceModuleView): string {
  const key = `code.${row.code}`;
  if (row.code !== "" && hasWord(key)) {
    return t(key, asParams(row.params));
  }
  if (row.code === "") {
    return t("ui.modules.failed");
  }
  return t("ui.modules.failed_code", { code: row.code });
}

/** The values a sentence can take from a report's params. */
function asParams(params: Record<string, unknown>): Record<string, string> {
  const named: Record<string, string> = {};
  for (const [name, value] of Object.entries(params)) {
    if (typeof value === "string" || typeof value === "number") {
      named[name] = String(value);
    }
  }
  return named;
}
