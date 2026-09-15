import type { ReactNode } from "react";

import { DeviceChipStrip } from "./device_chip_strip";
import { t, useLanguage } from "../i18n";
import type { DeviceChip } from "./device_chip_strip";
import type { DeviceOnlineView } from "../api_types";

import "./device_pick.css";

/**
 * The section every Agent-group page opens with: which machine.
 *
 * The chips are the machines whose agent is answering, the hub box among
 * them, and whatever the page does below belongs to the picked one. Terminals,
 * Files and Modules share this one control, so picking a machine reads the
 * same on each; the page passes the list it already holds, since it needs the
 * picked machine's name itself.
 */

/** How tall the strip is while the list is still on its way. */
const SKELETON_HEIGHT_PX = 48;

interface DevicePickProps {
  /** The machines whose agent is answering, hub box first. */
  devices: DeviceOnlineView[];
  /** Whether the first list is still on its way. */
  isLoading: boolean;
  /** What the page does on the picked machine, in one line. */
  hint: string;
  selected: string | null;
  onSelect: (deviceId: string) => void;
  /** A page-scope action that sits at the section's far end. */
  actions?: ReactNode;
}

export function DevicePick({
  devices,
  isLoading,
  hint,
  selected,
  onSelect,
  actions,
}: DevicePickProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const chips: DeviceChip[] = devices.map(toChip);

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.device_pick.title")}</h2>
        {actions !== undefined && (
          <div className="device_pick_actions">{actions}</div>
        )}
      </div>
      <p className="field_hint">{hint}</p>
      {isLoading && devices.length === 0 ? (
        <div className="skeleton" style={{ height: SKELETON_HEIGHT_PX }} />
      ) : devices.length === 0 ? (
        <div className="placeholder">
          <span>{t("ui.device_pick.no_devices")}</span>
          <span className="faint">{t("ui.device_pick.no_devices_hint")}</span>
        </div>
      ) : (
        <DeviceChipStrip
          chips={chips}
          selected={selected}
          onSelect={onSelect}
          isMulti={false}
        />
      )}
    </section>
  );
}

/** One online machine as the chip strip wants it. */
function toChip(device: DeviceOnlineView): DeviceChip {
  return {
    key: device.device_id,
    label: device.name,
    hostname: device.hostname,
    isOnline: true,
  };
}
