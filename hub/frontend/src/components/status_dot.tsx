import "./status_dot.css";

/**
 * The one-glance health indicator used by nodes, devices and services.
 *
 * An `ok` dot pulses so a screen left open still reads as live; every other
 * tone is static, because a blinking failure is harder to scan, not easier.
 */

export type StatusTone = "ok" | "warn" | "error" | "idle";

interface StatusDotProps {
  tone: StatusTone;
  label?: string;
  isLarge?: boolean;
  isPulsing?: boolean;
}

export function StatusDot({
  tone,
  label,
  isLarge = false,
  isPulsing,
}: StatusDotProps) {
  const shouldPulse = isPulsing ?? tone === "ok";
  const classNames = [
    "status_dot",
    `status_dot--${tone}`,
    isLarge ? "status_dot--large" : "",
    shouldPulse ? "status_dot--pulsing" : "",
  ]
    .filter((name) => name.length > 0)
    .join(" ");

  if (label === undefined) {
    return <span className={classNames} role="img" aria-label={tone} />;
  }

  return (
    <span className="status_label">
      <span className={classNames} role="img" aria-label={tone} />
      <span className="muted">{label}</span>
    </span>
  );
}
