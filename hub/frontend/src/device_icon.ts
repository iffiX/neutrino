import type { IconName } from "./components/icon";

/**
 * The icon vocabulary a device annotation may carry.
 *
 * `DeviceView.icon` is a free-form string on the backend, so the panel maps it
 * onto the icon set here rather than trusting it, and falls back to a neutral
 * glyph for anything it does not recognise.
 */

export const DEVICE_ICON_NAMES: IconName[] = [
  "laptop",
  "desktop",
  "phone",
  "tablet",
  "tv",
  "printer",
  "server",
  "nas",
  "camera",
  "router",
  "unknown",
];

/**
 * Resolve a stored device icon name to one this panel can draw.
 *
 * Args:
 *   icon: The annotation value, or null for a device nobody has named yet.
 *
 * Returns:
 *   A known icon name, defaulting to `unknown`.
 */
export function toDeviceIconName(icon: string | null): IconName {
  if (icon === null) {
    return "unknown";
  }
  const candidate = icon.trim().toLowerCase();
  const match = DEVICE_ICON_NAMES.find((name) => name === candidate);
  return match ?? "unknown";
}
