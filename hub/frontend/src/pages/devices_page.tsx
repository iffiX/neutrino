import { useEffect, useState } from "react";

import { DeviceDrawer } from "../components/device_drawer";
import { DeviceEnrollmentNotice } from "../components/device_enrollment_notice";
import { DeviceMonitor } from "../components/device_monitor";
import { DeviceTile } from "../components/device_tile";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { apiGet, apiPost, describeError } from "../api_client";
import {
  isDeviceManaged,
  toDeviceReach,
  toDevicePresence,
} from "../device_level";
import type { DeviceReach } from "../device_level";
import { useApiResource } from "../use_api_resource";
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
  label: string;
  tone: string;
  hint: string;
}

// How often the list quietly refreshes so agents and metrics stay current.
const DEVICE_POLL_INTERVAL_MS = 6000;

const FILTER_LABELS: Record<DeviceFilter, string> = {
  all: "All",
  online: "Online",
  offline: "Offline",
  none: "Scanned only",
  ssh: "SSH",
  agent: "Agent",
};

// What the page says about itself, its two sections, and what each badge means.
const PAGE_BADGE = "{managed} of {total} managed";

const MANAGED_TITLE = "Managed devices";
const MANAGED_HINT =
  "Agents report in from these machines; vitals, modules and power are managed here.";
const MANAGED_BADGE = "{reporting} of {total} reporting";
const MANAGED_EMPTY_TITLE = "No managed devices yet";
const MANAGED_EMPTY_HINT =
  "Install the agent on a device below, or send it an enrollment link.";

const UNMANAGED_TITLE = "Unmanaged devices";
const UNMANAGED_HINT =
  "No agent yet: install one over SSH, or send an enrollment link.";
const UNMANAGED_BADGE = "{ssh} of {total} with SSH";
const UNMANAGED_EMPTY_TITLE = "Every device is managed";
const UNMANAGED_EMPTY_HINT = "Nothing here is waiting for an agent.";

const FILTERED_EMPTY_TITLE = "No devices match";
const FILTERED_EMPTY_HINT = "Try a different filter or clear the search.";

const NO_DEVICES_TITLE = "No devices yet";
const NO_DEVICES_HINT = "Run a LAN scan to discover what is connected.";

const DEVICE_LEGEND: DeviceLegendRow[] = [
  {
    label: "agent",
    tone: "badge--ok",
    hint: "Managed: reports its own vitals and takes modules from the hub.",
  },
  {
    label: "ssh",
    tone: "badge--accent",
    hint: "Unmanaged with credentials: one action installs the agent.",
  },
  {
    label: "scanned",
    tone: "",
    hint: "Unmanaged with no credentials: send it an enrollment link.",
  },
  {
    label: "offline",
    tone: "badge--warn",
    hint: "Not answering. Its credentials keep working once it returns.",
  },
];

export function DevicesPage() {
  const resource = useApiResource<DevicesResponse>("/devices");

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

  // Auto-refresh: an agent that just came online, or one whose metrics changed,
  // should appear without a manual reload. The list endpoint is the cheap,
  // arp-scan-free one, so polling it is quiet. Refreshing the list does not
  // disturb the open drawer — its form fields are their own state.
  useEffect(() => {
    let isCancelled = false;
    const poll = async () => {
      if (isScanning) {
        return;
      }
      try {
        const result = await apiGet<DevicesResponse>("/devices");
        if (!isCancelled) {
          setDevices(result.devices);
        }
      } catch {
        // A transient failure is ignored; the next tick tries again.
      }
    };
    const handle = window.setInterval(
      () => void poll(),
      DEVICE_POLL_INTERVAL_MS,
    );
    return () => {
      isCancelled = true;
      window.clearInterval(handle);
    };
  }, [isScanning]);

  // Once now for the task's own outcome, once again after the agent's first
  // heartbeat window, so a fresh install reads as online without waiting for
  // the next poll tick.
  const refreshDevices = async () => {
    try {
      const result = await apiGet<DevicesResponse>("/devices");
      setDevices(result.devices);
    } catch {
      // The poll picks it up on its next tick.
    }
  };

  const handleTaskFinished = () => {
    void refreshDevices();
    window.setTimeout(() => void refreshDevices(), 2500);
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
        <h1>Devices</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <div className="page_title_row">
            <h1>Devices</h1>
            <span className="badge">
              {fill(PAGE_BADGE, {
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
            Add by link
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => void handleScan()}
            disabled={isScanning}
          >
            <Icon name="search" size={14} />
            {isScanning ? "Scanning…" : "Scan LAN"}
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
          enrollment={enrollment}
          deviceName={null}
          onDismiss={() => setEnrollment(null)}
        />
      )}

      <div className="devices_filters">
        {(Object.keys(FILTER_LABELS) as DeviceFilter[]).map((name) => (
          <button
            key={name}
            type="button"
            className={`devices_filter ${filter === name ? "devices_filter--active" : ""}`}
            onClick={() => setFilter(name)}
          >
            {FILTER_LABELS[name]}
            {name !== "all" && ` · ${countMatching(devices, name)}`}
          </button>
        ))}
        <input
          className="input devices_search"
          placeholder="Filter by name, IP or MAC"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <div className="devices_legend">
        {DEVICE_LEGEND.map((row) => (
          <span key={row.label} className="devices_legend_item">
            <span className={`badge ${row.tone}`}>{row.label}</span>
            {row.hint}
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
          <span>{NO_DEVICES_TITLE}</span>
          <span className="faint">{NO_DEVICES_HINT}</span>
        </div>
      ) : (
        <>
          <DeviceSection
            title={MANAGED_TITLE}
            hint={MANAGED_HINT}
            badge={fill(MANAGED_BADGE, {
              reporting: managedDevices.filter(
                (device) => device.is_agent_online,
              ).length,
              total: managedDevices.length,
            })}
            devices={managedDevices}
            emptyTitle={hasManaged ? FILTERED_EMPTY_TITLE : MANAGED_EMPTY_TITLE}
            emptyHint={hasManaged ? FILTERED_EMPTY_HINT : MANAGED_EMPTY_HINT}
            onOpen={setSelectedMac}
          />
          <DeviceSection
            title={UNMANAGED_TITLE}
            hint={UNMANAGED_HINT}
            badge={fill(UNMANAGED_BADGE, {
              ssh: unmanagedDevices.filter((device) => device.has_ssh).length,
              total: unmanagedDevices.length,
            })}
            devices={unmanagedDevices}
            emptyTitle={
              hasUnmanaged ? FILTERED_EMPTY_TITLE : UNMANAGED_EMPTY_TITLE
            }
            emptyHint={
              hasUnmanaged ? FILTERED_EMPTY_HINT : UNMANAGED_EMPTY_HINT
            }
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

/** Put counts into a wording constant, by name. */
function fill(wording: string, values: Record<string, number>): string {
  let filled = wording;
  for (const [name, value] of Object.entries(values)) {
    filled = filled.replace(`{${name}}`, String(value));
  }
  return filled;
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
