import "./spinner.css";

/**
 * The panel's in-progress indicator.
 *
 * Used where an action takes long enough that a frozen button would read as a
 * broken one — joining a Wi-Fi network, which can sit for twenty seconds while
 * the radio associates and DHCP answers.
 */

interface SpinnerProps {
  size?: number;
  label?: string;
}

export function Spinner({ size = 14, label }: SpinnerProps) {
  return (
    <span className="spinner_wrap">
      <span
        className="spinner"
        style={{ width: size, height: size }}
        role="status"
        aria-label={label ?? "Working"}
      />
      {label !== undefined && <span className="muted">{label}</span>}
    </span>
  );
}
