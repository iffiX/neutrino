import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { DeviceChipStrip } from "./device_chip_strip";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { InstallConsentModal } from "./install_consent_modal";
import { Spinner } from "./spinner";
import { TabStrip } from "./tab_strip";
import { ApiError, apiPut, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import {
  HUB_EVENT_CONFIG,
  HUB_EVENT_DEVICE_REPORT,
  HUB_EVENT_DEVICES,
  HUB_EVENT_MODULE_ORDER,
} from "../use_hub_events";
import type { DeviceChip } from "./device_chip_strip";
import type { StripTab } from "./tab_strip";
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
 * A module is a thing the hub puts on machines, so each of its pages opens by
 * asking which machines run it. The hub box is a managed machine like the rest
 * and is simply first in the list.
 *
 * The machines it is asked for are tabs below that, the way the Network page
 * tabs its interfaces, and the module's own panels hang under the picked one:
 * the same forms, pointed at whichever agent is answering for them. A machine
 * the module is not standing on yet keeps its tab and says where it stands.
 */

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

// The states that are a step, not a standing answer; their tab wears amber.
const IN_FLIGHT_STATES = ["installing", "uninstalling"];

// The word a machine's tab wears while the module is not standing on it.
const TAB_STATE_KEYS: Record<string, string> = {
  installing: "ui.agent_service.tab_installing",
  uninstalling: "ui.agent_service.tab_uninstalling",
  failed: "ui.agent_service.tab_failed",
  unsupported: "ui.agent_service.tab_unsupported",
};

// What a picked machine says in place of the module's panels, by its state.
const DEVICE_STATE_KEYS: Record<string, string> = {
  installing: "ui.agent_service.device_installing",
  uninstalling: "ui.agent_service.device_uninstalling",
  unsupported: "ui.agent_service.device_unsupported",
};

// What a machine's own failure says beside its chip.
const DEVICE_ERROR_KEYS: Record<string, string> = {
  unsupported_platform: "ui.agent_service.device_unsupported_platform",
  no_platform_build: "code.no_platform_build",
  install_failed: "code.install_failed",
  uninstall_failed: "code.uninstall_failed",
  install_unconfirmed: "code.install_unconfirmed",
  uninstall_unconfirmed: "code.uninstall_unconfirmed",
  agent_never_reported: "code.agent_never_reported",
  hub_unreachable: "code.hub_unreachable",
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
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<ModuleDevicesView>(`/${moduleName}`, {
    invalidateOn: INVALIDATE_ON,
  });

  const [checkedIds, setCheckedIds] = useState<string[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [isConsentOpen, setIsConsentOpen] = useState(false);

  const devices = resource.data?.devices ?? [];
  // Every machine the module is asked for, whatever state it stands in: a
  // machine keeps its tab while it installs.
  const enabledDevices = devices.filter((device) => device.is_enabled);
  const enabledIds = enabledDevices.map((device) => device.device_id);

  // The draft follows the gateway until somebody edits it: an apply landing
  // elsewhere, or a machine finishing an install, should move these chips.
  const enabledKey = enabledIds.join(",");
  useEffect(() => {
    setCheckedIds(null);
  }, [enabledKey]);

  // Whichever machine is picked has to still be one the module is asked for.
  useEffect(() => {
    const enabled = enabledKey === "" ? [] : enabledKey.split(",");
    setSelectedId((current) =>
      current !== null && enabled.includes(current)
        ? current
        : (enabled[0] ?? null),
    );
  }, [enabledKey]);

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
    enabledDevices.find((device) => device.device_id === selectedId) ?? null;
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
          <h2>{t("ui.agent_service.enabled_title")}</h2>
          <div className="agent_service_actions">
            <button
              type="button"
              className="button button--primary button--commit"
              disabled={!isDirty || isBusy}
              onClick={() => setIsConsentOpen(true)}
            >
              {isBusy ? <Spinner size={13} /> : <Icon name="check" size={14} />}
              {isBusy
                ? t("ui.agent_service.applying")
                : t("ui.agent_service.apply")}
            </button>
          </div>
        </div>
        <p className="field_hint">
          {t("ui.agent_service.enabled_hint", { module: moduleName })}
        </p>
        {applyError !== null && (
          <div className="notice notice--error">
            <Icon name="alert" size={15} />
            <div className="notice_body">{applyError}</div>
          </div>
        )}
        {devices.length === 0 ? (
          <div className="placeholder">
            <span>{t("ui.agent_service.no_devices")}</span>
            <span className="faint">
              {t("ui.agent_service.no_devices_hint")}
            </span>
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

      {enabledDevices.length === 0 ? (
        <div className="placeholder">
          <span>{t("ui.agent_service.no_active", { module: moduleName })}</span>
          <span className="faint">{t("ui.agent_service.no_active_hint")}</span>
        </div>
      ) : (
        <TabStrip
          label={t("ui.agent_service.devices_label")}
          tabs={enabledDevices.map(toTab)}
          selected={selectedId}
          onSelect={setSelectedId}
        />
      )}

      {selected !== null && selected.state !== INSTALLED_STATE && (
        <p
          className={`agent_service_state ${
            selected.state === FAILED_STATE ? "agent_service_state--error" : ""
          }`}
        >
          {describeDeviceState(selected, moduleName)}
        </p>
      )}

      {selected !== null && selected.state === INSTALLED_STATE && (
        <fieldset className="agent_service_body" disabled={!selected.is_online}>
          {!selected.is_online && (
            <div className="notice notice--warn">
              <Icon name="alert" size={15} />
              <div className="notice_body">{t("ui.agent_service.offline")}</div>
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
          titleKey="ui.agent_service.consent_title"
          confirmKey="ui.agent_service.consent_confirm"
          onConfirm={() => void applyDevices()}
          onCancel={() => setIsConsentOpen(false)}
        />
      )}
    </div>
  );
}

/** One machine the module is asked for, as the tab strip wants it. */
function toTab(device: ModuleDeviceView): StripTab {
  const stateKey: string | undefined = TAB_STATE_KEYS[device.state];
  return {
    key: device.device_id,
    name: device.name,
    tag: stateKey === undefined ? undefined : t(stateKey),
    tagTone: IN_FLIGHT_STATES.includes(device.state) ? "warn" : "error",
    dotTone: device.is_online ? "ok" : "idle",
  };
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

/** A picked machine the module does not stand on yet, in one line. */
function describeDeviceState(
  device: ModuleDeviceView,
  moduleName: string,
): string {
  if (device.state === FAILED_STATE) {
    return describeDeviceCode(device);
  }
  if (!device.is_online) {
    return t("ui.agent_service.offline");
  }
  const key =
    DEVICE_STATE_KEYS[device.state] ?? "ui.agent_service.device_absent";
  return t(key, { module: moduleName, device: device.name });
}

/** A refused apply, worded from the code and the device it names. */
function describeApplyError(
  cause: unknown,
  devices: ModuleDeviceView[],
): string {
  if (!(cause instanceof ApiError)) {
    return describeError(cause);
  }
  if (cause.code !== "agent_offline") {
    return describeError(cause);
  }
  const detail = cause.detail as { params?: Record<string, unknown> } | null;
  const deviceId = detail?.params?.device_id;
  const named = devices.find((device) => device.device_id === deviceId);
  return t("ui.agent_service.apply_agent_offline", {
    device: named?.name ?? String(deviceId ?? ""),
  });
}

/** One machine's own failure, worded from what its agent reported. */
function describeDeviceCode(device: ModuleDeviceView): string {
  const key = DEVICE_ERROR_KEYS[device.code];
  if (key !== undefined) {
    return t(key, { device: device.name });
  }
  if (device.code === "") {
    return t("ui.agent_service.device_failed", { device: device.name });
  }
  return t("ui.agent_service.device_code", {
    device: device.name,
    code: device.code,
  });
}
