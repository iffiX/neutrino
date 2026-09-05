import { useCallback, useEffect, useState } from "react";

import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import { apiGet, apiPut, describeError } from "../api_client";
import { useConfirm } from "../use_confirm";
import type { DeviceModuleView, DeviceModulesResponse } from "../api_types";

import "./device_modules.css";

/**
 * The modules a device runs, and their real state.
 *
 * A click changes the row at once. The gateway only records what should be
 * true and the machine reconciles on its own time, so waiting for either
 * before showing anything would leave a button that appears not to have been
 * pressed — an install can finish in the gap between two heartbeats, and then
 * the step is never seen at all. So the asked-for step is drawn immediately
 * and stands until the machine reports having got there.
 *
 * A module with no build for a platform is shown greyed rather than hidden:
 * knowing a machine cannot run something is worth more than wondering where
 * it went. A builtin module — a capability the platform already carries — is
 * worded enable/disable rather than install/uninstall, and disabling asks
 * first, because it is the door SSH management walks through.
 */

const WORDING = {
  sectionLabel: "Modules",
  noAgent: "Install the agent to have these installed and kept in place.",
  agentQuiet:
    "The agent is not checking in, so what is on this device is unknown. " +
    "What it was last told to run is shown; nothing can be changed until it " +
    "answers.",
  noBuild: "No build for this platform",
  aimedHere: "pointing at this hub",
  notAimedHere: "not pointing here",
  activate: "Activate",
  deactivate: "Deactivate",
  install: "Install",
  uninstall: "Uninstall",
  enable: "Enable",
  disable: "Disable",
  disableTitle: "Disable {title}",
  disableBody:
    "The machine stops serving it; the agent channel keeps managing the " +
    "machine either way.",
};

// The agent's {code, params} beside a state, worded. A code without an entry
// shows as itself, because a failure hidden entirely is worse than a bare code.
const MODULE_ERROR_WORDING: Record<string, string> = {
  unsupported_platform: "This platform cannot run it.",
  no_platform_build: "There is no build of it for this machine.",
  no_download_named: "The catalog names no download for this machine.",
  install_failed: "The install failed. See Install output below.",
  install_unconfirmed:
    "The install finished, but the software cannot be found on the machine.",
  remove_unconfirmed: "The removal finished, but the software is still there.",
  switch_unconfirmed: "The switch ran, but the machine did not change.",
  vendor_served_a_page:
    "The vendor served a challenge page instead of the package. Install it by hand on the machine; this row turns green by itself once it is there.",
  module_fetch_failed: "The hub could not fetch the package from the vendor.",
  module_fetch_unavailable:
    "This hub cannot fetch downloads a vendor gates on a browser.",
  module_fetch_too_large:
    "The vendor's download is larger than the hub will fetch.",
  module_release_unreadable: "The hub could not read that project's releases.",
  module_cache_unwritable: "The hub could not save the download.",
  module_artifact_missing: "The hub no longer holds that download; ask again.",
  module_artifact_unknown: "The hub does not know that download; ask again.",
  module_digest_mismatch: "What arrived did not match the hub's checksum.",
  unknown_action: "The machine did not understand what it was asked to do.",
  unknown_kind: "The machine does not know this kind of module.",
  order_failed: "The install did not finish. See Install output below.",
  verify_failed:
    "The machine could not tell whether the software is there afterwards.",
  agent_never_reported: "The machine never said how it went.",
  hub_unreachable: "The machine could not reach the hub for the download.",
};

const STATE_WORDING: Record<string, string> = {
  installed: "installed",
  absent: "not installed",
  installing: "installing…",
  removing: "uninstalling…",
  uninstalling: "uninstalling…",
  activating: "activating…",
  deactivating: "deactivating…",
  unsupported: "not available here",
  failed: "failed",
};

// A builtin module is enabled and disabled, and its states say so — the
// agent reports those words as states for capability modules.
const BUILTIN_STATE_WORDING: Record<string, string> = {
  installed: "enabled",
  absent: "disabled",
  enabled: "enabled",
  disabled: "disabled",
  enabling: "enabling…",
  disabling: "disabling…",
  installing: "enabling…",
  removing: "disabling…",
  uninstalling: "disabling…",
};
const STATE_WORDING_FALLBACK = "waiting for the agent";

const REFRESH_INTERVAL_MS = 2000;

// A step in flight is worth watching closely; the read is a local one.
const BUSY_REFRESH_INTERVAL_MS = 1000;

// How long a step may be shown before the machine's own word takes over
// regardless. Only reached when an agent goes quiet mid-step, where a row
// frozen on "installing…" would be a lie.
const STEP_PATIENCE_MS = 120_000;

/** The four things that can be asked of a module. */
type Step = "installing" | "uninstalling" | "activating" | "deactivating";

// Every word that means a step is under way. The agent says "removing"
// where a click says "uninstalling"; both belong here, or a row mid-step
// reads as finished and offers the opposite button.
const BUSY_STATES: string[] = [
  "installing",
  "uninstalling",
  "removing",
  "activating",
  "deactivating",
  "enabling",
  "disabling",
];

/** One change to what is wanted; the wish left out stays as it is. */
interface ModuleWish {
  is_enabled?: boolean;
  is_activated?: boolean;
}

/** A step someone asked for, and when, so it cannot be shown forever. */
interface AskedStep {
  step: Step;
  askedAt: number;
}

interface DeviceModulesProps {
  macAddress: string;
  /** Whether any operation — an SSH task or a module order — is open on
   * this device. Every row's buttons grey while one is. */
  isOperationOpen: boolean;
}

export function DeviceModules({
  macAddress,
  isOperationOpen,
}: DeviceModulesProps) {
  const confirm = useConfirm();
  const [reported, setReported] = useState<DeviceModuleView[]>([]);
  // Whether the agent is installed, and whether it is answering. Both come
  // from the same response the modules do, because they are what makes the
  // modules readable: every state below is the agent's report, so with no
  // agent answering they are all unknown rather than all absent.
  const [agent, setAgent] = useState({ isInstalled: false, isOnline: false });
  const [asked, setAsked] = useState<Record<string, AskedStep>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await apiGet<DeviceModulesResponse>(
        `/devices/${macAddress}/modules`,
      );
      setReported(response.modules);
      setAgent({
        isInstalled: response.is_agent_managed,
        isOnline: response.is_agent_online,
      });
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  }, [macAddress]);

  // What the rows actually show: the machine's report, with any step just
  // asked for standing in front of it. Because the step is written into the
  // same field the machine reports, everything below — the dot, the wording,
  // which buttons are offered — follows from it without being told twice.
  const modules = reported.map((reportedModule) => {
    const pending = asked[reportedModule.name];
    return pending === undefined
      ? reportedModule
      : { ...reportedModule, state: pending.step };
  });
  const isAnyStepRunning = modules.some((deviceModule) =>
    BUSY_STATES.includes(deviceModule.state),
  );

  useEffect(() => {
    void load();
    const handle = window.setInterval(
      () => {
        if (!document.hidden) {
          void load();
        }
      },
      isAnyStepRunning ? BUSY_REFRESH_INTERVAL_MS : REFRESH_INTERVAL_MS,
    );
    return () => window.clearInterval(handle);
  }, [load, isAnyStepRunning]);

  // A step stops being shown once the machine reports having got there, or
  // has had long enough that its silence is the more honest answer.
  useEffect(() => {
    setAsked((current) => {
      const next = { ...current };
      let isChanged = false;
      for (const reportedModule of reported) {
        const pending = next[reportedModule.name];
        if (pending === undefined) {
          continue;
        }
        if (
          hasArrived(reportedModule, pending.step) ||
          Date.now() - pending.askedAt > STEP_PATIENCE_MS
        ) {
          delete next[reportedModule.name];
          isChanged = true;
        }
      }
      return isChanged ? next : current;
    });
  }, [reported]);

  const ask = async (deviceModule: DeviceModuleView, wish: ModuleWish) => {
    setAsked((current) => ({
      ...current,
      [deviceModule.name]: { step: stepFor(wish), askedAt: Date.now() },
    }));
    setError(null);
    try {
      const response = await apiPut<DeviceModulesResponse>(
        `/devices/${macAddress}/modules/${deviceModule.name}`,
        wish,
      );
      setReported(response.modules);
      setAgent({
        isInstalled: response.is_agent_managed,
        isOnline: response.is_agent_online,
      });
    } catch (cause: unknown) {
      setError(describeError(cause));
      setAsked((current) => {
        const next = { ...current };
        delete next[deviceModule.name];
        return next;
      });
    }
  };

  const askOff = (deviceModule: DeviceModuleView) => {
    if (!deviceModule.is_builtin) {
      void ask(deviceModule, { is_enabled: false });
      return;
    }
    confirm.ask({
      title: fill(WORDING.disableTitle, { title: deviceModule.title }),
      body: WORDING.disableBody,
      confirmLabel: WORDING.disable,
      onConfirm: () => void ask(deviceModule, { is_enabled: false }),
    });
  };

  return (
    <div className="device_drawer_section">
      <span className="section_label">{WORDING.sectionLabel}</span>
      {!agent.isInstalled && (
        <span className="field_hint">{WORDING.noAgent}</span>
      )}
      {agent.isInstalled && !agent.isOnline && (
        <span className="field_hint">{WORDING.agentQuiet}</span>
      )}
      {error !== null && <span className="field_error">{error}</span>}
      <div className="device_modules">
        {modules.map((deviceModule) => {
          const isBusy = BUSY_STATES.includes(deviceModule.state);
          const isActionable =
            deviceModule.is_supported &&
            agent.isOnline &&
            !isBusy &&
            !isOperationOpen;
          const here = standing(deviceModule);
          return (
            <div key={deviceModule.name} className="device_module">
              <StatusDot tone={toneFor(deviceModule)} />
              <div className="device_module_body">
                <span className="device_module_title">
                  {deviceModule.title}
                </span>
                <span
                  className="device_module_note"
                  title={deviceModule.description}
                >
                  {deviceModule.is_supported
                    ? describeModule(deviceModule)
                    : WORDING.noBuild}
                </span>
              </div>
              {deviceModule.has_activation && here.isOnMachine && (
                <button
                  type="button"
                  className={`button button--small ${
                    here.isAimedHere ? "button--danger" : "button--primary"
                  }`}
                  disabled={!isActionable}
                  onClick={() =>
                    void ask(deviceModule, {
                      is_activated: !here.isAimedHere,
                    })
                  }
                >
                  <Icon name={here.isAimedHere ? "close" : "bolt"} size={13} />
                  {here.isAimedHere ? WORDING.deactivate : WORDING.activate}
                </button>
              )}
              {!deviceModule.is_native && (
                <button
                  type="button"
                  className={`button button--small ${
                    here.isOnMachine ? "button--danger" : "button--ok"
                  }`}
                  disabled={!isActionable}
                  onClick={() =>
                    here.isOnMachine
                      ? askOff(deviceModule)
                      : void ask(deviceModule, { is_enabled: true })
                  }
                >
                  <Icon
                    name={
                      deviceModule.is_builtin
                        ? "power"
                        : here.isOnMachine
                          ? "trash"
                          : "download"
                    }
                    size={13}
                  />
                  {onOffLabel(deviceModule, here.isOnMachine)}
                </button>
              )}
            </div>
          );
        })}
      </div>
      {confirm.modal}
    </div>
  );
}

/**
 * What a row stands at, mid-step included.
 *
 * A step in flight leaves the row between two truths, and every button has to
 * agree about which one to draw. Deciding that in one place is what keeps an
 * uninstall from offering "Install" the moment it starts, or an activation
 * from claiming the module is not there.
 *
 * The rule is that a step shows the world it is leaving, not the one it is
 * heading for: uninstalling is still installed until it is gone, activating
 * is still not aimed here until it arrives.
 */
function standing(deviceModule: DeviceModuleView): {
  isOnMachine: boolean;
  isAimedHere: boolean;
} {
  switch (deviceModule.state) {
    case "installing":
      return { isOnMachine: false, isAimedHere: false };
    case "uninstalling":
    case "removing":
      return { isOnMachine: true, isAimedHere: deviceModule.is_active };
    case "activating":
      return { isOnMachine: true, isAimedHere: false };
    case "deactivating":
      return { isOnMachine: true, isAimedHere: true };
    default:
      return {
        isOnMachine:
          deviceModule.state === "installed" ||
          deviceModule.state === "enabled",
        isAimedHere: deviceModule.is_active,
      };
  }
}

/** Whether the machine reports having it, ignoring any step in flight. */
function isPresent(deviceModule: DeviceModuleView): boolean {
  return deviceModule.state === "installed" || deviceModule.state === "enabled";
}

/** Which step a wish amounts to. */
function stepFor(wish: ModuleWish): Step {
  if (wish.is_activated !== undefined) {
    return wish.is_activated ? "activating" : "deactivating";
  }
  return wish.is_enabled ? "installing" : "uninstalling";
}

/** Whether the machine's report has caught up with what was asked. */
function hasArrived(deviceModule: DeviceModuleView, step: Step): boolean {
  if (
    deviceModule.state === "failed" ||
    BUSY_STATES.includes(deviceModule.state)
  ) {
    return true;
  }
  if (step === "installing") {
    return (
      deviceModule.state === "installed" || deviceModule.state === "enabled"
    );
  }
  if (step === "uninstalling") {
    return deviceModule.state === "absent" || deviceModule.state === "disabled";
  }
  if (step === "activating") {
    return deviceModule.is_active;
  }
  return !deviceModule.is_active;
}

function toneFor(
  deviceModule: DeviceModuleView,
): "ok" | "warn" | "error" | "idle" {
  if (!deviceModule.is_supported) {
    return "idle";
  }
  if (BUSY_STATES.includes(deviceModule.state)) {
    return "warn";
  }
  if (deviceModule.state === "installed" || deviceModule.state === "enabled") {
    return "ok";
  }
  if (deviceModule.state === "failed") {
    return "error";
  }
  return "idle";
}

/** The on/off button's verb, per the module's own semantics. */
function onOffLabel(
  deviceModule: DeviceModuleView,
  isOnMachine: boolean,
): string {
  if (deviceModule.is_builtin) {
    return isOnMachine ? WORDING.disable : WORDING.enable;
  }
  return isOnMachine ? WORDING.uninstall : WORDING.install;
}

/** What a row says under its title: where it is, and where it points. */
function describeModule(deviceModule: DeviceModuleView): string {
  const stateWording =
    deviceModule.is_builtin || deviceModule.is_native
      ? (BUILTIN_STATE_WORDING[deviceModule.state] ??
        STATE_WORDING[deviceModule.state])
      : STATE_WORDING[deviceModule.state];
  const parts = [stateWording ?? STATE_WORDING_FALLBACK];
  if (
    deviceModule.has_activation &&
    isPresent(deviceModule) &&
    !BUSY_STATES.includes(deviceModule.state)
  ) {
    parts.push(
      deviceModule.is_active ? WORDING.aimedHere : WORDING.notAimedHere,
    );
  }
  if (deviceModule.code && !BUSY_STATES.includes(deviceModule.state)) {
    parts.push(MODULE_ERROR_WORDING[deviceModule.code] ?? deviceModule.code);
  }
  return parts.join(" · ");
}

/** Put values into a wording constant, by name. */
function fill(
  wording: string,
  values: Record<string, string | number>,
): string {
  let filled = wording;
  for (const [name, value] of Object.entries(values)) {
    filled = filled.replace(`{${name}}`, String(value));
  }
  return filled;
}
