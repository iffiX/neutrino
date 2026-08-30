import { useEffect, useState } from "react";

import { DeviceDrawer } from "../components/device_drawer";
import { DeviceMonitor } from "../components/device_monitor";
import { DeviceTile } from "../components/device_tile";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { apiGet, apiPost, describeError } from "../api_client";
import {
  DEVICE_REACH_HINTS,
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
 * Every host the gateway can see on the LAN.
 *
 * The grid is deliberately mixed: hosts the scanner merely found sit next to
 * fully managed ones, because the point of the page is to make the gap
 * obvious and easy to close. A scan is explicit rather than automatic — ARP
 * sweeping the LAN on every page load would be rude to sleeping devices.
 */

type DeviceFilter = "all" | "online" | "offline" | DeviceReach;

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
          <h1>Devices</h1>
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
        <div className="notice devices_enrollment">
          <Icon name="link" size={15} />
          <div className="notice_body">
            <strong>Paste this into the machine&apos;s own agent page</strong>
            <span className="muted">
              Install the agent there, open http://127.0.0.1:8765, and paste the
              link. It works for {Math.round(enrollment.expires_in_s / 60)}{" "}
              minutes.
            </span>
            <div className="devices_enrollment_link">
              <code>{enrollment.link}</code>
              <button
                type="button"
                className="button button--small"
                onClick={() =>
                  void navigator.clipboard.writeText(enrollment.link)
                }
              >
                <Icon name="file" size={13} />
                Copy
              </button>
              <button
                type="button"
                className="button button--small button--ghost"
                onClick={() => setEnrollment(null)}
              >
                <Icon name="close" size={13} />
              </button>
            </div>
          </div>
        </div>
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
        <span className="devices_legend_item">
          <span className="badge">scanned</span>
          {DEVICE_REACH_HINTS.none}
        </span>
        <span className="devices_legend_item">
          <span className="badge badge--accent">ssh</span>
          {DEVICE_REACH_HINTS.ssh}
        </span>
        <span className="devices_legend_item">
          <span className="badge badge--ok">agent</span>
          {DEVICE_REACH_HINTS.agent}
        </span>
        <span className="devices_legend_item">
          <span className="badge badge--warn">offline</span>
          Not answering. Its credentials keep working once it returns.
        </span>
      </div>

      {resource.isLoading && devices.length === 0 ? (
        <div className="devices_grid">
          <div className="skeleton" style={{ height: 170 }} />
          <div className="skeleton" style={{ height: 170 }} />
          <div className="skeleton" style={{ height: 170 }} />
          <div className="skeleton" style={{ height: 170 }} />
        </div>
      ) : visibleDevices.length === 0 ? (
        <div className="placeholder">
          <span>
            {devices.length === 0 ? "No devices yet" : "No devices match"}
          </span>
          <span className="faint">
            {devices.length === 0
              ? "Run a LAN scan to discover what is connected."
              : "Try a different filter or clear the search."}
          </span>
        </div>
      ) : (
        <div className="devices_grid">
          {visibleDevices.map((device) => (
            <DeviceTile
              key={device.mac_address}
              device={device}
              onOpen={() => setSelectedMac(device.mac_address)}
            />
          ))}
        </div>
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
          />
        </>
      )}
    </div>
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
