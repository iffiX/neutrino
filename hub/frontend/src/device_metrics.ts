import type { DeviceMetricsView, DeviceView } from "./api_types";
import type { HubEvent } from "./use_hub_events";

/**
 * The readings a `metrics` event carries, and how they land on a device.
 *
 * Every report brings these, so they ride the event rather than a refetch:
 * the Agents page's rings and the machine page's monitor redraw from what
 * arrived. They are the agent's `machine.metrics`, the document a device's
 * `client.metrics` holds, so folding one in leaves the rest of the device
 * untouched.
 */

/**
 * Read one `metrics` event's payload.
 *
 * Args:
 *   event: The event as it arrived.
 *
 * Returns:
 *   The readings, or null when the frame carried none.
 */
export function toDeviceMetrics(event: HubEvent): DeviceMetricsView | null {
  const data = event.data;
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const reading = data as Partial<DeviceMetricsView>;
  return {
    cpu_percent: toReading(reading.cpu_percent),
    cpu_core_percents: Array.isArray(reading.cpu_core_percents)
      ? reading.cpu_core_percents
      : [],
    memory_percent: toReading(reading.memory_percent),
    disk_percent: toReading(reading.disk_percent),
    temperature_c: toReading(reading.temperature_c),
    uptime_s: toReading(reading.uptime_s),
    load_average: Array.isArray(reading.load_average)
      ? reading.load_average
      : [],
    gpus: Array.isArray(reading.gpus) ? reading.gpus : [],
    processes: Array.isArray(reading.processes) ? reading.processes : [],
  };
}

/**
 * Put one machine's readings on the device the list holds for it.
 *
 * Args:
 *   devices: The list as it stands.
 *   deviceId: Whose readings these are.
 *   metrics: What arrived.
 *   reportedAt: When the report the readings came from arrived.
 *
 * Returns:
 *   The list, with that one device's readings replaced. The same list comes
 *   back where the device is unknown or has not reported, so nothing redraws
 *   for a machine the page is not showing.
 */
export function withDeviceMetrics(
  devices: DeviceView[],
  deviceId: string,
  metrics: DeviceMetricsView,
  reportedAt: string,
): DeviceView[] {
  const held = devices.find((device) => device.id === deviceId);
  if (held === undefined || held.client === null) {
    return devices;
  }
  const client = { ...held.client, metrics, last_report_at: reportedAt };
  return devices.map((device) =>
    device.id === deviceId ? { ...device, client } : device,
  );
}

function toReading(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}
