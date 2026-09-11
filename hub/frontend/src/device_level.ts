import type { DeviceView } from "./api_types";

/**
 * What the panel can do with a device, and whether it can do it right now.
 *
 * Two independent questions, kept apart because conflating them is what makes
 * a device list confusing. **Reach** is what the gateway holds: nothing, SSH
 * credentials, or an installed agent — SSH and the agent are both real
 * control, the agent simply reaching further. **Presence** is whether the
 * machine is answering at all this minute.
 *
 * Both are derived rather than stored, so the tile, the drawer and the filters
 * can never disagree about what a device is.
 */

/** What the gateway holds for a device. */
export type DeviceReach = "none" | "ssh" | "agent";

/** Whether it is answering, and by what. */
export type DevicePresence = "offline" | "seen" | "reporting";

/** How a device reaches the managed state, or gets its agent back in step. */
export type DeviceUpgradePath = "install" | "link";

/** What each reach is called, as catalog keys the caller words. */
export const DEVICE_REACH_KEYS: Record<DeviceReach, string> = {
  none: "ui.device_level.reach_none",
  ssh: "ui.device_level.reach_ssh",
  agent: "ui.device_level.reach_agent",
};

/** Whether the hub manages this device through its own agent. */
export function isDeviceManaged(device: DeviceView): boolean {
  return device.client !== null && device.client.is_managed;
}

/**
 * Which way this device gets an agent that matches the hub.
 *
 * The SSH installer needs systemd, so a machine that reports another
 * platform, or holds no credentials, joins by enrollment link. A platform
 * nobody has reported yet stays on the SSH path.
 */
export function toDeviceUpgradePath(device: DeviceView): DeviceUpgradePath {
  if (!device.has_ssh) {
    return "link";
  }
  const platformOs = device.client?.platform_os ?? null;
  return platformOs !== null && platformOs !== "linux" ? "link" : "install";
}

/** What the gateway holds for this device. */
export function toDeviceReach(device: DeviceView): DeviceReach {
  if (isDeviceManaged(device)) {
    return "agent";
  }
  if (device.has_ssh) {
    return "ssh";
  }
  return "none";
}

/**
 * Whether the device is answering.
 *
 * `reporting` means its agent is beating, which is the strongest evidence and
 * the only one that works over the overlay. `seen` means the network sweep
 * found it but nothing is reporting. `offline` means neither.
 */
export function toDevicePresence(device: DeviceView): DevicePresence {
  if (device.is_agent_online) {
    return "reporting";
  }
  return device.is_online ? "seen" : "offline";
}

/** Whether the gateway could act on this device right now. */
export function isDeviceControllable(device: DeviceView): boolean {
  return (
    toDeviceReach(device) !== "none" && toDevicePresence(device) !== "offline"
  );
}
