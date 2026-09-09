import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { DeviceChipStrip } from "../components/device_chip_strip";
import { ErrorPanel } from "../components/error_panel";
import { FileBrowser } from "../components/file_browser";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_DEVICES } from "../use_hub_events";
import type { DeviceChip } from "../components/device_chip_strip";
import type { DevicesOnlineResponse } from "../api_types";

/**
 * Files on a managed machine.
 *
 * The page opens on a machine the way every other Agent-group page does: the
 * chips are the machines whose agent is answering, the hub box among them,
 * and the browser below belongs to whichever one is picked. A drawer's Files
 * link arrives with `?device=` and lands on that machine.
 */

const WORDING = {
  title: "Files",
  pick: "Which machine",
  pickHint: "Files below are on this machine.",
  noDevices: "No machine is answering",
  noDevicesHint: "Install the agent on a machine from the Devices page.",
  noPick: "No machine picked",
  noPickHint: "Pick a machine above to browse it.",
};

// What moves the list of machines: an agent's channel opening or ending.
const INVALIDATE_ON = [{ type: HUB_EVENT_DEVICES }];

/** The query a page link carries to open on one machine. */
const DEVICE_QUERY = "device";

export function FilesPage() {
  const resource = useApiResource<DevicesOnlineResponse>("/devices/online", {
    invalidateOn: INVALIDATE_ON,
  });
  const [searchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // A link from a device's drawer names the machine it came from.
  const askedDeviceId = searchParams.get(DEVICE_QUERY);
  useEffect(() => {
    if (askedDeviceId !== null) {
      setSelectedId(askedDeviceId);
    }
  }, [askedDeviceId]);

  const devices = resource.data?.devices ?? [];
  const chips: DeviceChip[] = devices.map((device) => ({
    key: device.device_id,
    label: device.name,
    hostname: device.hostname,
    isOnline: true,
  }));
  const selectedDevice =
    devices.find((device) => device.device_id === selectedId) ?? null;

  if (resource.error !== null && devices.length === 0) {
    return (
      <div className="page">
        <h1>{WORDING.title}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{WORDING.title}</h1>
        </div>
      </div>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{WORDING.pick}</h2>
        </div>
        <p className="field_hint">{WORDING.pickHint}</p>
        {resource.isLoading && devices.length === 0 ? (
          <div className="skeleton" style={{ height: 48 }} />
        ) : devices.length === 0 ? (
          <div className="placeholder">
            <span>{WORDING.noDevices}</span>
            <span className="faint">{WORDING.noDevicesHint}</span>
          </div>
        ) : (
          <DeviceChipStrip
            chips={chips}
            selected={selectedId}
            onSelect={setSelectedId}
            isMulti={false}
          />
        )}
      </section>

      {selectedDevice === null ? (
        devices.length > 0 && (
          <div className="placeholder">
            <span>{WORDING.noPick}</span>
            <span className="faint">{WORDING.noPickHint}</span>
          </div>
        )
      ) : (
        <FileBrowser
          key={selectedDevice.device_id}
          basePath={`/devices/${selectedDevice.device_id}/files`}
        />
      )}
    </div>
  );
}
