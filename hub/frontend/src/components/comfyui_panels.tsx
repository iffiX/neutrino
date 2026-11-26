import { ComfyuiSettings } from "./comfyui_settings";
import { ErrorPanel } from "./error_panel";
import { apiPath } from "../api_client";
import { useLanguage } from "../i18n";
import { usePolledResource } from "../use_polled_resource";
import type { ComfyuiDeviceView } from "../api_types";

/**
 * The ComfyUI module's Configure on one machine: **Settings**, drawn from
 * one view read every few seconds, so its apply bar follows the machine's
 * report.
 */

interface ComfyuiPanelsProps {
  /** The machine ComfyUI runs on. */
  deviceId: string;
  /** Where the module answers: `/agent/module/comfyui`. */
  basePath: string;
  /** Why nothing here can be applied, or null while it can. */
  blockedHint: string | null;
  /** The machine's system: `linux`, `windows` or `darwin`. */
  platformOs: string;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
}

/** How often the view is read. */
const POLL_INTERVAL_MS = 5000;

export function ComfyuiPanels({
  deviceId,
  basePath,
  blockedHint,
  platformOs,
  want,
}: ComfyuiPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = usePolledResource<ComfyuiDeviceView>(
    apiPath(basePath, { device_id: deviceId }),
    POLL_INTERVAL_MS,
  );
  const saved = resource.data;

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null) {
    return <div className="skeleton" style={{ height: 160 }} />;
  }

  return (
    <ComfyuiSettings
      deviceId={deviceId}
      basePath={basePath}
      saved={saved}
      blockedHint={blockedHint}
      platformOs={platformOs}
      want={want}
      onSaved={resource.setData}
    />
  );
}
