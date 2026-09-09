import { NavLink } from "react-router-dom";

import { Icon } from "./icon";
import { navItemsInGroup } from "../nav_items";
import type { NavGroup, NavItem } from "../nav_items";
import "./sidebar_nav.css";

/**
 * The fixed left rail.
 *
 * The active route is marked by a glowing cyan bar rather than a filled block,
 * so the eye finds the current page instantly without the nav competing with
 * the page content for attention. Narrow and portrait viewports hide the rail
 * and show the bottom bar (bottom_nav.tsx) in its place.
 *
 * Two zones, always both, always whole. Hub is the box itself; Agent is what
 * the hub drives on a machine running the agent.
 */

const GROUP_LABELS: Record<NavGroup, string> = {
  hub: "Hub",
  agent: "Agent",
};

interface SidebarNavProps {
  onLogout: () => void;
}

export function SidebarNav({ onLogout }: SidebarNavProps) {
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
        <SidebarGroup group="hub" items={navItemsInGroup("hub")} />
        <SidebarGroup group="agent" items={navItemsInGroup("agent")} />
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
      {items.map((item) => (
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
      ))}
    </div>
  );
}
