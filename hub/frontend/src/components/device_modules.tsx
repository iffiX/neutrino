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
 * A click queues one order and changes the row at once. The machine runs it
 * on its own time, so waiting for its report before showing anything would
 * leave a button that appears not to have been pressed — an install can
 * finish in the gap between two heartbeats, and then the step is never seen
 * at all. So the asked-for step is drawn immediately and stands until the
 * machine reports having got there.
 *
 * A module with no build for a platform is shown greyed rather than hidden:
 * knowing a machine cannot run something is worth more than wondering where
 * it went. A module the platform carries natively is worded built in, with
 * no button. A user-tier module offers no button either: the person installs
 * it themselves, and the row only shows what the machine detects.
 * Uninstalling the SSH server asks first, because losing SSH can lock a
 * person out.
 */

const WORDING = {
  sectionLabel: "Modules",
  noAgent: "Install the agent to have these installed and kept in place.",
  agentQuiet:
    "The agent is not checking in, so what is on this device is unknown. " +
    "What it was last told to run is shown; nothing can be changed until it " +
    "answers.",
  noBuild: "No build for this platform",
  builtIn: "built in",
  userTier: "Install it on the machine yourself; the hub only manages it",
  install: "Install",
  uninstall: "Uninstall",
  uninstallSshTitle: "Uninstall the SSH server on {title}",
  uninstallSshBody:
    "SSH stops answering on the machine; the agent channel keeps managing " +
    "it either way.",
};

// The manifest kind whose uninstall asks first: losing SSH can lock a
// person out of a machine the agent is not on yet.
const OPENSSH_KIND = "openssh";

// The installer tier whose rows never offer install or uninstall: the
// person puts the software there, and the hub only detects and manages it.
const USER_INSTALLER = "user";

// The agent's {code, params} beside a state, worded. A code without an entry
// shows as itself, because a failure hidden entirely is worse than a bare code.
const MODULE_ERROR_WORDING: Record<string, string> = {
  unsupported_platform: "This platform cannot run it.",
  no_platform_build: "There is no build of it for this machine.",
  no_download_named: "The catalog names no download for this machine.",
  install_failed: "The install failed. See Install output below.",
  install_unconfirmed:
    "The install finished, but the software cannot be found on the machine.",
  uninstall_unconfirmed:
    "The uninstall finished, but the software is still there.",
  module_fetch_failed: "The hub could not fetch the package from the vendor.",
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
  uninstalling: "uninstalling…",
  unsupported: "not available here",
  failed: "failed",
};
const STATE_WORDING_FALLBACK = "waiting for the agent";

const REFRESH_INTERVAL_MS = 2000;

// A step in flight is worth watching closely; the read is a local one.
const BUSY_REFRESH_INTERVAL_MS = 1000;

// How long a step may be shown before the machine's own word takes over
// regardless. Only reached when an agent goes quiet mid-step, where a row
// frozen on "installing…" would be a lie.
const STEP_PATIENCE_MS = 120_000;

/** The two things that can be asked of a module. */
type Step = "installing" | "uninstalling";

// Every word that means a step is under way; a row mid-step must not read
// as finished and offer the opposite button.
const BUSY_STATES: string[] = ["installing", "uninstalling"];

/** One click's ask; the hub queues one order for it and keeps nothing. */
interface ModuleAsk {
  is_enabled: boolean;
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

  const ask = async (deviceModule: DeviceModuleView, request: ModuleAsk) => {
    setAsked((current) => ({
      ...current,
      [deviceModule.name]: { step: stepFor(request), askedAt: Date.now() },
    }));
    setError(null);
    try {
      const response = await apiPut<DeviceModulesResponse>(
        `/devices/${macAddress}/modules/${deviceModule.name}`,
        request,
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
    if (deviceModule.kind !== OPENSSH_KIND) {
      void ask(deviceModule, { is_enabled: false });
      return;
    }
    confirm.ask({
      title: fill(WORDING.uninstallSshTitle, { title: deviceModule.title }),
      body: WORDING.uninstallSshBody,
      confirmLabel: WORDING.uninstall,
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
          const isHere = isOnMachine(deviceModule);
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
              {!deviceModule.is_native &&
                deviceModule.installer !== USER_INSTALLER && (
                  <button
                    type="button"
                    className={`button button--small ${
                      isHere ? "button--danger" : "button--ok"
                    }`}
                    disabled={!isActionable}
                    onClick={() =>
                      isHere
                        ? askOff(deviceModule)
                        : void ask(deviceModule, { is_enabled: true })
                    }
                  >
                    <Icon name={isHere ? "trash" : "download"} size={13} />
                    {isHere ? WORDING.uninstall : WORDING.install}
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
 * Whether a row's module is on the machine, mid-step included.
 *
 * A step in flight leaves the row between two truths, and every button has to
 * agree about which one to draw. Deciding that in one place is what keeps an
 * uninstall from offering "Install" the moment it starts.
 *
 * The rule is that a step shows the world it is leaving, not the one it is
 * heading for: uninstalling is still installed until it is gone.
 */
function isOnMachine(deviceModule: DeviceModuleView): boolean {
  switch (deviceModule.state) {
    case "installing":
      return false;
    case "uninstalling":
      return true;
    default:
      return deviceModule.state === "installed";
  }
}

/** Which step one ask amounts to. */
function stepFor(request: ModuleAsk): Step {
  return request.is_enabled ? "installing" : "uninstalling";
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
    return deviceModule.state === "installed";
  }
  return deviceModule.state === "absent";
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
  if (deviceModule.state === "installed") {
    return "ok";
  }
  if (deviceModule.state === "failed") {
    return "error";
  }
  return "idle";
}

/** What a row says under its title: where it stands. */
function describeModule(deviceModule: DeviceModuleView): string {
  const stateWording = deviceModule.is_native
    ? WORDING.builtIn
    : STATE_WORDING[deviceModule.state];
  const parts = [stateWording ?? STATE_WORDING_FALLBACK];
  if (
    deviceModule.installer === USER_INSTALLER &&
    deviceModule.state === "absent"
  ) {
    parts.push(WORDING.userTier);
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
