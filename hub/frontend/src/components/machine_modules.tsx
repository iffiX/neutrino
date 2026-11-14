import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";

import { apiGet, apiPath, apiPost, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { AyakaleafPanels } from "./ayakaleaf_panels";
import { ContainersAccountModal } from "./containers_account_modal";
import { ContainersPanels } from "./containers_panels";
import { ErrorPanel } from "./error_panel";
import { FolderSharesPanel } from "./folder_shares_panel";
import { GiteaPanels } from "./gitea_panels";
import { Icon } from "./icon";
import { InstancesPanel } from "./instances_panel";
import { ModuleCatalogModal } from "./module_catalog_modal";
import { ModuleIcon } from "./module_icon";
import { ModuleLog } from "./module_log";
import { ModuleTaskSteps, REBOOT_REQUIRED_CODE } from "./module_task_steps";
import { ModuleVersionBlock } from "./module_version_block";
import { OllamaPanels } from "./ollama_panels";
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
import { stepWords } from "../module_step_words";
import { moduleTitle, withModuleTitle } from "../module_title";
import { MACHINE_RUN_OS } from "../podman_machine";
import { stripAnsi } from "../strip_ansi";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { FAILED_STATES } from "../use_settled_apply";
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
  ModuleInstanceState,
  ModuleUninstallData,
  PodmanDeviceView,
  TaskStarted,
} from "../api_types";

import "./machine_modules.css";

/**
 * **Module configuration** on the machine page: the machine's modules down
 * the left, the picked one's tab on the right, and **+ Add module** under
 * the list, which opens the catalog.
 *
 * A tab reads top to bottom: its state line, the steps of the module's last
 * task, its version line once the module is installed, its notices,
 * `Log · last 200 lines` and the log box,
 * `Configuration` and the module's panel while Configure holds it open, and
 * the presses at the right edge. The modules the agent carries show their
 * state line and their panel alone. A command line program has no Start or
 * Stop, and its version line shows while its own copy is on the machine.
 * The picked tab is kept in the address as `?module=`, and
 * `&configure=1` opens its panel at the page's start.
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
  /** What the hub asks of the module: `running`, `stopped`, `installed`, or
   * empty. */
  want: string;
  /** Whether the agent's package carries the module, with no Start of its
   * own. */
  isCarried: boolean;
  /** Whether the module is a command line program, with no Start. */
  isProgram: boolean;
  /** Each module's title as its manifest gives it, by name. */
  manifestTitles: Record<string, string>;
}

/** The want of a module a person pressed Start on. An apply on any other
 * takes effect at its next Start. */
const WANT_RUNNING = "running";

/** The want of a module the person stopped. */
const WANT_STOPPED = "stopped";

/** The want of a module the person uninstalled, or whose install they
 * cancelled. */
const WANT_ABSENT = "absent";

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
          isWaitingForStart={
            !target.isCarried &&
            !target.isProgram &&
            target.want !== WANT_RUNNING
          }
          want={target.want}
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
      <FolderSharesPanel
        deviceId={target.deviceId}
        basePath={target.basePath}
        isEditable={target.isEditable}
        isWaitingForStart={target.want !== WANT_RUNNING}
      />
      <SambaStatusPanel deviceId={target.deviceId} basePath={target.basePath} />
    </>
  ),
  gitea: (target) => (
    <GiteaPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
      isWaitingForStart={target.want !== WANT_RUNNING}
    />
  ),
  ollama: (target) => (
    <OllamaPanels
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
  ayakaleaf: (target) => (
    <AyakaleafPanels
      deviceId={target.deviceId}
      basePath={target.basePath}
      isEditable={target.isEditable}
      want={target.want}
    />
  ),
};

/** The source chip of each word the hub derives: who installs, updates and
 * removes the software. A word outside the table shows no chip. */
const SOURCE_KEYS: Record<string, string> = {
  agent: "ui.modules.source_agent",
  system: "ui.modules.source_system",
  upstream: "ui.modules.source_upstream",
  container: "ui.modules.source_container",
};

/** The kind chip of each kind: a service, which Start and Stop run, or a
 * program, which a person runs. A word outside the table shows no chip. */
const KIND_KEYS: Record<string, string> = {
  service: "ui.modules.kind_service",
  program: "ui.modules.kind_program",
};

/** The kind of a command line program, which has no Start or Stop. */
const KIND_PROGRAM = "program";

/** The line over a command line program's state line, saying the owner
 * installs it. */
const PROGRAM_NOTICES: Record<string, string> = {
  claude_code: "ui.claude_code.owner_notice",
  codex: "ui.codex.owner_notice",
  opencode: "ui.opencode.owner_notice",
};

/** The module whose containers run in an account's Podman machine. */
const CONTAINERS_MODULE = "podman";

/** The module whose Stop stops the machine's SMB server. */
const FILE_SHARE_MODULE = "samba";

/** The module whose tab opens only once its terms are accepted. */
const TERMS_MODULE = "vscode";

/** The module whose tab says the owner installs it, with its version. */
const HERMES_MODULE = "hermes_webui";

/** The module whose tab says the owner installs it and its two databases. */
const AYAKALEAF_MODULE = "ayakaleaf";

/** The module whose tab says the owner installs it, or names the person's
 * own app it serves through with no presses but Configure. */
const OLLAMA_MODULE = "ollama";

/** What `details.found` says of a person's own Ollama app on Windows and
 * macOS. */
const OLLAMA_FOUND_APP = "app";

/** The method of a module whose containers run on Containers. */
const CONTAINER_METHOD = "container";

/** The code of a row whose task ended on a module it requires. */
const MODULE_NEEDED_CODE = "module_needed";

/** The wants of a module the machine is not asked to have. */
const UNWANTED = ["", "absent"];

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

/** The wants under which the machine applies the hub's configuration, so a
 * `failed` row under one of them is a refused configuration. */
const CONFIGURING_WANTS = ["running", "stopped"];

/** The states in transit: the tab turns a spinner beside its word and
 * every button of the tab but a first install's Cancel is disabled. */
const BUSY_STATES = ["installing", "uninstalling", "queued"];

/** The states a first install reads while its task runs. */
const FIRST_INSTALL_STATES = ["installing", "queued"];

/** The step only an install plan has. */
const INSTALL_PLAN_STEP = "verify";

/** The steps of a container module's version change, whose plan pulls the new
 * images and starts them. A first install's plan ends before `start`. */
const IMAGE_CHANGE_STEPS = ["pull", "start"];

/** The states a first start reads while its task runs. */
const FIRST_START_STATES = ["installed", ...FIRST_INSTALL_STATES];

/** The states a start's plan with `npm` reads with no instance running. A
 * started module with no instance reads `running`. */
const EVERY_START_STATES = ["running", ...FIRST_START_STATES];

/** The step of a `hub` module's version switch. */
const VERSION_SWITCH_STEP = "switch";

/** The long step of a first start that every start's plan holds. A plan that
 * holds it while an instance runs is no first start. */
const EVERY_START_LONG_STEP = "npm";

/** The steps a first start's plan holds around its other long step. `tex`
 * alone comes back after a version change, and `replica_set` runs once. */
const FRESH_START_LONG_STEPS = ["replica_set", "tex"];

/** The busy mark of a Cancel. A Cancel posts Uninstall's route. */
const CANCEL_BUSY = "cancel";

/** The transient a press shows until the machine reports otherwise. */
const PRESSED_STATES: Record<ModuleAction, string> = {
  install: "installing",
  uninstall: "uninstalling",
  start: "queued",
  stop: "queued",
};

/** The states whose code the tab words as a notice at its top: what holds
 * up an install or a queued task, what is missing of software that is
 * partly there, and what a running module leaves out. */
const NOTICED_STATES = ["installing", "queued", "absent", "running"];

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

/** The query that opens the picked tab's panel at the page's start, `1`. */
const CONFIGURE_QUERY = "configure";

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
  // The modules whose configuration is open: the asked tab's when the
  // address names `configure=1`.
  const [configured, setConfigured] = useState<string[]>(() => {
    const opened = searchParams.get(MODULE_QUERY);
    return opened !== null && searchParams.get(CONFIGURE_QUERY) === "1"
      ? [opened]
      : [];
  });
  const [isCatalogOpen, setIsCatalogOpen] = useState(false);
  const [isAccountAsked, setIsAccountAsked] = useState(false);
  // The modules this page saw cancelling, by name, until the uninstall ends.
  const [cancels, setCancels] = useState<string[]>([]);
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
        next.delete(CONFIGURE_QUERY);
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
    setCancels((current) => keptCancels(current, rowsByName(modules.data)));
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
    return () => {
      window.clearTimeout(timer);
    };
  }, [presses]);

  const notePress = (module: string, action: ModuleAction) => {
    const from = reportedRows[module]?.state ?? "";
    setPresses((current) => ({
      ...current,
      [module]: { state: PRESSED_STATES[action], from, at: Date.now() },
    }));
  };

  const act = async (action: ModuleAction, busy: string = action) => {
    if (activeModule === null) {
      return;
    }
    setBusyAction(busy);
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
      if (busy === CANCEL_BUSY) {
        setCancels((current) => [...current, activeModule]);
      } else {
        notePress(activeModule, action);
      }
      modules.setData(answer);
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setBusyAction(null);
    }
  };

  // Configure opens the section, and imports what the machine has first where
  // the hub holds nothing for it yet. It writes no want. Pressed while its
  // section is open, it closes the section.
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
    try {
      if (
        !activeRow.is_configured &&
        IMPORTING_MODULES.includes(activeModule)
      ) {
        const imported: DeviceRequest = { device_id: deviceId };
        await apiPost(`/agent/module/${activeModule}/import`, imported);
      }
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

  const askRestart = () => {
    confirm.ask({
      title: t("ui.modules.restart_title", { device: deviceName }),
      body: t("ui.modules.restart_body"),
      confirmLabel: t("ui.modules.restart_confirm"),
      onConfirm: () => void restart(),
    });
  };

  // Whether Install on this row needs the account of Containers' machine.
  const isAccountMissing = async (row: DeviceModuleView) => {
    const isOnMachine =
      MACHINE_RUN_OS.includes(platformOs) &&
      (row.name === CONTAINERS_MODULE ||
        row.requires.includes(CONTAINERS_MODULE));
    if (!isOnMachine) {
      return false;
    }
    const view = await apiGet<PodmanDeviceView>(
      apiPath(`/agent/module/${CONTAINERS_MODULE}`, { device_id: deviceId }),
    );
    return (view.machine?.account ?? "") === "";
  };

  // Install on a module whose required modules read absent opens a dialog
  // listing them first. Install asks for Containers' account after that dialog
  // and before anything installs.
  const askInstall = async () => {
    if (activeRow === undefined) {
      return;
    }
    setBusyAction("install");
    setActionError(null);
    let isAsked = false;
    try {
      isAsked = await isAccountMissing(activeRow);
    } catch (cause: unknown) {
      setActionError(describeError(cause));
      return;
    } finally {
      setBusyAction(null);
    }
    const install = () => {
      if (isAsked) {
        setIsAccountAsked(true);
      } else {
        void act("install");
      }
    };
    const absent = activeRow.requires.filter(
      (name) => reportedRows[name]?.state === "absent",
    );
    if (absent.length === 0) {
      install();
      return;
    }
    confirm.ask({
      title: t("ui.modules.install_title", {
        module: moduleTitle(activeRow.name, activeRow.title),
        device: deviceName,
      }),
      body: t("ui.modules.install_requires_body"),
      items: absent.map((name) =>
        moduleTitle(name, reportedRows[name]?.title ?? name),
      ),
      question: t("ui.modules.install_requires_question"),
      confirmLabel: t("ui.confirm.yes"),
      cancelLabel: t("ui.confirm.no"),
      onConfirm: install,
    });
  };

  // Stop on the File share asks first. Stop on any other module acts at once.
  const askStop = () => {
    if (activeRow === undefined) {
      return;
    }
    if (activeRow.name !== FILE_SHARE_MODULE) {
      void act("stop");
      return;
    }
    confirm.ask({
      title: t("ui.samba.stop_title", { device: deviceName }),
      body: t("ui.samba.stop_body"),
      confirmLabel: t("ui.modules.stop"),
      onConfirm: () => void act("stop"),
    });
  };

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

  const askCancel = () => {
    if (activeRow === undefined) {
      return;
    }
    confirm.ask({
      title: t("ui.modules.cancel_title", {
        module: moduleTitle(activeRow.name, activeRow.title),
        device: deviceName,
      }),
      body: t("ui.modules.cancel_body"),
      detail: uninstallLine(activeRow.uninstall_data),
      isDanger: activeRow.uninstall_data?.is_deleted === true,
      confirmLabel: t("ui.modules.cancel_confirm"),
      cancelLabel: t("ui.modules.cancel_keep"),
      onConfirm: () => void act("uninstall", CANCEL_BUSY),
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
  const isProgram = activeRow?.kind === KIND_PROGRAM;
  // A person's own Ollama app, which takes no press but Configure.
  const isFoundApp =
    activeRow?.name === OLLAMA_MODULE &&
    activeRow.details.found === OLLAMA_FOUND_APP;
  const programNotice =
    activeRow === undefined ? undefined : PROGRAM_NOTICES[activeRow.name];
  const isConfiguring =
    activeModule !== null &&
    panels !== undefined &&
    (isCarriedRow || configured.includes(activeModule));
  const isBusy = busyAction !== null;
  const isInTransit = activeRow !== undefined && isRowInTransit(activeRow);
  const canAct =
    activeRow !== undefined && isAgentOnline && !isBusy && !isInTransit;
  const isPresent =
    activeRow !== undefined && PRESENT_STATES.includes(activeRow.state);
  const isConfigRefused =
    activeRow !== undefined &&
    activeRow.state === "failed" &&
    CONFIGURING_WANTS.includes(activeRow.want);
  const termsView = terms.data;
  const memoryNeed = modules.data.memory_need;
  const isMemoryShort =
    memoryNeed !== null &&
    activeRow !== undefined &&
    activeRow.method === CONTAINER_METHOD &&
    !UNWANTED.includes(activeRow.want);
  const isTermsGated =
    activeModule === TERMS_MODULE && termsView?.is_terms_accepted !== true;
  const manifestTitles = manifestTitlesOf(modules.data);
  // The step list follows the machine's report, not a press's transient.
  const reportedRow =
    activeModule === null ? undefined : reportedRows[activeModule];
  const stepsTask = reportedRow?.task ?? null;
  const isRowCancelling =
    reportedRow !== undefined && isCancelKept(reportedRow, cancels);
  const isCancelShown =
    reportedRow !== undefined &&
    (isRowCancelling || isFirstInstall(reportedRow));
  const isStepFailed =
    reportedRow !== undefined && FAILED_STATES.includes(reportedRow.state);
  const owedRestart =
    activeRow === undefined ? undefined : restartOwner(activeRow, rows);
  const restartButton = (
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
  );
  // What the step list already words under a step: the wait of the running
  // step, and the failure of the last step run.
  const isWaitInSteps =
    stepsTask !== null &&
    stepsTask.is_running &&
    activeRow !== undefined &&
    stepsTask.wait.code === activeRow.code;
  const isFailureInSteps =
    stepsTask !== null && !stepsTask.is_running && isStepFailed;

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
          onClick={() => {
            setIsCatalogOpen(true);
          }}
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
          {activeRow.name === AYAKALEAF_MODULE && (
            <p className="field_hint">{t("ui.ayakaleaf.owner_notice")}</p>
          )}
          {activeRow.name === OLLAMA_MODULE && (
            <p className="field_hint">
              {t(isFoundApp ? "ui.ollama.found_app" : "ui.ollama.owner_notice")}
            </p>
          )}
          {programNotice !== undefined && (
            <p className="field_hint">{t(programNotice)}</p>
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
                <ModuleChips row={activeRow} />
                {isRowInTransit(activeRow) && <Spinner size={11} />}
                <StatusDot
                  tone={dotTone(activeRow)}
                  label={stateWord(activeRow)}
                  isPulsing={isProgram ? false : undefined}
                />
              </div>
              {stepsTask !== null && reportedRow !== undefined && (
                <ModuleTaskSteps
                  module={activeRow.name}
                  task={stepsTask}
                  isFailed={isStepFailed}
                  failure={describeFailure(reportedRow, manifestTitles)}
                  manifestTitles={manifestTitles}
                />
              )}
              {(isPresent || FAILED_STATES.includes(activeRow.state)) &&
                !isCarriedRow &&
                (!isProgram || hasModuleCopy(activeRow)) && (
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
              {isMemoryShort && (
                <div className="notice notice--warn">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {t("ui.modules.memory_need", {
                      memory: memoryNeed.memory_gib,
                      need: memoryNeed.need_gib,
                    })}
                  </div>
                </div>
              )}
              {isCodeNoticed(activeRow) &&
                activeRow.code !== "" &&
                (!isWaitInSteps || activeRow.code === REBOOT_REQUIRED_CODE) && (
                  <div className="notice notice--warn modules_install_notice">
                    <Icon name="alert" size={15} />
                    <div className="notice_body">
                      <span>
                        {wordedCode(activeRow, manifestTitles) ??
                          activeRow.code}
                      </span>
                      {activeRow.code === REBOOT_REQUIRED_CODE && restartButton}
                    </div>
                  </div>
                )}
              {isInTransit && owedRestart !== undefined && (
                <div className="notice notice--warn modules_install_notice">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    <span>
                      {wordedCode(owedRestart, manifestTitles) ??
                        owedRestart.code}
                    </span>
                    {restartButton}
                  </div>
                </div>
              )}
              {FAILED_STATES.includes(activeRow.state) && !isFailureInSteps && (
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {activeRow.step !== null && (
                      <span>
                        {t("ui.modules.failed_step", {
                          index: activeRow.step.index,
                          count: activeRow.step.count,
                          step: stepWords(
                            activeRow.step,
                            activeRow.name,
                            0,
                            manifestTitles,
                          ),
                        })}
                      </span>
                    )}
                    <span className="modules_failure_detail">
                      {stripAnsi(describeFailure(activeRow, manifestTitles))}
                    </span>
                  </div>
                </div>
              )}
              {!isCarriedRow && (
                <ModuleLog
                  key={`${deviceId}:${activeRow.name}`}
                  deviceId={deviceId}
                  module={activeRow.name}
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
                      want: wantAtApply(activeRow),
                      isCarried: isCarriedRow,
                      isProgram: isProgram,
                      manifestTitles,
                    })}
                  </fieldset>
                </>
              )}
              {!isCarriedRow && (
                <div className="modules_actions">
                  {isFoundApp ? null : isCancelShown ? (
                    <CancelButton
                      isCancelling={isRowCancelling}
                      isEnabled={isAgentOnline && !isBusy && !isRowCancelling}
                      isBusy={busyAction === CANCEL_BUSY}
                      onClick={askCancel}
                    />
                  ) : (
                    <ActionButton
                      action="install"
                      isEnabled={
                        canAct &&
                        (activeRow.state === "absent" ||
                          activeRow.state === "install_failed" ||
                          isRetried(activeRow, "installed") ||
                          (isProgram &&
                            (isUnclaimed(activeRow) ||
                              isRetried(activeRow, WANT_RUNNING))))
                      }
                      disabledReason={
                        isPresent ? t("ui.modules.install_present") : undefined
                      }
                      isBusy={busyAction === "install"}
                      onClick={() => void askInstall()}
                    />
                  )}
                  {!isProgram && !isFoundApp && (
                    <>
                      <ActionButton
                        action="start"
                        isEnabled={
                          canAct &&
                          (activeRow.state === "installed" ||
                            activeRow.state === "stopped" ||
                            isUnclaimed(activeRow) ||
                            isRetried(activeRow, "running") ||
                            isRequiredModuleNeeded(activeRow))
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
                            isRetried(activeRow, "stopped") ||
                            isKeeperStoppable(activeRow))
                        }
                        isBusy={busyAction === "stop"}
                        onClick={askStop}
                      />
                    </>
                  )}
                  {!isFoundApp && (
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
                  )}
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
          onClose={() => {
            setIsCatalogOpen(false);
          }}
        />
      )}
      {isAccountAsked && (
        <ContainersAccountModal
          deviceId={deviceId}
          module={activeRow?.name ?? ""}
          onChosen={() => {
            setIsAccountAsked(false);
            void act("install");
          }}
          onCancel={() => {
            setIsAccountAsked(false);
          }}
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

interface CancelButtonProps {
  /** Whether the row wants the module absent. */
  isCancelling: boolean;
  isEnabled: boolean;
  isBusy: boolean;
  onClick: () => void;
}

/** A first install's Cancel, in the place of Install. */
function CancelButton({
  isCancelling,
  isEnabled,
  isBusy,
  onClick,
}: CancelButtonProps) {
  return (
    <button
      type="button"
      className="button button--danger"
      disabled={!isEnabled}
      onClick={onClick}
    >
      {isBusy || isCancelling ? (
        <Spinner size={13} />
      ) : (
        <Icon name="close" size={14} />
      )}
      {t(isCancelling ? "ui.modules.cancelling" : "ui.modules.cancel")}
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

/** The tabs the page shows, in the hub's order: the rows the hub marks
 * shown that the machine can run. */
function shownModules(list: DeviceModuleListView | null): string[] {
  return (list?.modules ?? [])
    .filter((row) => row.is_shown && row.is_supported)
    .map((row) => row.name);
}

/** Whether the machine has the module and the hub holds no want for it, as
 * after a reset or a new join: Start gives it one. */
function isUnclaimed(row: DeviceModuleView): boolean {
  return row.want === "" && PRESENT_STATES.includes(row.state);
}

/** The want a module's panel works under: a row with no want that reads
 * `running` takes `running` at its apply. */
function wantAtApply(row: DeviceModuleView): string {
  return row.want === "" && row.state === WANT_RUNNING
    ? WANT_RUNNING
    : row.want;
}

/** Whether a failed module's own press tries again: the one of what it was
 * asked for. */
function isRetried(row: DeviceModuleView, want: string): boolean {
  return row.state === "failed" && row.want === want;
}

/** Whether a failed row's task ended on a module it requires, whose words
 * name Start whatever the row's want. */
function isRequiredModuleNeeded(row: DeviceModuleView): boolean {
  return row.state === "failed" && row.code === MODULE_NEEDED_CODE;
}

/** Whether a failed row's Stop ends what its module retries by itself,
 * whatever it was asked for: Containers' keeper. */
function isKeeperStoppable(row: DeviceModuleView): boolean {
  return row.state === "failed" && row.name === CONTAINERS_MODULE;
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
      onClick={() => {
        onSelect(row.name);
      }}
    >
      <ModuleIcon name={row.name} size={ROW_ICON_PX} />
      <span className="modules_list_row_title">{title}</span>
      {row.task !== null && row.task.is_running && (
        <span className="modules_list_row_step">
          {row.task.index}/{row.task.steps.length}
        </span>
      )}
      {isRowInTransit(row) && <Spinner size={11} />}
      <StatusDot tone={dotTone(row)} />
    </button>
  );
}

/** The chips left of a tab's state: the source of the module's software on
 * this machine and the module's kind, each the word the hub sends, then
 * Upgrade only on a module whose data moves forward only. */
function ModuleChips({ row }: { row: DeviceModuleView }) {
  const sourceKey = SOURCE_KEYS[row.source];
  const kindKey = KIND_KEYS[row.kind];
  return (
    <>
      {sourceKey !== undefined && <span className="badge">{t(sourceKey)}</span>}
      {kindKey !== undefined && <span className="badge">{t(kindKey)}</span>}
      {row.is_data_forward_only && (
        <span className="badge">{t("ui.modules.forward_only")}</span>
      )}
    </>
  );
}

/** Whether a command line program's own copy is on the machine, as its
 * `details` report it. */
function hasModuleCopy(row: DeviceModuleView): boolean {
  return row.details.has_module_copy === true;
}

/** Whether a module is in transit: a state of the busy set, or a task that
 * runs. */
function isRowInTransit(row: DeviceModuleView): boolean {
  return (
    BUSY_STATES.includes(row.state) ||
    (row.task !== null && row.task.is_running)
  );
}

/** Whether the tab words a row's code as a notice: a state that holds one, or
 * a module stopped against its want. */
function isCodeNoticed(row: DeviceModuleView): boolean {
  return (
    NOTICED_STATES.includes(row.state) ||
    (row.state === "stopped" && row.want !== WANT_STOPPED)
  );
}

/** The step names of a row's running task, empty with none running. */
function runningPlan(row: DeviceModuleView): string[] {
  return row.task !== null && row.task.is_running
    ? row.task.steps.map((step) => step.name)
    : [];
}

/** Whether a module's first install runs, or its first start with a long
 * step. The row names no kind of plan, so this reads the task's steps. */
function isFirstInstall(row: DeviceModuleView): boolean {
  const plan = runningPlan(row);
  return (
    (FIRST_INSTALL_STATES.includes(row.state) &&
      plan.includes(INSTALL_PLAN_STEP) &&
      !IMAGE_CHANGE_STEPS.every((step) => plan.includes(step))) ||
    isLongFirstStart(row, plan)
  );
}

/** Whether a running plan is a first start that holds a long step. */
function isLongFirstStart(row: DeviceModuleView, plan: string[]): boolean {
  return (
    !plan.includes(VERSION_SWITCH_STEP) &&
    ((EVERY_START_STATES.includes(row.state) &&
      plan.includes(EVERY_START_LONG_STEP) &&
      !hasRunningInstance(row)) ||
      (FIRST_START_STATES.includes(row.state) &&
        FRESH_START_LONG_STEPS.every((step) => plan.includes(step))))
  );
}

/** Whether an instance of a row's module runs, as the row's `details` list
 * them. */
function hasRunningInstance(row: DeviceModuleView): boolean {
  const instances = (row.details.instances ?? []) as ModuleInstanceState[];
  return instances.some((instance) => instance.is_running);
}

/** Whether a first install still runs on a row whose want is absent. */
function isCancelling(row: DeviceModuleView): boolean {
  return isFirstInstall(row) && row.want === WANT_ABSENT;
}

/** Whether a row reads as cancelling, or is in the uninstall of a cancel this
 * page saw. That uninstall reads as any uninstall on the row. */
function isCancelKept(row: DeviceModuleView, cancels: string[]): boolean {
  return (
    isCancelling(row) ||
    (cancels.includes(row.name) &&
      row.want === WANT_ABSENT &&
      isRowInTransit(row))
  );
}

/** The cancels still on their way, by module name. */
function keptCancels(
  cancels: string[],
  rows: Record<string, DeviceModuleView>,
): string[] {
  return Object.values(rows)
    .filter((row) => isCancelKept(row, cancels))
    .map((row) => row.name);
}

/** The required module whose restart this row's task waits behind. */
function restartOwner(
  row: DeviceModuleView,
  rows: Record<string, DeviceModuleView>,
): DeviceModuleView | undefined {
  return row.requires
    .map((name) => rows[name])
    .find((required) => required?.code === REBOOT_REQUIRED_CODE);
}

/** The word a module's state wears; a token outside the table reads as a
 * machine that has not reported. A command line program reads ready in
 * place of running. */
function stateWord(row: DeviceModuleView): string {
  if (row.state === "running" && row.kind === KIND_PROGRAM) {
    return t("state.ready");
  }
  if (row.state === "running" && row.is_without_accounts) {
    return t("state.running_no_accounts");
  }
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
function describeFailure(
  row: DeviceModuleView,
  manifestTitles: Record<string, string>,
): string {
  if (row.code === "") {
    return t("ui.modules.failed");
  }
  return (
    wordedCode(row, manifestTitles) ??
    t("ui.modules.failed_code", { code: row.code })
  );
}

/** The catalog key of a row's code. A `failed` row has its software, so its
 * `module_needed` names Start, where every other row's names Install. */
function codeKey(row: DeviceModuleView): string {
  if (row.code === MODULE_NEEDED_CODE && row.state === "failed") {
    return "code.module_needed_start";
  }
  return `code.${row.code}`;
}

/** The code the agent reported, in words; null for one the catalog lacks.
 * `manifestTitles` holds each module's manifest title, by name. */
function wordedCode(
  row: DeviceModuleView,
  manifestTitles: Record<string, string>,
): string | null {
  const key = codeKey(row);
  if (row.code === "" || !hasWord(key)) {
    return null;
  }
  return t(key, withModuleTitle(codeParams(row.params), manifestTitles));
}
