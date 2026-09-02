import { useCallback, useEffect, useState } from "react";

import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import { apiGet, apiPut, describeError } from "../api_client";
import type { DeviceFeatureView, DeviceFeaturesResponse } from "../api_types";

import "./device_features.css";

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
 * knowing a machine cannot run cc-switch is worth more than wondering where
 * it went.
 *
 * Some modules have two steps. cc-switch can be installed and left pointing
 * wherever it already pointed; activating is what aims it at this hub, and
 * deactivating gives the machine back the configuration it had beforehand
 * without taking cc-switch off it.
 */

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
];

/** One change to what is wanted; the wish left out stays as it is. */
interface FeatureWish {
  is_enabled?: boolean;
  is_activated?: boolean;
}

/** A step someone asked for, and when, so it cannot be shown forever. */
interface AskedStep {
  step: Step;
  askedAt: number;
}

interface DeviceFeaturesProps {
  macAddress: string;
}

export function DeviceFeatures({ macAddress }: DeviceFeaturesProps) {
  const [reported, setReported] = useState<DeviceFeatureView[]>([]);
  // Whether the agent is installed, and whether it is answering. Both come
  // from the same response the features do, because they are what makes the
  // features readable: every state below is the agent's report, so with no
  // agent answering they are all unknown rather than all absent.
  const [agent, setAgent] = useState({ isInstalled: false, isOnline: false });
  const [asked, setAsked] = useState<Record<string, AskedStep>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await apiGet<DeviceFeaturesResponse>(
        `/devices/${macAddress}/features`,
      );
      setReported(response.features);
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
  const features = reported.map((feature) => {
    const pending = asked[feature.name];
    return pending === undefined
      ? feature
      : { ...feature, state: pending.step };
  });
  const isAnyStepRunning = features.some((feature) =>
    BUSY_STATES.includes(feature.state),
  );

  useEffect(() => {
    void load();
    const handle = window.setInterval(
      () => void load(),
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
      for (const feature of reported) {
        const pending = next[feature.name];
        if (pending === undefined) {
          continue;
        }
        if (
          hasArrived(feature, pending.step) ||
          Date.now() - pending.askedAt > STEP_PATIENCE_MS
        ) {
          delete next[feature.name];
          isChanged = true;
        }
      }
      return isChanged ? next : current;
    });
  }, [reported]);

  const ask = async (feature: DeviceFeatureView, wish: FeatureWish) => {
    setAsked((current) => ({
      ...current,
      [feature.name]: { step: stepFor(wish), askedAt: Date.now() },
    }));
    setError(null);
    try {
      const response = await apiPut<DeviceFeaturesResponse>(
        `/devices/${macAddress}/features/${feature.name}`,
        wish,
      );
      setReported(response.features);
      setAgent({
        isInstalled: response.is_agent_managed,
        isOnline: response.is_agent_online,
      });
    } catch (cause: unknown) {
      setError(describeError(cause));
      setAsked((current) => {
        const next = { ...current };
        delete next[feature.name];
        return next;
      });
    }
  };

  return (
    <div className="device_drawer_section">
      <span className="section_label">Modules</span>
      {!agent.isInstalled && (
        <span className="field_hint">
          Install the agent to have these installed and kept in place.
        </span>
      )}
      {agent.isInstalled && !agent.isOnline && (
        <span className="field_hint">
          The agent is not checking in, so what is on this device is unknown.
          What it was last told to run is shown; nothing can be changed until it
          answers.
        </span>
      )}
      {error !== null && <span className="field_error">{error}</span>}
      <div className="device_features">
        {features.map((feature) => {
          const isBusy = BUSY_STATES.includes(feature.state);
          const isActionable =
            feature.is_supported && agent.isOnline && !isBusy;
          const here = standing(feature);
          return (
            <div key={feature.name} className="device_feature">
              <StatusDot tone={toneFor(feature)} />
              <div className="device_feature_body">
                <span className="device_feature_title">{feature.title}</span>
                <span
                  className="device_feature_note"
                  title={feature.description}
                >
                  {feature.is_supported
                    ? describeFeature(feature)
                    : "No build for this platform"}
                </span>
              </div>
              {feature.has_activation && here.isOnMachine && (
                <button
                  type="button"
                  className={`button button--small ${
                    here.isAimedHere ? "button--danger" : "button--primary"
                  }`}
                  disabled={!isActionable}
                  onClick={() =>
                    void ask(feature, { is_activated: !here.isAimedHere })
                  }
                >
                  <Icon name={here.isAimedHere ? "close" : "bolt"} size={13} />
                  {here.isAimedHere ? "Deactivate" : "Activate"}
                </button>
              )}
              {(feature.is_removable || !here.isOnMachine) && (
                <button
                  type="button"
                  className={`button button--small ${
                    here.isOnMachine ? "button--danger" : "button--ok"
                  }`}
                  disabled={!isActionable}
                  onClick={() =>
                    void ask(feature, { is_enabled: !here.isOnMachine })
                  }
                >
                  <Icon
                    name={here.isOnMachine ? "trash" : "download"}
                    size={13}
                  />
                  {here.isOnMachine ? "Uninstall" : "Install"}
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
 * from claiming the module is not there.
 *
 * The rule is that a step shows the world it is leaving, not the one it is
 * heading for: uninstalling is still installed until it is gone, activating
 * is still not aimed here until it arrives.
 */
function standing(feature: DeviceFeatureView): {
  isOnMachine: boolean;
  isAimedHere: boolean;
} {
  switch (feature.state) {
    case "installing":
      return { isOnMachine: false, isAimedHere: false };
    case "uninstalling":
    case "removing":
      return { isOnMachine: true, isAimedHere: feature.is_active };
    case "activating":
      return { isOnMachine: true, isAimedHere: false };
    case "deactivating":
      return { isOnMachine: true, isAimedHere: true };
    default:
      return {
        isOnMachine: feature.state === "installed",
        isAimedHere: feature.is_active,
      };
  }
}

/** Whether the machine reports having it, ignoring any step in flight. */
function isPresent(feature: DeviceFeatureView): boolean {
  return feature.state === "installed";
}

/** Which step a wish amounts to. */
function stepFor(wish: FeatureWish): Step {
  if (wish.is_activated !== undefined) {
    return wish.is_activated ? "activating" : "deactivating";
  }
  return wish.is_enabled ? "installing" : "uninstalling";
}

/** Whether the machine's report has caught up with what was asked. */
function hasArrived(feature: DeviceFeatureView, step: Step): boolean {
  if (feature.state === "failed" || BUSY_STATES.includes(feature.state)) {
    return true;
  }
  if (step === "installing") {
    return feature.state === "installed";
  }
  if (step === "uninstalling") {
    return feature.state === "absent";
  }
  if (step === "activating") {
    return feature.is_active;
  }
  return !feature.is_active;
}

function toneFor(feature: DeviceFeatureView): "ok" | "warn" | "error" | "idle" {
  if (!feature.is_supported) {
    return "idle";
  }
  if (BUSY_STATES.includes(feature.state)) {
    return "warn";
  }
  if (feature.state === "installed") {
    return "ok";
  }
  if (feature.state === "failed") {
    return "error";
  }
  return "idle";
}

/** What a row says under its title: where it is, and where it points. */
function describeFeature(feature: DeviceFeatureView): string {
  const parts = [describeState(feature.state)];
  if (
    feature.has_activation &&
    isPresent(feature) &&
    !BUSY_STATES.includes(feature.state)
  ) {
    parts.push(
      feature.is_active ? "pointing at this hub" : "not pointing here",
    );
  }
  if (feature.message && !BUSY_STATES.includes(feature.state)) {
    parts.push(feature.message);
  }
  return parts.join(" · ");
}

function describeState(state: string): string {
  if (state === "installed") {
    return "installed";
  }
  if (state === "absent") {
    return "not installed";
  }
  if (state === "installing") {
    return "installing…";
  }
  if (state === "removing" || state === "uninstalling") {
    return "uninstalling…";
  }
  if (state === "activating") {
    return "activating…";
  }
  if (state === "deactivating") {
    return "deactivating…";
  }
  if (state === "unsupported") {
    return "not available here";
  }
  if (state === "failed") {
    return "failed";
  }
  return "waiting for the agent";
}
