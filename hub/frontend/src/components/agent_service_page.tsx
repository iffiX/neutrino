import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { DeviceChipStrip } from "./device_chip_strip";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { InstallConsentModal } from "./install_consent_modal";
import { Spinner } from "./spinner";
import { ApiError, apiPut, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import {
  HUB_EVENT_CONFIG,
  HUB_EVENT_DEVICE_REPORT,
  HUB_EVENT_DEVICES,
  HUB_EVENT_MODULE_ORDER,
} from "../use_hub_events";
import type { DeviceChip } from "./device_chip_strip";
import type {
  ModuleDeviceView,
  ModuleDevicesRequest,
  ModuleDevicesView,
  ProvisionConsentView,
} from "../api_types";

import "./agent_service_page.css";

/**
 * The shape every Agent-group service page takes.
 *
 * A module is a thing the hub puts on machines, so each of its pages opens
 * with the same two questions before any of its own: which machines run it,
 * and which one is being configured now. The hub box is a managed machine
 * like the rest and is simply first in the list.
 *
 * The third panel is the module's own, and it is handed the selected
 * machine's address rather than a global one — the same forms, pointed at
 * whichever agent is answering for them.
 */

const WORDING = {
  enabledTitle: "Enabled devices",
  enabledHint:
    "Machines running the agent. Picking one installs {module} on it; " +
    "clearing one removes it.",
  enabledApply: "Apply devices",
  enabledApplying: "Applying…",
  noDevices: "No machines run the agent",
  noDevicesHint: "Install the agent on a machine from the Devices page.",
  activeTitle: "Configuring",
  activeHint: "Which machine the settings below belong to.",
  noActive: "{module} is on no machine yet",
  noActiveHint: "Pick a machine above and apply.",
  offline: "The agent is offline",
  deviceFailed: "The last step on {device} failed.",
  consentTitle: "Applying {name} changes what these machines run",
  consentConfirm: "Apply devices",
};

// What moves this list: a machine coming or going, its report saying the
// module now stands somewhere else, an install changing state, and the
// written set of machines the module is asked for on.
const INVALIDATE_ON = [
  { type: HUB_EVENT_DEVICES },
  { type: HUB_EVENT_DEVICE_REPORT },
  { type: HUB_EVENT_MODULE_ORDER },
  { type: HUB_EVENT_CONFIG },
];

// The state that makes a machine configurable: the module is really there.
const INSTALLED_STATE = "installed";

// The state that earns a machine a notice of its own, saying why.
const FAILED_STATE = "failed";

// What a refused apply says, from the code the API returned.
const APPLY_ERROR_WORDING: Record<string, string> = {
  agent_offline: "{device} is not answering, so nothing was changed on it.",
};

// What a machine's own failure says beside its chip.
const DEVICE_ERROR_WORDING: Record<string, string> = {
  unsupported_platform: "{device} cannot run this module.",
  no_platform_build: "There is no build of this module for {device}.",
  install_failed: "The install on {device} failed.",
  uninstall_failed: "The uninstall on {device} failed.",
  install_unconfirmed:
    "The install on {device} finished, but the software cannot be found.",
  uninstall_unconfirmed:
    "The uninstall on {device} finished, but the software is still there.",
  agent_never_reported: "{device} never said how it went.",
  hub_unreachable: "{device} could not reach the hub for the download.",
};

/** The machine a module's own panels are pointed at. */
export interface ServiceTarget {
  deviceId: string;
  /** Where this machine's module answers: `/<module>/devices/<id>`. */
  basePath: string;
  isOnline: boolean;
  /** Whether anything here can be applied. Offline machines take no orders. */
  isEditable: boolean;
}

interface AgentServicePageProps {
  title: string;
  /** The module's panel-facing name, which is also its API root. */
  moduleName: string;
  children: (target: ServiceTarget) => ReactNode;
}

export function AgentServicePage({
  title,
  moduleName,
  children,
}: AgentServicePageProps) {
  const resource = useApiResource<ModuleDevicesView>(`/${moduleName}`, {
    invalidateOn: INVALIDATE_ON,
  });

  const [checkedIds, setCheckedIds] = useState<string[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [isConsentOpen, setIsConsentOpen] = useState(false);

  const devices = resource.data?.devices ?? [];
  const enabledIds = devices
    .filter((device) => device.is_enabled)
    .map((device) => device.device_id);
  const activeDevices = devices.filter(
    (device) => device.state === INSTALLED_STATE,
  );

  // The draft follows the gateway until somebody edits it: an apply landing
  // elsewhere, or a machine finishing an install, should move these chips.
  const enabledKey = enabledIds.join(",");
  useEffect(() => {
    setCheckedIds(null);
  }, [enabledKey]);

  // Whichever machine is picked has to still be one that runs the module.
  const activeKey = activeDevices.map((device) => device.device_id).join(",");
  useEffect(() => {
    const active = activeKey === "" ? [] : activeKey.split(",");
    setSelectedId((current) =>
      current !== null && active.includes(current)
        ? current
        : (active[0] ?? null),
    );
  }, [activeKey]);

  const checked = checkedIds ?? enabledIds;
  const addedDevices = devices.filter(
    (device) => checked.includes(device.device_id) && !device.is_enabled,
  );
  const removedDevices = devices.filter(
    (device) => !checked.includes(device.device_id) && device.is_enabled,
  );
  const isDirty = addedDevices.length > 0 || removedDevices.length > 0;

  const toggleChecked = (deviceId: string) => {
    setApplyError(null);
    setCheckedIds(
      checked.includes(deviceId)
        ? checked.filter((entry) => entry !== deviceId)
        : [...checked, deviceId],
    );
  };

  const applyDevices = async () => {
    setIsConsentOpen(false);
    setIsBusy(true);
    setApplyError(null);
    const request: ModuleDevicesRequest = { device_ids: checked };
    try {
      const updated = await apiPut<ModuleDevicesView>(
        `/${moduleName}/devices`,
        request,
      );
      setCheckedIds(null);
      resource.setData(updated);
    } catch (cause: unknown) {
      setApplyError(describeApplyError(cause, devices));
    } finally {
      setIsBusy(false);
    }
  };

  if (resource.error !== null && resource.data === null) {
    return (
      <div className="page">
        <h1>{title}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (resource.data === null) {
    return (
      <div className="page">
        <h1>{title}</h1>
        <div className="skeleton" style={{ height: 120 }} />
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  const selected =
    activeDevices.find((device) => device.device_id === selectedId) ?? null;
  const failedDevices = devices.filter(
    (device) => device.state === FAILED_STATE,
  );

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{title}</h1>
        </div>
      </div>

      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{WORDING.enabledTitle}</h2>
          <div className="agent_service_actions">
            <button
              type="button"
              className="button button--primary button--commit"
              disabled={!isDirty || isBusy}
              onClick={() => setIsConsentOpen(true)}
            >
              {isBusy ? <Spinner size={13} /> : <Icon name="check" size={14} />}
              {isBusy ? WORDING.enabledApplying : WORDING.enabledApply}
            </button>
          </div>
        </div>
        <p className="field_hint">
          {fill(WORDING.enabledHint, { module: moduleName })}
        </p>
        {applyError !== null && (
          <div className="notice notice--error">
            <Icon name="alert" size={15} />
            <div className="notice_body">{applyError}</div>
          </div>
        )}
        {devices.length === 0 ? (
          <div className="placeholder">
            <span>{WORDING.noDevices}</span>
            <span className="faint">{WORDING.noDevicesHint}</span>
          </div>
        ) : (
          <DeviceChipStrip
            chips={devices.map(toChip)}
            selected={checked}
            onSelect={toggleChecked}
            isMulti
          />
        )}
        {failedDevices.map((device) => (
          <div className="notice notice--error" key={device.device_id}>
            <Icon name="alert" size={15} />
            <div className="notice_body">{describeDeviceCode(device)}</div>
          </div>
        ))}
      </section>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{WORDING.activeTitle}</h2>
        </div>
        {activeDevices.length === 0 ? (
          <div className="placeholder">
            <span>{fill(WORDING.noActive, { module: moduleName })}</span>
            <span className="faint">{WORDING.noActiveHint}</span>
          </div>
        ) : (
          <>
            <p className="field_hint">{WORDING.activeHint}</p>
            <DeviceChipStrip
              chips={activeDevices.map(toChip)}
              selected={selectedId}
              onSelect={setSelectedId}
              isMulti={false}
            />
          </>
        )}
      </section>

      {selected !== null && (
        <fieldset className="agent_service_body" disabled={!selected.is_online}>
          {!selected.is_online && (
            <div className="notice notice--warn">
              <Icon name="alert" size={15} />
              <div className="notice_body">{WORDING.offline}</div>
            </div>
          )}
          {children({
            deviceId: selected.device_id,
            basePath: `/${moduleName}/devices/${selected.device_id}`,
            isOnline: selected.is_online,
            isEditable: selected.is_online,
          })}
        </fieldset>
      )}

      {isConsentOpen && (
        <InstallConsentModal
          name={moduleName}
          consents={consentsFor(addedDevices, removedDevices)}
          title={WORDING.consentTitle}
          confirmLabel={WORDING.consentConfirm}
          onConfirm={() => void applyDevices()}
          onCancel={() => setIsConsentOpen(false)}
        />
      )}
    </div>
  );
}

/** One device row as the chip strip wants it. */
function toChip(device: ModuleDeviceView): DeviceChip {
  return {
    key: device.device_id,
    label: device.name,
    hostname: device.hostname,
    isOnline: device.is_online,
    isChecked: device.is_enabled,
    state: device.state,
  };
}

/** What the consent dialog lists: what this apply would put where. */
function consentsFor(
  added: ModuleDeviceView[],
  removed: ModuleDeviceView[],
): ProvisionConsentView[] {
  const consents: ProvisionConsentView[] = [];
  if (added.length > 0) {
    consents.push({
      code: "device_install",
      detail: { devices: added.map((device) => device.name) },
    });
  }
  if (removed.length > 0) {
    consents.push({
      code: "device_uninstall",
      detail: { devices: removed.map((device) => device.name) },
    });
  }
  return consents;
}

/** A refused apply, worded from the code and the device it names. */
function describeApplyError(
  cause: unknown,
  devices: ModuleDeviceView[],
): string {
  if (!(cause instanceof ApiError)) {
    return describeError(cause);
  }
  const wording = APPLY_ERROR_WORDING[cause.code];
  if (wording === undefined) {
    return describeError(cause);
  }
  const detail = cause.detail as { params?: Record<string, unknown> } | null;
  const deviceId = detail?.params?.device_id;
  const named = devices.find((device) => device.device_id === deviceId);
  return fill(wording, { device: named?.name ?? String(deviceId ?? "") });
}

/** One machine's own failure, worded from what its agent reported. */
function describeDeviceCode(device: ModuleDeviceView): string {
  const wording = DEVICE_ERROR_WORDING[device.code];
  if (wording !== undefined) {
    return fill(wording, { device: device.name });
  }
  if (device.code === "") {
    return fill(WORDING.deviceFailed, { device: device.name });
  }
  return `${device.name}: ${device.code}`;
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
