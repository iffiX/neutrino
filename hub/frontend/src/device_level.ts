import type { DeviceView } from "./api_types";

/**
 * What a managed machine is called: its name, else the MAC its agent last
 * used, else the host it was added by, else its id.
 *
 * Args:
 *   device: The machine's row.
 *
 * Returns:
 *   The name the panel shows for it.
 */
export function toDeviceLabel(device: DeviceView): string {
  if (device.name !== null && device.name !== "") {
    return device.name;
  }
  if (device.link_mac.length > 0) {
    return device.link_mac;
  }
  return device.ssh?.host || device.id;
}
