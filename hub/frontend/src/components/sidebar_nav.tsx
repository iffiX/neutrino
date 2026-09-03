import { useContext } from "react";
import { NavLink } from "react-router-dom";

import { Icon } from "./icon";
import { navItemsInGroup, visibleNavItems } from "../nav_items";
import type { NavGroup, NavItem } from "../nav_items";
import { ServicesContext } from "../services_context";
import "./sidebar_nav.css";

/**
 * The fixed left rail.
 *
 * The active route is marked by a glowing cyan bar rather than a filled block,
 * so the eye finds the current page instantly without the nav competing with
 * the page content for attention. Narrow and portrait viewports hide the rail
 * and show the bottom bar (bottom_nav.tsx) in its place.
 *
 * Two zones, always both. Core is what makes this a gateway; Optional is what
 * the box also hosts, and each of those appears only once its service is
 * enabled — an appliance serving no files should not have a Files page telling
 * it so. The Optional heading stays even when nothing is under it, because an
 * empty half says "there is more this box can do" where a missing half would
 * say nothing at all.
 */

const GROUP_LABELS: Record<NavGroup, string> = {
  core: "Core",
  optional: "Optional",
};

// What an empty half says for itself. Only Optional can be empty: a gateway
// with no core pages would be a panel with nothing to show.
const EMPTY_OPTIONAL_HINT = "Nothing switched on";

interface SidebarNavProps {
  onLogout: () => void;
}

export function SidebarNav({ onLogout }: SidebarNavProps) {
  // The shell's shared copy of the service list, the same one the Services
  // page writes its actions into — which is what makes disabling a service
  // drop its page from here immediately rather than on the next refetch.
  const services = useContext(ServicesContext);
  const enabled = (services?.data?.services ?? [])
    .filter((service) => service.is_enabled && !service.is_core)
    .map((service) => service.name);
  const items = visibleNavItems(enabled);

  return (
    <nav className="sidebar_nav" aria-label="Main">
      <div className="sidebar_brand">
        <span className="sidebar_brand_mark">
          <Icon name="proxy" size={15} />
        </span>
        <span className="sidebar_brand_text">
          <span className="sidebar_brand_name">Neutrino Hub</span>
          <span className="sidebar_brand_sub">control panel</span>
        </span>
      </div>

      <div className="sidebar_items">
        <SidebarGroup group="core" items={navItemsInGroup(items, "core")} />
        <SidebarGroup
          group="optional"
          items={navItemsInGroup(items, "optional")}
        />
      </div>

      <div className="sidebar_footer">
        <button
          type="button"
          className="button button--ghost button--small sidebar_logout"
          onClick={onLogout}
          title="Sign out"
        >
          <Icon name="logout" size={14} />
          <span className="sidebar_logout_label">Sign out</span>
        </button>
      </div>
    </nav>
  );
}

interface SidebarGroupProps {
  group: NavGroup;
  items: NavItem[];
}

function SidebarGroup({ group, items }: SidebarGroupProps) {
  return (
    <div className="sidebar_group">
      <div className="sidebar_group_label">{GROUP_LABELS[group]}</div>
      {items.length === 0 ? (
        <div className="sidebar_group_empty">{EMPTY_OPTIONAL_HINT}</div>
      ) : (
        items.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            title={item.description}
            className={({ isActive }) =>
              `sidebar_item ${isActive ? "sidebar_item--active" : ""}`
            }
          >
            <Icon name={item.icon} size={17} className="sidebar_item_icon" />
            <span className="sidebar_item_label">{item.label}</span>
          </NavLink>
        ))
      )}
    </div>
  );
}
