import type { ReactNode } from "react";

import "./toggle_switch.css";

/**
 * The panel's only on/off control.
 *
 * It renders as a real `button` with `role="switch"` so keyboard and screen
 * reader users get the same affordance as the pointer, and so a disabled
 * switch cannot be toggled by a stray click while a request is in flight.
 */

interface ToggleSwitchProps {
  isOn: boolean;
  onChange: (isOn: boolean) => void;
  label?: string;
  /** The switch's name where a title beside it already shows it. */
  ariaLabel?: string;
  description?: string;
  /** A tag beside the label, for a state this switch does not set. */
  badge?: ReactNode;
  isDisabled?: boolean;
}

export function ToggleSwitch({
  isOn,
  onChange,
  label,
  ariaLabel,
  description,
  badge,
  isDisabled = false,
}: ToggleSwitchProps) {
  const handleClick = () => {
    onChange(!isOn);
  };

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isOn}
      aria-label={label ?? ariaLabel}
      className={`toggle_switch ${isOn ? "toggle_switch--on" : ""}`}
      disabled={isDisabled}
      onClick={handleClick}
    >
      <span className="toggle_switch_track">
        <span className="toggle_switch_thumb" />
      </span>
      {(label !== undefined || description !== undefined) && (
        <span className="toggle_switch_text">
          {label !== undefined && (
            <span className="toggle_switch_label">
              {label}
              {badge}
            </span>
          )}
          {description !== undefined && (
            <span className="toggle_switch_description">{description}</span>
          )}
        </span>
      )}
    </button>
  );
}
