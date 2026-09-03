import { useContext } from "react";
import { NavLink } from "react-router-dom";

import { Icon } from "./icon";
import { visibleNavItems } from "../nav_items";
import { ServicesContext } from "../services_context";
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
  // The same shared service list the sidebar reads, so both navs agree on
  // which optional pages exist in the same render.
  const services = useContext(ServicesContext);
  const enabled = (services?.data?.services ?? [])
    .filter((service) => service.is_enabled && !service.is_core)
    .map((service) => service.name);
  const items = visibleNavItems(enabled);

  return (
    <nav className="bottom_nav" aria-label="Main">
      <div className="bottom_nav_items">
        {items.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            title={item.label}
            aria-label={item.label}
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
          title="Sign out"
          aria-label="Sign out"
        >
          <Icon name="logout" size={18} />
        </button>
      </div>
    </nav>
  );
}
