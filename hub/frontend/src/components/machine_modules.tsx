import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";

import { apiPath, apiPost, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { ContainersPanels } from "./containers_panels";
import { ErrorPanel } from "./error_panel";
import { GiteaPanels } from "./gitea_panels";
import { Icon } from "./icon";
import { InstancesPanel } from "./instances_panel";
import { ModuleCatalogModal } from "./module_catalog_modal";
import { ModuleIcon } from "./module_icon";
import { ModuleLog } from "./module_log";
import { ModuleVersionBlock } from "./module_version_block";
import { RemoteDesktopPanels } from "./remote_desktop_panels";
import { SambaStatusPanel } from "./samba_status_panel";
import { Spinner } from "./spinner";
import { StatusDot } from "./status_dot";
import { VscodeTerms } from "./vscode_terms";
import {
  LANGUAGE_DEFAULT,
  getLanguage,
  hasWord,
  t,
  useLanguage,
} from "../i18n";
import { MODULE_DESCRIPTORS } from "../module_descriptors";
import { moduleTitle, withModuleTitle } from "../module_title";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import {
  HUB_EVENT_CONFIG,
  HUB_EVENT_DEVICE_REPORT,
  HUB_EVENT_TASK,
} from "../use_hub_events";
import type { IconName } from "./icon";
import type { StatusTone } from "./status_dot";
import type {
  DeviceModuleListView,
  DeviceModuleRequest,
  DeviceModuleView,
  DeviceRequest,
  EnabledAccountsView,
  ModuleUninstallData,
  TaskStarted,
} from "../api_types";

import "./machine_modules.css";

/**
 * **Module configuration** on the machine page: the machine's modules down
 * the left, the picked one's tab on the right, and **+ Add module** under
 * the list, which opens the catalog.
 *
 * A tab reads top to bottom: its state line, its version line once the
 * module is installed, its notices, `Log · last 200 lines` and the log box,
 * `Configuration` and the module's panel while Configure holds it open, and
 * the presses at the right edge. The modules the agent carries show their
 * state line and their panel alone. The picked tab is kept in the address
 * as `?module=`.
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
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
  /** Each module's title as its manifest gives it, by name. */
  manifestTitles: Record<string, string>;
}

/** The account layer's panels, one per module of the descriptor table. */
const ACCOUNT_LAYER_PANELS: Record<string, (target: PanelTarget) => ReactNode> =
  Object.fromEntries(
    Object.values(MODULE_DESCRIPTORS).map((descriptor) => [
      descriptor.name,
      (target: PanelTarget) => (
        <InstancesPanel
          descriptor={descriptor}
          deviceId={target.deviceId}
          basePath={target.basePath}
          isEditable={target.isEditable}
          want={target.want}
          platformOs={target.platformOs}
        />
      ),
    ]),
  );

/** The modules this page has panels for. */
const MODULE_PANELS: Record<string, (target: PanelTarget) => ReactNode> = {
  ...ACCOUNT_LAYER_PANELS,
  samba: (target) => (
    <>
      {ACCOUNT_LAYER_PANELS.samba?.(target)}
      <SambaStatusPanel deviceId={target.deviceId} basePath={target.basePath} />
    </>
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
  remote_desktop: (target) => (
    <RemoteDesktopPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
    />
  ),
};

/** The tabs' order: the modules every system runs first. A module not
 * named here, a container module, comes after them by name. */
const TAB_ORDER = [
  "samba",
  "terminal",
  "ssh_server",
  "remote_desktop",
  "gitea",
  "vscode",
  "code_server",
  "cloudcli",
  "codeg",
  "siyuan",
  "podman",
  "hermes_webui",
];

/** The module whose tab opens only once its terms are accepted. */
const TERMS_MODULE = "vscode";

/** The module whose tab says the owner installs it, with its version. */
const HERMES_MODULE = "hermes_webui";

/** The modules whose first Configure imports what the machine already has. */
const IMPORTING_MODULES = ["gitea", "podman"];

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

/** The route that restarts a managed machine, as the Agents page's Reboot. */
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

/** The query the picked tab is kept in. */
const MODULE_QUERY = "module";

/** How tall the panel is while the first list is still on its way. */
const SKELETON_HEIGHT_PX = 120;

/** The size of a module's glyph in its row. */
const ROW_ICON_PX = 16;

interface MachineModulesProps {
  deviceId: string;
  /** The machine's name, for the restart's question. */
  deviceName: string;
  /** The system the machine's agent reports. */
  platformOs: string;
}

export function MachineModules({
  deviceId,
  deviceName,
  platformOs,
}: MachineModulesProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [searchParams, setSearchParams] = useSearchParams();
  const [busyAction, setBusyAction] = useState<string | null>(null);
  // Each module to the transient a press shows, the state the module was in
  // at the press, and when the press was made.
  const [presses, setPresses] = useState<Record<string, Press>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  // The modules whose configuration is open.
  const [configured, setConfigured] = useState<string[]>([]);
  const [isCatalogOpen, setIsCatalogOpen] = useState(false);
  const confirm = useConfirm();

  const modules = useApiResource<DeviceModuleListView>(
    apiPath("/agent/module", { device_id: deviceId }),
    {
      invalidateOn: [
        { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
        { type: HUB_EVENT_CONFIG },
        { type: HUB_EVENT_TASK },
      ],
    },
  );

  const reportedRows = rowsByName(modules.data);
  const rows = withPresses(reportedRows, presses);
  const shownNames = shownModules(modules.data);
  const asked = searchParams.get(MODULE_QUERY);
  const activeModule =
    asked !== null && shownNames.includes(asked)
      ? asked
      : (shownNames[0] ?? null);
  const activeRow = activeModule === null ? undefined : rows[activeModule];
  const isAgentOnline = modules.data?.is_agent_online ?? false;

  // VS Code's terms, read while its tab is the current one.
  const terms = useApiResource<EnabledAccountsView>(
    activeModule !== TERMS_MODULE
      ? null
      : apiPath(`/agent/module/${TERMS_MODULE}`, { device_id: deviceId }),
    { invalidateOn: [{ type: HUB_EVENT_CONFIG }] },
  );

  const pickModule = (name: string) => {
    setActionError(null);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set(MODULE_QUERY, name);
        return next;
      },
      { replace: true },
    );
  };

  // A press is answered once the machine reports the module in another
  // state, or after the hold.
  useEffect(() => {
    setPresses((current) =>
      dropAnswered(current, rowsByName(modules.data), Date.now()),
    );
  }, [modules.data]);

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
    const from = reportedRows[module]?.state ?? "";
    // Configure on a running module changes no state the tab could wait on.
    if (action === "configure" && from === "running") {
      return;
    }
    setPresses((current) => ({
      ...current,
      [module]: { state: PRESSED_STATES[action], from, at: Date.now() },
    }));
  };

  const act = async (action: ModuleAction) => {
    if (activeModule === null) {
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
    if (activeModule === null || activeRow === undefined) {
      return;
    }
    if (configured.includes(activeModule)) {
      setConfigured((current) =>
        current.filter((held) => held !== activeModule),
      );
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
      setConfigured((current) =>
        current.includes(activeModule) ? current : [...current, activeModule],
      );
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setBusyAction(null);
    }
  };

  const restart = async () => {
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

  const askRestart = () =>
    confirm.ask({
      title: t("ui.modules.restart_title", { device: deviceName }),
      body: t("ui.modules.restart_body"),
      confirmLabel: t("ui.modules.restart_confirm"),
      onConfirm: () => void restart(),
    });

  const askUninstall = () => {
    if (activeRow === undefined) {
      return;
    }
    confirm.ask({
      title: t("ui.modules.uninstall_title", {
        module: moduleTitle(activeRow.name, activeRow.title),
        device: deviceName,
      }),
      body: t("ui.modules.uninstall_body"),
      detail: uninstallLine(activeRow.uninstall_data),
      isDanger: activeRow.uninstall_data?.is_deleted === true,
      confirmLabel: t("ui.modules.uninstall"),
      onConfirm: () => void act("uninstall"),
    });
  };

  if (modules.error !== null && modules.data === null) {
    return <ErrorPanel message={modules.error} onRetry={modules.reload} />;
  }
  if (modules.data === null) {
    return <div className="skeleton" style={{ height: SKELETON_HEIGHT_PX }} />;
  }

  const panels =
    activeModule === null ? undefined : MODULE_PANELS[activeModule];
  const isCarriedRow = activeRow?.is_carried === true;
  const isConfiguring =
    activeModule !== null &&
    panels !== undefined &&
    (isCarriedRow || configured.includes(activeModule));
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
  const termsView = terms.data;
  const isTermsGated =
    activeModule === TERMS_MODULE && termsView?.is_terms_accepted !== true;

  return (
    <div className="modules_split">
      <div
        className="modules_list"
        role="tablist"
        aria-label={t("ui.modules.tabs_title")}
      >
        {shownNames
          .map((name) => rows[name])
          .filter((row) => row !== undefined)
          .map((row) => (
            <ModuleListRow
              key={row.name}
              row={row}
              isOn={row.name === activeModule}
              onSelect={pickModule}
            />
          ))}
        <button
          type="button"
          className="button modules_list_add"
          onClick={() => setIsCatalogOpen(true)}
        >
          {t("ui.modules.add_module")}
        </button>
      </div>

      {activeRow !== undefined && (
        <div className="modules_detail">
          {activeRow.name === HERMES_MODULE && (
            <p className="field_hint">
              {activeRow.version === ""
                ? t("ui.hermes_webui.owner_notice")
                : t("ui.hermes_webui.owner_notice_version", {
                    version: activeRow.version,
                  })}
            </p>
          )}

          {activeModule === TERMS_MODULE && (
            <>
              {termsView !== null ? (
                <VscodeTerms
                  deviceId={deviceId}
                  view={termsView}
                  onRecorded={terms.setData}
                />
              ) : terms.error !== null ? (
                <ErrorPanel message={terms.error} onRetry={terms.reload} />
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
              <div className="modules_detail_head">
                <h3>{moduleTitle(activeRow.name, activeRow.title)}</h3>
                {BUSY_STATES.includes(activeRow.state) && <Spinner size={11} />}
                <StatusDot
                  tone={dotTone(activeRow)}
                  label={stateWord(activeRow)}
                />
              </div>
              {isPresent && !isCarriedRow && (
                <ModuleVersionBlock
                  key={activeRow.name}
                  deviceId={deviceId}
                  module={activeRow.name}
                  title={moduleTitle(activeRow.name, activeRow.title)}
                  canPress={isAgentOnline && !isInTransit}
                />
              )}
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
                      <span>{wordedCode(activeRow) ?? activeRow.code}</span>
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
              {!isCarriedRow && (
                <ModuleLog
                  key={`${deviceId}:${activeRow.name}`}
                  deviceId={deviceId}
                  row={activeRow}
                  isAgentOnline={isAgentOnline}
                />
              )}
              {panels !== undefined && isConfiguring && (
                <>
                  {!isCarriedRow && (
                    <span className="section_label">
                      {t("ui.modules.config_title")}
                    </span>
                  )}
                  <fieldset
                    className="modules_config"
                    disabled={!isAgentOnline}
                  >
                    {panels({
                      deviceId,
                      basePath: `/agent/module/${activeRow.name}`,
                      isEditable: isAgentOnline,
                      platformOs,
                      want: activeRow.want,
                      manifestTitles: manifestTitlesOf(modules.data),
                    })}
                  </fieldset>
                </>
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
                      isPresent ? t("ui.modules.install_present") : undefined
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
                      (isPresent || FAILED_STATES.includes(activeRow.state))
                    }
                    disabledReason={
                      activeRow.state === "absent"
                        ? t("ui.modules.uninstall_absent")
                        : undefined
                    }
                    isBusy={busyAction === "uninstall"}
                    onClick={askUninstall}
                  />
                  {panels !== undefined && (
                    <button
                      type="button"
                      className="button"
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
                  )}
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

      {isCatalogOpen && (
        <ModuleCatalogModal
          deviceId={deviceId}
          onChanged={modules.reload}
          onClose={() => setIsCatalogOpen(false)}
        />
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

/** The machine's modules, by name. */
/** A module's uninstall line in the panel's language, else in English.
 * Empty for a module the agent carries. */
function uninstallLine(data: ModuleUninstallData | null): string {
  if (data === null) {
    return "";
  }
  return data.text[getLanguage()] ?? data.text[LANGUAGE_DEFAULT] ?? "";
}

function rowsByName(
  list: DeviceModuleListView | null,
): Record<string, DeviceModuleView> {
  const rows: Record<string, DeviceModuleView> = {};
  for (const row of list?.modules ?? []) {
    rows[row.name] = row;
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

/** The tabs the page shows, in the page's order: the rows the hub marks
 * shown that the machine can run. */
function shownModules(list: DeviceModuleListView | null): string[] {
  const names = (list?.modules ?? [])
    .filter((row) => row.is_shown && row.is_supported)
    .map((row) => row.name);
  return names.sort((left, right) => tabRank(left, right));
}

function tabRank(left: string, right: string): number {
  const leftAt = TAB_ORDER.indexOf(left);
  const rightAt = TAB_ORDER.indexOf(right);
  if (leftAt >= 0 && rightAt >= 0) {
    return leftAt - rightAt;
  }
  if (leftAt >= 0 || rightAt >= 0) {
    return leftAt >= 0 ? -1 : 1;
  }
  return left.localeCompare(right);
}

/** Whether the machine has the module and the hub holds no want for it, as
 * after a reset or a new join: Start gives it one. */
function isUnclaimed(row: DeviceModuleView): boolean {
  return row.want === "" && PRESENT_STATES.includes(row.state);
}

/** Whether a failed module's own press tries again: the one of what it was
 * asked for. */
function isRetried(row: DeviceModuleView, want: string): boolean {
  return row.state === "failed" && row.want === want;
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
  presses: Record<string, Press>,
): Record<string, DeviceModuleView> {
  const shown: Record<string, DeviceModuleView> = {};
  for (const [name, row] of Object.entries(rows)) {
    const press = presses[name];
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
  rows: Record<string, DeviceModuleView>,
  now: number,
): Record<string, Press> {
  const kept: Record<string, Press> = {};
  for (const [name, press] of Object.entries(presses)) {
    const row = rows[name];
    const isAnswered = row !== undefined && row.state !== press.from;
    if (!isAnswered && now - press.at < PRESSED_HOLD_MS) {
      kept[name] = press;
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
  for (const [name, press] of Object.entries(presses)) {
    if (now - press.at < PRESSED_HOLD_MS) {
      kept[name] = press;
    }
  }
  return kept;
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
