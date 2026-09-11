import { NavLink } from "react-router-dom";

import { Icon } from "./icon";
import { t, useLanguage } from "../i18n";
import { NAV_ITEMS } from "../nav_items";
import "./bottom_nav.css";

/**
 * The bottom bar for narrow and portrait viewports, where the rail is hidden.
 *
 * Icons only, one row along the bottom edge, scrolling sideways when the
 * pages outnumber the width. Every page the sidebar would list is here in the
 * same order, with Sign out set apart at the end; each button's title carries
 * the name the missing label would have shown.
 */

interface BottomNavProps {
  onLogout: () => void;
}

export function BottomNav({ onLogout }: BottomNavProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const signOut = t("ui.shell.sign_out");
  return (
    <nav className="bottom_nav" aria-label={t("ui.shell.nav_label")}>
      <div className="bottom_nav_items">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            title={t(item.labelKey)}
            aria-label={t(item.labelKey)}
            className={({ isActive }) =>
              `bottom_nav_item ${isActive ? "bottom_nav_item--active" : ""}`
            }
          >
            <Icon name={item.icon} size={18} />
          </NavLink>
        ))}
        <button
          type="button"
          className="bottom_nav_item bottom_nav_logout"
          onClick={onLogout}
          title={signOut}
          aria-label={signOut}
        >
          <Icon name="logout" size={18} />
        </button>
      </div>
    </nav>
  );
}
