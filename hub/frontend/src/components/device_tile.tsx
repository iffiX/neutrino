import { DeviceGauge } from "./device_gauge";
import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import { formatTimeAgo } from "../format_duration";
import { toDeviceIconName } from "../device_icon";
import { toDeviceReach, toDevicePresence } from "../device_level";
import type { DeviceGpuInfo, DeviceView } from "../api_types";

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

interface DeviceTileProps {
  device: DeviceView;
  onOpen: () => void;
}

export function DeviceTile({ device, onOpen }: DeviceTileProps) {
  const reach = toDeviceReach(device);
  const presence = toDevicePresence(device);
  const client = device.client;

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
            {device.vendor.length > 0 ? device.vendor : "unknown vendor"}
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
                ? "This agent is a different version from the hub. Reinstall it from the drawer."
                : undefined
            }
          >
            v{client.version}
          </span>
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
        {reach === "none" ? (
          <span className="device_tile_add_ssh">
            <Icon name="plus" size={12} />
            Add SSH
          </span>
        ) : (
          <span className="mono">{device.mac_address}</span>
        )}
        {reach === "agent" && client !== null && (
          <span>{formatTimeAgo(client.last_seen)}</span>
        )}
      </div>
    </button>
  );
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
