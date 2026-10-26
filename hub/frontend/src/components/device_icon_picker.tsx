import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import type { IconName } from "./icon";
import { DEVICE_ICON_NAMES } from "../device_icon";
import { t, useLanguage } from "../i18n";

import "./device_icon_picker.css";

/**
 * A machine's icon as a button that opens the grid of device icons under
 * it; a pick is handed back at once, and Escape, a press elsewhere or a
 * scroll close the grid.
 */

/** Room left between the button and its grid, in pixels. */
const GRID_GAP_PX = 4;

interface DeviceIconPickerProps {
  icon: IconName;
  isDisabled?: boolean;
  onPick: (icon: IconName) => void;
}

export function DeviceIconPicker({
  icon,
  isDisabled = false,
  onPick,
}: DeviceIconPickerProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [place, setPlace] = useState<CSSProperties | null>(null);

  useEffect(() => {
    if (place === null) {
      return;
    }
    const close = (event: Event) => {
      const target = event.target as Node | null;
      if (
        target !== null &&
        (gridRef.current?.contains(target) ||
          buttonRef.current?.contains(target))
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
    const button = buttonRef.current;
    if (place !== null || button === null) {
      setPlace(null);
      return;
    }
    const box = button.getBoundingClientRect();
    setPlace({ top: box.bottom + GRID_GAP_PX, left: box.left });
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="device_icon_picker_button"
        title={t("ui.devices.icon")}
        aria-label={t("ui.devices.icon")}
        aria-expanded={place !== null}
        disabled={isDisabled}
        onClick={toggle}
      >
        <Icon name={icon} size={18} />
      </button>
      {place !== null &&
        createPortal(
          <div
            ref={gridRef}
            className="device_icon_picker_grid"
            style={place}
            role="listbox"
            aria-label={t("ui.devices.icon")}
          >
            {DEVICE_ICON_NAMES.map((option) => (
              <button
                key={option}
                type="button"
                role="option"
                title={option}
                aria-label={option}
                aria-selected={icon === option}
                className={`device_icon_picker_option ${
                  icon === option ? "device_icon_picker_option--on" : ""
                }`}
                onClick={() => {
                  setPlace(null);
                  if (option !== icon) {
                    onPick(option);
                  }
                }}
              >
                <Icon name={option} size={16} />
              </button>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
