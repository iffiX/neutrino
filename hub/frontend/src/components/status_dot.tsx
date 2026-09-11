import { t, useLanguage } from "../i18n";

import "./status_dot.css";

/**
 * The one-glance health indicator used by nodes, devices and services.
 *
 * An `ok` dot pulses so a screen left open still reads as live; every other
 * tone is static, because a blinking failure is harder to scan, not easier.
 */

export type StatusTone = "ok" | "warn" | "error" | "idle";

const TONE_KEYS: Record<StatusTone, string> = {
  ok: "ui.status_dot.ok",
  warn: "ui.status_dot.warn",
  error: "ui.status_dot.error",
  idle: "ui.status_dot.idle",
};

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
  // Redrawn when the panel's language changes.
  useLanguage();
  const shouldPulse = isPulsing ?? tone === "ok";
  const toneLabel = t(TONE_KEYS[tone]);
  const classNames = [
    "status_dot",
    `status_dot--${tone}`,
    isLarge ? "status_dot--large" : "",
    shouldPulse ? "status_dot--pulsing" : "",
  ]
    .filter((name) => name.length > 0)
    .join(" ");

  if (label === undefined) {
    return <span className={classNames} role="img" aria-label={toneLabel} />;
  }

  return (
    <span className="status_label">
      <span className={classNames} role="img" aria-label={toneLabel} />
      <span className="muted">{label}</span>
    </span>
  );
}
