import { NavLink } from "react-router-dom";

import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import { toDeviceLabel } from "../device_level";
import { t, useLanguage } from "../i18n";
import { NAV_ITEMS } from "../nav_items";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_DEVICES } from "../use_hub_events";
import type { DevicesResponse, DeviceView } from "../api_types";
import "./sidebar_nav.css";
import neutrinoMark from "../images/neutrino_mark.png";

/**
 * The fixed left rail.
 *
 * The active route is marked by a glowing cyan bar rather than a filled block,
 * so the eye finds the current page instantly without the nav competing with
 * the page content for attention. Narrow and portrait viewports hide the rail
 * and show the bottom bar (bottom_nav.tsx) in its place.
 *
 * Two groups. The hub group is the hub's own pages; the machine group under
 * it holds one entry per managed machine, its status dot pulsing green while
 * the machine is online and grey with a faint `offline` otherwise, each a
 * link to its machine page.
 */

/** The paths whose entry is lit only at the path itself, not below it. */
const EXACT_PATHS = ["/", "/agents"];

/** What moves the machine group: a machine came, went, or was named. */
const DEVICES_INVALIDATE_ON = [{ type: HUB_EVENT_DEVICES }];

interface SidebarNavProps {
  onLogout: () => void;
}

export function SidebarNav({ onLogout }: SidebarNavProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const devices = useApiResource<DevicesResponse>("/hub/device", {
    invalidateOn: DEVICES_INVALIDATE_ON,
  });
  const machines = devices.data?.devices ?? [];
  return (
    <nav className="sidebar_nav" aria-label={t("ui.shell.nav_label")}>
      <div className="sidebar_brand">
        <span className="sidebar_brand_mark">
          <img className="brand_mark_image" src={neutrinoMark} alt="" />
        </span>
        <span className="sidebar_brand_text">
          <span className="sidebar_brand_name">{t("ui.brand.hub")}</span>
          <span className="sidebar_brand_sub">{t("ui.shell.brand_sub")}</span>
        </span>
      </div>

      <div className="sidebar_items">
        <div className="sidebar_group">
          <div className="sidebar_group_label">{t("ui.shell.group_hub")}</div>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={EXACT_PATHS.includes(item.path)}
              title={t(item.descriptionKey)}
              className={({ isActive }) =>
                `sidebar_item ${isActive ? "sidebar_item--active" : ""}`
              }
            >
              <Icon name={item.icon} size={17} className="sidebar_item_icon" />
              <span className="sidebar_item_label">{t(item.labelKey)}</span>
            </NavLink>
          ))}
        </div>
        {machines.length > 0 && (
          <div className="sidebar_group">
            <div className="sidebar_group_label">
              {t("ui.shell.group_agent")}
            </div>
            {machines.map((machine) => (
              <MachineEntry key={machine.id} machine={machine} />
            ))}
          </div>
        )}
      </div>

      <div className="sidebar_footer">
        <button
          type="button"
          className="button button--ghost button--small sidebar_logout"
          onClick={onLogout}
          title={t("ui.shell.sign_out")}
        >
          <Icon name="logout" size={14} />
          <span className="sidebar_logout_label">{t("ui.shell.sign_out")}</span>
        </button>
      </div>
    </nav>
  );
}

interface MachineEntryProps {
  machine: DeviceView;
}

function MachineEntry({ machine }: MachineEntryProps) {
  const isOnline = machine.is_agent_online;
  const label = toDeviceLabel(machine);
  return (
    <NavLink
      to={`/agents/${encodeURIComponent(machine.id)}`}
      title={label}
      className={({ isActive }) =>
        `sidebar_item sidebar_machine ${isActive ? "sidebar_item--active" : ""}`
      }
    >
      <span className="sidebar_machine_dot">
        <StatusDot tone={isOnline ? "ok" : "idle"} isPulsing={isOnline} />
      </span>
      <span className="sidebar_item_label sidebar_machine_name">{label}</span>
      {!isOnline && (
        <span className="sidebar_machine_offline">{t("state.offline")}</span>
      )}
    </NavLink>
  );
}
