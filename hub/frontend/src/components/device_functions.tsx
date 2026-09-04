import { useCallback, useEffect, useState } from "react";

import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import { apiGet, apiPut, describeError } from "../api_client";
import type { DeviceFunctionView, DeviceFunctionsResponse } from "../api_types";

import "./device_functions.css";

/**
 * The functions a device runs, and their real state.
 *
 * A click changes the row at once. The gateway only records what should be
 * true and the machine reconciles on its own time, so waiting for either
 * before showing anything would leave a button that appears not to have been
 * pressed — an install can finish in the gap between two heartbeats, and then
 * the step is never seen at all. So the asked-for step is drawn immediately
 * and stands until the machine reports having got there.
 *
 * A function with no build for a platform is shown greyed rather than hidden:
 * knowing a machine cannot run something is worth more than wondering where
 * it went.
 */

const WORDING = {
  sectionLabel: "Functions",
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
};

// The agent's {code, params} beside a state, worded. A code without an entry
// shows as itself, because a failure hidden entirely is worse than a bare code.
const FUNCTION_ERROR_WORDING: Record<string, string> = {
  unsupported_platform: "This platform cannot run it.",
  download_failed: "The download failed.",
  install_failed: "The install failed.",
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
const STATE_WORDING_FALLBACK = "waiting for the agent";

const REFRESH_INTERVAL_MS = 2000;

// A step in flight is worth watching closely; the read is a local one.
const BUSY_REFRESH_INTERVAL_MS = 1000;

// How long a step may be shown before the machine's own word takes over
// regardless. Only reached when an agent goes quiet mid-step, where a row
// frozen on "installing…" would be a lie.
const STEP_PATIENCE_MS = 120_000;

/** The four things that can be asked of a function. */
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
];

/** One change to what is wanted; the wish left out stays as it is. */
interface FunctionWish {
  is_enabled?: boolean;
  is_activated?: boolean;
}

/** A step someone asked for, and when, so it cannot be shown forever. */
interface AskedStep {
  step: Step;
  askedAt: number;
}

interface DeviceFunctionsProps {
  macAddress: string;
}

export function DeviceFunctions({ macAddress }: DeviceFunctionsProps) {
  const [reported, setReported] = useState<DeviceFunctionView[]>([]);
  // Whether the agent is installed, and whether it is answering. Both come
  // from the same response the functions do, because they are what makes the
  // functions readable: every state below is the agent's report, so with no
  // agent answering they are all unknown rather than all absent.
  const [agent, setAgent] = useState({ isInstalled: false, isOnline: false });
  const [asked, setAsked] = useState<Record<string, AskedStep>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await apiGet<DeviceFunctionsResponse>(
        `/devices/${macAddress}/functions`,
      );
      setReported(response.functions);
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
  const functions = reported.map((reportedFunction) => {
    const pending = asked[reportedFunction.name];
    return pending === undefined
      ? reportedFunction
      : { ...reportedFunction, state: pending.step };
  });
  const isAnyStepRunning = functions.some((deviceFunction) =>
    BUSY_STATES.includes(deviceFunction.state),
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
      for (const reportedFunction of reported) {
        const pending = next[reportedFunction.name];
        if (pending === undefined) {
          continue;
        }
        if (
          hasArrived(reportedFunction, pending.step) ||
          Date.now() - pending.askedAt > STEP_PATIENCE_MS
        ) {
          delete next[reportedFunction.name];
          isChanged = true;
        }
      }
      return isChanged ? next : current;
    });
  }, [reported]);

  const ask = async (
    deviceFunction: DeviceFunctionView,
    wish: FunctionWish,
  ) => {
    setAsked((current) => ({
      ...current,
      [deviceFunction.name]: { step: stepFor(wish), askedAt: Date.now() },
    }));
    setError(null);
    try {
      const response = await apiPut<DeviceFunctionsResponse>(
        `/devices/${macAddress}/functions/${deviceFunction.name}`,
        wish,
      );
      setReported(response.functions);
      setAgent({
        isInstalled: response.is_agent_managed,
        isOnline: response.is_agent_online,
      });
    } catch (cause: unknown) {
      setError(describeError(cause));
      setAsked((current) => {
        const next = { ...current };
        delete next[deviceFunction.name];
        return next;
      });
    }
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
      <div className="device_functions">
        {functions.map((deviceFunction) => {
          const isBusy = BUSY_STATES.includes(deviceFunction.state);
          const isActionable =
            deviceFunction.is_supported && agent.isOnline && !isBusy;
          const here = standing(deviceFunction);
          return (
            <div key={deviceFunction.name} className="device_function">
              <StatusDot tone={toneFor(deviceFunction)} />
              <div className="device_function_body">
                <span className="device_function_title">
                  {deviceFunction.title}
                </span>
                <span
                  className="device_function_note"
                  title={deviceFunction.description}
                >
                  {deviceFunction.is_supported
                    ? describeFunction(deviceFunction)
                    : WORDING.noBuild}
                </span>
              </div>
              {deviceFunction.has_activation && here.isOnMachine && (
                <button
                  type="button"
                  className={`button button--small ${
                    here.isAimedHere ? "button--danger" : "button--primary"
                  }`}
                  disabled={!isActionable}
                  onClick={() =>
                    void ask(deviceFunction, {
                      is_activated: !here.isAimedHere,
                    })
                  }
                >
                  <Icon name={here.isAimedHere ? "close" : "bolt"} size={13} />
                  {here.isAimedHere ? WORDING.deactivate : WORDING.activate}
                </button>
              )}
              {(deviceFunction.is_removable || !here.isOnMachine) && (
                <button
                  type="button"
                  className={`button button--small ${
                    here.isOnMachine ? "button--danger" : "button--ok"
                  }`}
                  disabled={!isActionable}
                  onClick={() =>
                    void ask(deviceFunction, { is_enabled: !here.isOnMachine })
                  }
                >
                  <Icon
                    name={here.isOnMachine ? "trash" : "download"}
                    size={13}
                  />
                  {here.isOnMachine ? WORDING.uninstall : WORDING.install}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * What a row stands at, mid-step included.
 *
 * A step in flight leaves the row between two truths, and every button has to
 * agree about which one to draw. Deciding that in one place is what keeps an
 * uninstall from offering "Install" the moment it starts, or an activation
 * from claiming the function is not there.
 *
 * The rule is that a step shows the world it is leaving, not the one it is
 * heading for: uninstalling is still installed until it is gone, activating
 * is still not aimed here until it arrives.
 */
function standing(deviceFunction: DeviceFunctionView): {
  isOnMachine: boolean;
  isAimedHere: boolean;
} {
  switch (deviceFunction.state) {
    case "installing":
      return { isOnMachine: false, isAimedHere: false };
    case "uninstalling":
    case "removing":
      return { isOnMachine: true, isAimedHere: deviceFunction.is_active };
    case "activating":
      return { isOnMachine: true, isAimedHere: false };
    case "deactivating":
      return { isOnMachine: true, isAimedHere: true };
    default:
      return {
        isOnMachine: deviceFunction.state === "installed",
        isAimedHere: deviceFunction.is_active,
      };
  }
}

/** Whether the machine reports having it, ignoring any step in flight. */
function isPresent(deviceFunction: DeviceFunctionView): boolean {
  return deviceFunction.state === "installed";
}

/** Which step a wish amounts to. */
function stepFor(wish: FunctionWish): Step {
  if (wish.is_activated !== undefined) {
    return wish.is_activated ? "activating" : "deactivating";
  }
  return wish.is_enabled ? "installing" : "uninstalling";
}

/** Whether the machine's report has caught up with what was asked. */
function hasArrived(deviceFunction: DeviceFunctionView, step: Step): boolean {
  if (
    deviceFunction.state === "failed" ||
    BUSY_STATES.includes(deviceFunction.state)
  ) {
    return true;
  }
  if (step === "installing") {
    return deviceFunction.state === "installed";
  }
  if (step === "uninstalling") {
    return deviceFunction.state === "absent";
  }
  if (step === "activating") {
    return deviceFunction.is_active;
  }
  return !deviceFunction.is_active;
}

function toneFor(
  deviceFunction: DeviceFunctionView,
): "ok" | "warn" | "error" | "idle" {
  if (!deviceFunction.is_supported) {
    return "idle";
  }
  if (BUSY_STATES.includes(deviceFunction.state)) {
    return "warn";
  }
  if (deviceFunction.state === "installed") {
    return "ok";
  }
  if (deviceFunction.state === "failed") {
    return "error";
  }
  return "idle";
}

/** What a row says under its title: where it is, and where it points. */
function describeFunction(deviceFunction: DeviceFunctionView): string {
  const parts = [STATE_WORDING[deviceFunction.state] ?? STATE_WORDING_FALLBACK];
  if (
    deviceFunction.has_activation &&
    isPresent(deviceFunction) &&
    !BUSY_STATES.includes(deviceFunction.state)
  ) {
    parts.push(
      deviceFunction.is_active ? WORDING.aimedHere : WORDING.notAimedHere,
    );
  }
  if (deviceFunction.code && !BUSY_STATES.includes(deviceFunction.state)) {
    parts.push(
      FUNCTION_ERROR_WORDING[deviceFunction.code] ?? deviceFunction.code,
    );
  }
  return parts.join(" · ");
}
