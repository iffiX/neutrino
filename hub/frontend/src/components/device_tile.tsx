import { DeviceGauge } from "./device_gauge";
import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { toDeviceIconName } from "../device_icon";
import {
  isDeviceManaged,
  toDeviceReach,
  toDevicePresence,
  toDeviceUpgradePath,
} from "../device_level";
import type { DeviceUpgradePath } from "../device_level";
import type { DeviceClientInfo, DeviceGpuInfo, DeviceView } from "../api_types";

import "./device_tile.css";

/**
 * One LAN host, drawn by what the gateway can do with it and whether it can
 * do it now.
 *
 * A device the scanner merely saw is dashed and dimmed and offers only to take
 * SSH details. One with SSH or an agent can be acted on, and says so even when
 * it is currently offline — losing sight of a machine does not lose the
 * credentials for it. Vitals appear only where an agent reports them, and the
 * last-seen stamp only where the agent is not answering now.
 */

const TEMPERATURE_WARN_C = 70;
const TEMPERATURE_ERROR_C = 85;

// The footer of an unmanaged tile names the step that manages it.
const UPGRADE_PATH_KEYS: Record<DeviceUpgradePath, string> = {
  install: "ui.device_tile.install_agent",
  link: "ui.device_tile.get_link",
};

const UPGRADE_PATH_ICONS: Record<DeviceUpgradePath, "download" | "link"> = {
  install: "download",
  link: "link",
};

const VERSION_MISMATCH_KEYS: Record<DeviceUpgradePath, string> = {
  install: "ui.device_tile.version_mismatch_install",
  link: "ui.device_tile.version_mismatch_link",
};

/** The gauge captions, which are the same abbreviations in every language. */
const GAUGE_CPU = "cpu";
const GAUGE_MEMORY = "mem";
const GAUGE_DISK = "disk";
const GAUGE_TEMPERATURE = "temp";
const GAUGE_GPU = "gpu";
const GAUGE_VRAM = "vram";

interface DeviceTileProps {
  device: DeviceView;
  onOpen: () => void;
}

export function DeviceTile({ device, onOpen }: DeviceTileProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const reach = toDeviceReach(device);
  const presence = toDevicePresence(device);
  const upgradePath = toDeviceUpgradePath(device);
  const isManaged = isDeviceManaged(device);
  const client = device.client;
  const platform = client === null ? null : toPlatformLabel(client);

  return (
    <button
      type="button"
      className={`device_tile device_tile--${reach} ${
        presence === "offline" ? "device_tile--offline" : ""
      }`}
      onClick={onOpen}
    >
      <div className="device_tile_head">
        <span className="device_tile_icon">
          <Icon name={toDeviceIconName(device.icon)} size={19} />
        </span>
        <span className="device_tile_identity">
          <span className="device_tile_name">
            <StatusDot
              tone={presence === "offline" ? "idle" : "ok"}
              isPulsing={presence === "reporting"}
            />
            <span className="device_tile_name_text">
              {device.name ?? device.mac_address}
            </span>
          </span>
          <span className="device_tile_address">{device.ipv4_address}</span>
          <span className="device_tile_vendor" title={device.vendor}>
            {device.client?.hostname ??
              (device.vendor.length > 0
                ? device.vendor
                : t("ui.device_tile.unknown_vendor"))}
          </span>
        </span>
      </div>

      <div className="device_tile_levels">
        {reach === "none" && (
          <span className="badge">{t("state.scanned")}</span>
        )}
        {reach !== "none" && (
          <span className="badge badge--accent">{t("state.ssh")}</span>
        )}
        {reach === "agent" && (
          <span className="badge badge--ok">{t("state.agent")}</span>
        )}
        {presence === "offline" && reach !== "none" && (
          <span className="badge badge--warn">{t("state.offline")}</span>
        )}
        {client !== null && client.version !== null && (
          <span
            className={`badge${client.is_version_mismatched ? " badge--warn" : ""}`}
            title={
              client.is_version_mismatched
                ? t(VERSION_MISMATCH_KEYS[upgradePath])
                : undefined
            }
          >
            v{client.version}
          </span>
        )}
        {isManaged && platform !== null && (
          <span className="badge">{platform}</span>
        )}
      </div>

      {reach === "agent" && client !== null && (
        <div className="device_tile_gauges">
          <DeviceGauge label={GAUGE_CPU} reading={client.cpu_percent} />
          <DeviceGauge label={GAUGE_MEMORY} reading={client.memory_percent} />
          <DeviceGauge label={GAUGE_DISK} reading={client.disk_percent} />
          <DeviceGauge
            label={GAUGE_TEMPERATURE}
            reading={client.temperature_c}
            unit="°C"
            warnAt={TEMPERATURE_WARN_C}
            errorAt={TEMPERATURE_ERROR_C}
          />
          {client.gpus.length > 0 && (
            <>
              <DeviceGauge
                label={GAUGE_GPU}
                reading={maxUtilization(client.gpus)}
              />
              <DeviceGauge
                label={GAUGE_VRAM}
                reading={vramPercent(client.gpus)}
              />
            </>
          )}
        </div>
      )}

      <div className="device_tile_footer">
        {isManaged ? (
          <span className="mono">{device.mac_address}</span>
        ) : (
          <span className="device_tile_path">
            <Icon name={UPGRADE_PATH_ICONS[upgradePath]} size={12} />
            {t(UPGRADE_PATH_KEYS[upgradePath])}
          </span>
        )}
        {isManaged && client !== null && !client.is_online && (
          <span>{formatTimeAgo(client.last_seen)}</span>
        )}
      </div>
    </button>
  );
}

/** What the agent says the machine is, once it has reported it. */
function toPlatformLabel(client: DeviceClientInfo): string | null {
  if (client.platform_os === null) {
    return null;
  }
  if (client.platform_arch === null) {
    return client.platform_os;
  }
  return `${client.platform_os} · ${client.platform_arch}`;
}

/** The busiest card's load — on a multi-GPU box that is the one that matters. */
function maxUtilization(gpus: DeviceGpuInfo[]): number | null {
  const readings = gpus
    .map((gpu) => gpu.utilization_percent)
    .filter((value): value is number => value !== null);
  return readings.length > 0 ? Math.max(...readings) : null;
}

function vramPercent(gpus: DeviceGpuInfo[]): number | null {
  let used = 0;
  let total = 0;
  for (const gpu of gpus) {
    if (gpu.memory_used_mb !== null && gpu.memory_total_mb !== null) {
      used += gpu.memory_used_mb;
      total += gpu.memory_total_mb;
    }
  }
  return total > 0 ? (100 * used) / total : null;
}
