import { NavLink } from "react-router-dom";

import { Icon } from "./icon";
import { t, useLanguage } from "../i18n";
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

/** The product's own name, which is the same in every language. */
const SIDEBAR_BRAND_NAME = "Neutrino Hub";

const GROUP_KEYS: Record<NavGroup, string> = {
  hub: "ui.shell.group_hub",
  agent: "ui.shell.group_agent",
};

interface SidebarNavProps {
  onLogout: () => void;
}

export function SidebarNav({ onLogout }: SidebarNavProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <nav className="sidebar_nav" aria-label={t("ui.shell.nav_label")}>
      <div className="sidebar_brand">
        <span className="sidebar_brand_mark">
          <Icon name="proxy" size={15} />
        </span>
        <span className="sidebar_brand_text">
          <span className="sidebar_brand_name">{SIDEBAR_BRAND_NAME}</span>
          <span className="sidebar_brand_sub">{t("ui.shell.brand_sub")}</span>
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
          title={t("ui.shell.sign_out")}
        >
          <Icon name="logout" size={14} />
          <span className="sidebar_logout_label">{t("ui.shell.sign_out")}</span>
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
      <div className="sidebar_group_label">{t(GROUP_KEYS[group])}</div>
      {items.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          end={item.path === "/"}
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
  );
}
