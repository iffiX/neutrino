import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import type { IconName } from "./icon";
import { t, useLanguage } from "../i18n";

import "./row_menu.css";

/**
 * A row's actions: shown on hover where there is a pointer, and behind an
 * always-visible ⋯ button on a touch screen or a narrow window, the way a
 * phone's file manager puts a row's actions behind a menu.
 *
 * The row's own buttons are the children and keep their hover rule. The menu
 * lists the same actions; an item that arms rather than acts keeps the menu
 * open, so its second press lands on the same item.
 */

/** Room left between the ⋯ button and its menu, in pixels. */
const ROW_MENU_GAP_PX = 4;

export interface RowMenuItem {
  /** Tells the items apart. */
  key: string;
  label: string;
  icon: IconName;
  onSelect: () => void;
  /** Whether the item removes or ends something. */
  isDanger?: boolean;
  /** Whether a press arms the item rather than acting, keeping the menu open. */
  isArming?: boolean;
  /** Whether it is armed now, and the next press acts. */
  isArmed?: boolean;
}

interface RowMenuProps {
  /** The row's own buttons, shown on hover where there is a pointer. */
  children: ReactNode;
  items: RowMenuItem[];
}

export function RowMenu({ children, items }: RowMenuProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [place, setPlace] = useState<CSSProperties | null>(null);

  useEffect(() => {
    if (place === null) {
      return;
    }
    const close = (event: Event) => {
      const target = event.target as Node | null;
      if (
        target !== null &&
        (menuRef.current?.contains(target) ||
          toggleRef.current?.contains(target))
      ) {
        return;
      }
      setPlace(null);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPlace(null);
      }
    };
    const closeOnScroll = () => setPlace(null);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("scroll", closeOnScroll, true);
    window.addEventListener("resize", closeOnScroll);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("scroll", closeOnScroll, true);
      window.removeEventListener("resize", closeOnScroll);
    };
  }, [place]);

  const toggle = () => {
    if (place !== null || toggleRef.current === null) {
      setPlace(null);
      return;
    }
    setPlace(menuPlace(toggleRef.current.getBoundingClientRect()));
  };

  const select = (item: RowMenuItem) => {
    if (!(item.isArming && !item.isArmed)) {
      setPlace(null);
    }
    item.onSelect();
  };

  return (
    <span className="row_menu">
      <span className="row_menu_inline">{children}</span>
      <button
        ref={toggleRef}
        type="button"
        className="row_menu_toggle"
        aria-label={t("ui.row_menu.open")}
        aria-haspopup="menu"
        aria-expanded={place !== null}
        onClick={toggle}
      >
        <span aria-hidden="true">⋯</span>
      </button>
      {place !== null &&
        createPortal(
          <div
            ref={menuRef}
            className="row_menu_list"
            role="menu"
            style={place}
          >
            {items.map((item) => (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                className={`row_menu_item ${item.isDanger ? "row_menu_item--danger" : ""} ${item.isArmed ? "row_menu_item--armed" : ""}`}
                onClick={() => select(item)}
              >
                <Icon name={item.icon} size={14} />
                {item.label}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </span>
  );
}

/** Where the menu opens: under the button, or above it in the lower half. */
function menuPlace(anchor: DOMRect): CSSProperties {
  const right = window.innerWidth - anchor.right;
  if (anchor.top > window.innerHeight / 2) {
    return { right, bottom: window.innerHeight - anchor.top + ROW_MENU_GAP_PX };
  }
  return { right, top: anchor.bottom + ROW_MENU_GAP_PX };
}
