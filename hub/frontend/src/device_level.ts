import { describeCode } from "./api_client";
import type { DeviceView } from "./api_types";

/** The code the hub marks a row that joined under 0.5 with. */
const HUB_KEY_MISSING = "hub_key_missing";

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

/**
 * The words for a machine whose row joined under 0.5, or null for any other.
 *
 * Args:
 *   device: The machine's row.
 *
 * Returns:
 *   The words of `code.hub_key_missing`, or null.
 */
export function describeJoinedUnder05(device: DeviceView): string | null {
  const error = device.client?.last_error ?? null;
  if (error === null || error.code !== HUB_KEY_MISSING) {
    return null;
  }
  return describeCode(error);
}
