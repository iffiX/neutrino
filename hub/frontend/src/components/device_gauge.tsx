import "./device_gauge.css";

/**
 * One vitals bar on an L2 device tile.
 *
 * A neutrino_client host reports percentages and a temperature through the
 * same shape, so the thresholds are parameters rather than two near-identical
 * components. A missing reading renders as an em dash and an empty track,
 * never as zero — an unreported CPU is not an idle one.
 */

const WARN_PERCENT = 75;
const ERROR_PERCENT = 90;

interface DeviceGaugeProps {
  label: string;
  reading: number | null;
  unit?: string;
  warnAt?: number;
  errorAt?: number;
}

export function DeviceGauge({
  label,
  reading,
  unit = "%",
  warnAt = WARN_PERCENT,
  errorAt = ERROR_PERCENT,
}: DeviceGaugeProps) {
  const hasReading = reading !== null && Number.isFinite(reading);
  const clamped = hasReading ? Math.min(100, Math.max(0, reading)) : 0;
  const tone = toGaugeTone(hasReading ? reading : null, warnAt, errorAt);

  return (
    <span className="device_gauge">
      <span className="device_gauge_head">
        <span>{label}</span>
        <span className="device_gauge_value">
          {hasReading ? `${Math.round(reading)}${unit}` : "—"}
        </span>
      </span>
      <span className="device_gauge_track">
        <span
          className={`device_gauge_fill device_gauge_fill--${tone}`}
          style={{ width: `${clamped}%` }}
        />
      </span>
    </span>
  );
}

function toGaugeTone(
  reading: number | null,
  warnAt: number,
  errorAt: number,
): "ok" | "warn" | "error" {
  if (reading === null) {
    return "ok";
  }
  if (reading >= errorAt) {
    return "error";
  }
  if (reading >= warnAt) {
    return "warn";
  }
  return "ok";
}
