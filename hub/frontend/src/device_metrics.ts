import type {
  DeviceClientInfo,
  DeviceGpuInfo,
  DeviceProcessInfo,
  DeviceView,
} from "./api_types";
import type { HubEvent } from "./use_hub_events";

/**
 * The vitals a `metrics` event carries, and how they land on a device.
 *
 * Every heartbeat brings these, so they ride the event rather than a refetch:
 * the tiles, the drawer header and the monitor redraw from what arrived. They
 * are exactly the fields the hub builds a device's client block from, so
 * folding one in leaves the rest of the device untouched.
 */

export interface DeviceMetrics {
  cpu_percent: number | null;
  memory_percent: number | null;
  disk_percent: number | null;
  temperature_c: number | null;
  uptime_s: number | null;
  load_average: number[];
  cpu_core_percents: number[];
  gpus: DeviceGpuInfo[];
  processes: DeviceProcessInfo[];
}

/**
 * Read one `metrics` event's payload.
 *
 * Args:
 *   event: The event as it arrived.
 *
 * Returns:
 *   The vitals, or null when the frame carried none.
 */
export function toDeviceMetrics(event: HubEvent): DeviceMetrics | null {
  const data = event.data;
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const reading = data as Partial<DeviceMetrics>;
  return {
    cpu_percent: toReading(reading.cpu_percent),
    memory_percent: toReading(reading.memory_percent),
    disk_percent: toReading(reading.disk_percent),
    temperature_c: toReading(reading.temperature_c),
    uptime_s: toReading(reading.uptime_s),
    load_average: Array.isArray(reading.load_average)
      ? reading.load_average
      : [],
    cpu_core_percents: Array.isArray(reading.cpu_core_percents)
      ? reading.cpu_core_percents
      : [],
    gpus: Array.isArray(reading.gpus) ? reading.gpus : [],
    processes: Array.isArray(reading.processes) ? reading.processes : [],
  };
}

/**
 * Put one machine's vitals on the device the list holds for it.
 *
 * Args:
 *   devices: The list as it stands.
 *   macAddress: Whose vitals these are.
 *   metrics: What arrived.
 *   reportedAt: When the report the vitals came from arrived.
 *
 * Returns:
 *   The list, with that one device's client block replaced. The same list
 *   comes back where the device is unknown or carries no agent, so nothing
 *   redraws for a machine the page is not showing.
 */
export function withDeviceMetrics(
  devices: DeviceView[],
  macAddress: string,
  metrics: DeviceMetrics,
  reportedAt: string,
): DeviceView[] {
  const held = devices.find((device) => device.mac_address === macAddress);
  if (held === undefined || held.client === null) {
    return devices;
  }
  const client: DeviceClientInfo = {
    ...held.client,
    ...metrics,
    last_report_at: reportedAt,
  };
  return devices.map((device) =>
    device.mac_address === macAddress ? { ...device, client } : device,
  );
}

function toReading(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}
