import type { IconName } from "./components/icon";

/**
 * The icon vocabulary a device annotation may carry.
 *
 * `DeviceView.icon` is a free-form string on the backend, so the panel maps it
 * onto the icon set here rather than trusting it, and falls back to a neutral
 * glyph for anything it does not recognise. A device nobody has given an icon
 * takes one from the system its agent reports.
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

/** The icon a machine with an agent takes before anybody picks one. */
const PLATFORM_ICONS: Record<string, IconName> = {
  linux: "server",
  darwin: "desktop",
  windows: "desktop",
};

/**
 * Resolve a stored device icon name to one this panel can draw.
 *
 * Args:
 *   icon: The annotation value, or null for a device nobody has named yet.
 *   platformOs: The system its agent reports, or null without one.
 *
 * Returns:
 *   A known icon name; without one, the system's, else `unknown`.
 */
export function toDeviceIconName(
  icon: string | null,
  platformOs: string | null = null,
): IconName {
  if (icon === null) {
    return (
      (platformOs === null ? undefined : PLATFORM_ICONS[platformOs]) ??
      "unknown"
    );
  }
  const candidate = icon.trim().toLowerCase();
  const match = DEVICE_ICON_NAMES.find((name) => name === candidate);
  return match ?? "unknown";
}
