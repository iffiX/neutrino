import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

import { DevicePick } from "../components/device_pick";
import { ErrorPanel } from "../components/error_panel";
import { FileBrowser } from "../components/file_browser";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { usePageMemory } from "../use_page_memory";
import { HUB_EVENT_DEVICES } from "../use_hub_events";
import type { DevicesOnlineResponse } from "../api_types";

/**
 * Files on a managed machine.
 *
 * The page opens on a machine the way every other Agent-group page does: the
 * chips are the machines whose agent is answering, the hub box among them,
 * and the browser below belongs to whichever one is picked. A drawer's Files
 * link arrives with `?device=` and lands on that machine. The machine picked
 * and the directory open on it are kept between visits, until a reload.
 */

// What moves the list of machines: an agent's channel opening or ending.
const INVALIDATE_ON = [{ type: HUB_EVENT_DEVICES }];

/** The query a page link carries to open on one machine. */
const DEVICE_QUERY = "device";

export function FilesPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<DevicesOnlineResponse>("/hub/device/online", {
    invalidateOn: INVALIDATE_ON,
  });
  const [searchParams] = useSearchParams();
  const [selectedId, setSelectedId] = usePageMemory<string | null>(
    "files.device",
    null,
  );

  // A link from a device's drawer names the machine it came from.
  const askedDeviceId = searchParams.get(DEVICE_QUERY);
  useEffect(() => {
    if (askedDeviceId !== null) {
      setSelectedId(askedDeviceId);
    }
  }, [askedDeviceId, setSelectedId]);

  const devices = resource.data?.devices ?? [];
  const selectedDevice =
    devices.find((device) => device.device_id === selectedId) ?? null;

  if (resource.error !== null && devices.length === 0) {
    return (
      <div className="page">
        <h1>{t("ui.files.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{t("ui.files.title")}</h1>
        </div>
      </div>

      <DevicePick
        devices={devices}
        isLoading={resource.isLoading}
        hint={t("ui.files.pick_hint")}
        selected={selectedId}
        onSelect={setSelectedId}
      />

      {selectedDevice === null ? (
        devices.length > 0 && (
          <div className="placeholder">
            <span>{t("ui.files.no_pick")}</span>
            <span className="faint">{t("ui.files.no_pick_hint")}</span>
          </div>
        )
      ) : (
        <FileBrowser
          key={selectedDevice.device_id}
          deviceId={selectedDevice.device_id}
        />
      )}
    </div>
  );
}
