import { DeviceGauge } from "./device_gauge";
import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import { formatTimeAgo } from "../format_duration";
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
 * credentials for it. Vitals appear only where an agent reports them.
 */

const TEMPERATURE_WARN_C = 70;
const TEMPERATURE_ERROR_C = 85;

// The footer of an unmanaged tile names the step that manages it.
const UPGRADE_PATH_LABELS: Record<DeviceUpgradePath, string> = {
  install: "Install agent",
  link: "Get link",
};

const UPGRADE_PATH_ICONS: Record<DeviceUpgradePath, "download" | "link"> = {
  install: "download",
  link: "link",
};

const VERSION_MISMATCH_TITLES: Record<DeviceUpgradePath, string> = {
  install:
    "This agent is a different version from the hub. Reinstall it from the drawer.",
  link: "This agent is a different version from the hub. Re-enroll it with a fresh link from the drawer.",
};

interface DeviceTileProps {
  device: DeviceView;
  onOpen: () => void;
}

export function DeviceTile({ device, onOpen }: DeviceTileProps) {
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
              (device.vendor.length > 0 ? device.vendor : "unknown vendor")}
          </span>
        </span>
      </div>

      <div className="device_tile_levels">
        {reach === "none" && <span className="badge">scanned</span>}
        {reach !== "none" && <span className="badge badge--accent">ssh</span>}
        {reach === "agent" && <span className="badge badge--ok">agent</span>}
        {presence === "offline" && reach !== "none" && (
          <span className="badge badge--warn">offline</span>
        )}
        {client !== null && client.version !== null && (
          <span
            className={`badge${client.is_version_mismatched ? " badge--warn" : ""}`}
            title={
              client.is_version_mismatched
                ? VERSION_MISMATCH_TITLES[upgradePath]
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
          <DeviceGauge label="cpu" reading={client.cpu_percent} />
          <DeviceGauge label="mem" reading={client.memory_percent} />
          <DeviceGauge label="disk" reading={client.disk_percent} />
          <DeviceGauge
            label="temp"
            reading={client.temperature_c}
            unit="°C"
            warnAt={TEMPERATURE_WARN_C}
            errorAt={TEMPERATURE_ERROR_C}
          />
          {client.gpus.length > 0 && (
            <>
              <DeviceGauge label="gpu" reading={maxUtilization(client.gpus)} />
              <DeviceGauge label="vram" reading={vramPercent(client.gpus)} />
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
            {UPGRADE_PATH_LABELS[upgradePath]}
          </span>
        )}
        {isManaged && client !== null && (
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
