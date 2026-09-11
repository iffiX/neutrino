import { useEffect, useState } from "react";

import { DeviceDrawer } from "../components/device_drawer";
import { DeviceEnrollmentNotice } from "../components/device_enrollment_notice";
import { DeviceMonitor } from "../components/device_monitor";
import { DeviceTile } from "../components/device_tile";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { apiPost, describeError } from "../api_client";
import {
  isDeviceManaged,
  toDeviceReach,
  toDevicePresence,
} from "../device_level";
import type { DeviceReach } from "../device_level";
import { toDeviceMetrics, withDeviceMetrics } from "../device_metrics";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import {
  HUB_EVENT_DEVICE_REPORT,
  HUB_EVENT_DEVICES,
  HUB_EVENT_METRICS,
  useHubEvents,
} from "../use_hub_events";
import type { HubEvent } from "../use_hub_events";
import type {
  DeviceEnrollmentView,
  DevicesResponse,
  DeviceView,
} from "../api_types";

import "./devices_page.css";

/**
 * Every host the gateway can see on the LAN, split by whether it is managed.
 *
 * Managed devices run the agent and report themselves; unmanaged ones are
 * whatever else the scanner found, each showing the one step that would make
 * it managed. The filters and the search sit above both sections and narrow
 * each of them. A scan is explicit rather than automatic — ARP sweeping the
 * LAN on every page load would be rude to sleeping devices.
 */

type DeviceFilter = "all" | "online" | "offline" | DeviceReach;

interface DeviceLegendRow {
  labelKey: string;
  tone: string;
  hintKey: string;
}

// What moves this list: a machine's channel opening or ending, a machine
// named, forgotten or enrolled, and a report saying something new about one.
const INVALIDATE_ON = [
  { type: HUB_EVENT_DEVICES },
  { type: HUB_EVENT_DEVICE_REPORT },
];

const FILTER_KEYS: Record<DeviceFilter, string> = {
  all: "ui.devices.filter_all",
  online: "ui.devices.filter_online",
  offline: "ui.devices.filter_offline",
  none: "ui.devices.filter_scanned",
  ssh: "ui.devices.filter_ssh",
  agent: "ui.devices.filter_agent",
};

// What each badge on a tile means, listed under the filters.
const DEVICE_LEGEND: DeviceLegendRow[] = [
  {
    labelKey: "state.agent",
    tone: "badge--ok",
    hintKey: "ui.devices.legend_agent",
  },
  {
    labelKey: "state.ssh",
    tone: "badge--accent",
    hintKey: "ui.devices.legend_ssh",
  },
  {
    labelKey: "state.scanned",
    tone: "",
    hintKey: "ui.devices.legend_scanned",
  },
  {
    labelKey: "state.offline",
    tone: "badge--warn",
    hintKey: "ui.devices.legend_offline",
  },
];

export function DevicesPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<DevicesResponse>("/devices", {
    invalidateOn: INVALIDATE_ON,
  });

  const [devices, setDevices] = useState<DeviceView[]>([]);
  const [filter, setFilter] = useState<DeviceFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedMac, setSelectedMac] = useState<string | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  // A link a machine joins with, for the ones the gateway cannot reach first.
  const [enrollment, setEnrollment] = useState<DeviceEnrollmentView | null>(
    null,
  );

  useEffect(() => {
    if (resource.data !== null) {
      setDevices(resource.data.devices);
    }
  }, [resource.data]);

  // Vitals ride their own event, so a heartbeat lands on the tiles, the
  // drawer header and the monitor without the list being asked for again.
  const handleMetrics = (event: HubEvent) => {
    const metrics = toDeviceMetrics(event);
    if (metrics === null) {
      return;
    }
    setDevices((current) =>
      withDeviceMetrics(current, event.key, metrics, event.at),
    );
  };
  useHubEvents([{ type: HUB_EVENT_METRICS }], handleMetrics);

  // The task's own outcome, read at once rather than waiting for the agent
  // to reconnect and say so itself.
  const handleTaskFinished = () => {
    resource.reload();
  };

  const handleScan = async () => {
    setIsScanning(true);
    setScanError(null);
    try {
      const result = await apiPost<DevicesResponse>("/devices/scan");
      setDevices(result.devices);
    } catch (cause: unknown) {
      setScanError(describeError(cause));
    } finally {
      setIsScanning(false);
    }
  };

  const handleEnrollmentLink = async () => {
    setScanError(null);
    try {
      setEnrollment(
        await apiPost<DeviceEnrollmentView>("/devices/enrollment", {}),
      );
    } catch (cause: unknown) {
      setScanError(describeError(cause));
    }
  };

  const handleSaved = (saved: DeviceView) => {
    setDevices((current) =>
      current.map((device) =>
        device.mac_address === saved.mac_address ? saved : device,
      ),
    );
  };

  const handleForgotten = (macAddress: string) => {
    setDevices((current) =>
      current.filter((device) => device.mac_address !== macAddress),
    );
    setSelectedMac(null);
  };

  const visibleDevices = devices.filter(
    (device) => matchesFilter(device, filter) && matchesSearch(device, search),
  );
  const managedDevices = visibleDevices.filter(isDeviceManaged);
  const unmanagedDevices = visibleDevices.filter(
    (device) => !isDeviceManaged(device),
  );
  const managedCount = devices.filter(isDeviceManaged).length;
  const hasManaged = managedCount > 0;
  const hasUnmanaged = managedCount < devices.length;
  const selectedDevice =
    devices.find((device) => device.mac_address === selectedMac) ?? null;

  if (resource.error !== null && devices.length === 0) {
    return (
      <div className="page">
        <h1>{t("ui.devices.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <div className="page_title_row">
            <h1>{t("ui.devices.title")}</h1>
            <span className="badge">
              {t("ui.devices.badge", {
                managed: managedCount,
                total: devices.length,
              })}
            </span>
          </div>
        </div>
        <div className="page_actions">
          <button
            type="button"
            className="button"
            onClick={() => void handleEnrollmentLink()}
          >
            <Icon name="link" size={14} />
            {t("ui.devices.add_by_link")}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => void handleScan()}
            disabled={isScanning}
          >
            <Icon name="search" size={14} />
            {isScanning ? t("ui.devices.scanning") : t("ui.devices.scan")}
          </button>
        </div>
      </div>

      {scanError !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{scanError}</div>
        </div>
      )}

      {enrollment !== null && (
        <DeviceEnrollmentNotice
          link={enrollment.link}
          expiresInS={enrollment.expires_in_s}
          title={t("ui.devices.enrollment_title")}
          hint={t("ui.devices.enrollment_hint")}
          onDismiss={() => setEnrollment(null)}
        />
      )}

      <div className="devices_filters">
        {(Object.keys(FILTER_KEYS) as DeviceFilter[]).map((name) => (
          <button
            key={name}
            type="button"
            className={`devices_filter ${filter === name ? "devices_filter--active" : ""}`}
            onClick={() => setFilter(name)}
          >
            {t(FILTER_KEYS[name])}
            {name !== "all" && ` · ${countMatching(devices, name)}`}
          </button>
        ))}
        <input
          className="input devices_search"
          placeholder={t("ui.devices.search_placeholder")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <div className="devices_legend">
        {DEVICE_LEGEND.map((row) => (
          <span key={row.labelKey} className="devices_legend_item">
            <span className={`badge ${row.tone}`}>{t(row.labelKey)}</span>
            {t(row.hintKey)}
          </span>
        ))}
      </div>

      {resource.isLoading && devices.length === 0 ? (
        <div className="devices_grid">
          <div className="skeleton" style={{ height: 170 }} />
          <div className="skeleton" style={{ height: 170 }} />
          <div className="skeleton" style={{ height: 170 }} />
          <div className="skeleton" style={{ height: 170 }} />
        </div>
      ) : devices.length === 0 ? (
        <div className="placeholder">
          <span>{t("ui.devices.none_title")}</span>
          <span className="faint">{t("ui.devices.none_hint")}</span>
        </div>
      ) : (
        <>
          <DeviceSection
            title={t("ui.devices.managed_title")}
            hint={t("ui.devices.managed_hint")}
            badge={t("ui.devices.managed_badge", {
              reporting: managedDevices.filter(
                (device) => device.is_agent_online,
              ).length,
              total: managedDevices.length,
            })}
            devices={managedDevices}
            emptyTitle={t(
              hasManaged
                ? "ui.devices.filtered_empty_title"
                : "ui.devices.managed_empty_title",
            )}
            emptyHint={t(
              hasManaged
                ? "ui.devices.filtered_empty_hint"
                : "ui.devices.managed_empty_hint",
            )}
            onOpen={setSelectedMac}
          />
          <DeviceSection
            title={t("ui.devices.unmanaged_title")}
            hint={t("ui.devices.unmanaged_hint")}
            badge={t("ui.devices.unmanaged_badge", {
              ssh: unmanagedDevices.filter((device) => device.has_ssh).length,
              total: unmanagedDevices.length,
            })}
            devices={unmanagedDevices}
            emptyTitle={t(
              hasUnmanaged
                ? "ui.devices.filtered_empty_title"
                : "ui.devices.unmanaged_empty_title",
            )}
            emptyHint={t(
              hasUnmanaged
                ? "ui.devices.filtered_empty_hint"
                : "ui.devices.unmanaged_empty_hint",
            )}
            onOpen={setSelectedMac}
          />
        </>
      )}

      {selectedDevice !== null && (
        <>
          <DeviceMonitor device={selectedDevice} />
          <DeviceDrawer
            key={selectedDevice.mac_address}
            device={selectedDevice}
            onClose={() => setSelectedMac(null)}
            onSaved={handleSaved}
            onForgotten={handleForgotten}
            onTaskFinished={handleTaskFinished}
          />
        </>
      )}
    </div>
  );
}

interface DeviceSectionProps {
  title: string;
  hint: string;
  badge: string;
  devices: DeviceView[];
  emptyTitle: string;
  emptyHint: string;
  onOpen: (macAddress: string) => void;
}

function DeviceSection({
  title,
  hint,
  badge,
  devices,
  emptyTitle,
  emptyHint,
  onOpen,
}: DeviceSectionProps) {
  return (
    <section className="devices_section">
      <div className="settings_group_title">
        <h2>{title}</h2>
        {devices.length > 0 && <span className="badge">{badge}</span>}
      </div>
      <p className="field_hint">{hint}</p>
      {devices.length === 0 ? (
        <div className="placeholder">
          <span>{emptyTitle}</span>
          <span className="faint">{emptyHint}</span>
        </div>
      ) : (
        <div className="devices_grid">
          {devices.map((device) => (
            <DeviceTile
              key={device.mac_address}
              device={device}
              onOpen={() => onOpen(device.mac_address)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function matchesFilter(device: DeviceView, filter: DeviceFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "online") {
    return toDevicePresence(device) !== "offline";
  }
  if (filter === "offline") {
    return toDevicePresence(device) === "offline";
  }
  return toDeviceReach(device) === filter;
}

function matchesSearch(device: DeviceView, search: string): boolean {
  const needle = search.trim().toLowerCase();
  if (needle.length === 0) {
    return true;
  }
  return [
    device.name ?? "",
    device.ipv4_address,
    device.mac_address,
    device.vendor,
  ].some((field) => field.toLowerCase().includes(needle));
}

function countMatching(devices: DeviceView[], filter: DeviceFilter): number {
  return devices.filter((device) => matchesFilter(device, filter)).length;
}
