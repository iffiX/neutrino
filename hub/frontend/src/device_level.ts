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

export const DEVICE_REACH_LABELS: Record<DeviceReach, string> = {
  none: "No access",
  ssh: "SSH",
  agent: "Agent",
};

export const DEVICE_REACH_HINTS: Record<DeviceReach, string> = {
  none: "Found on the network. Add SSH details to manage it.",
  ssh: "Terminal, file transfer, deployments, reboot and shutdown.",
  agent: "Reports its own vitals and installs modules without SSH.",
};

/** What the gateway holds for this device. */
export function toDeviceReach(device: DeviceView): DeviceReach {
  if (device.client !== null && device.client.is_installed) {
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
