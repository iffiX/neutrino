import "./device_gauge.css";

/**
 * One reading of a managed machine as a ring, 30 px across: the integer
 * inside, the label under it, and, with `count` above one, an `×N` badge at
 * the ring's corner.
 *
 * A missing reading draws an empty ring and an em dash, never a zero: an
 * unreported CPU is not an idle one. The thresholds are parameters, so a
 * temperature rings with its own.
 */

const WARN_PERCENT = 75;
const ERROR_PERCENT = 90;

const RING_PX = 30;
const STROKE_PX = 3;
const RADIUS = (RING_PX - STROKE_PX) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** A ring fills to its reading out of this; a temperature fills by degrees. */
const FULL_RING = 100;

interface DeviceGaugeProps {
  label: string;
  reading: number | null;
  warnAt?: number;
  errorAt?: number;
  /** How many cards the reading is the busiest of; a badge above one. */
  count?: number;
}

export function DeviceGauge({
  label,
  reading,
  warnAt = WARN_PERCENT,
  errorAt = ERROR_PERCENT,
  count = 1,
}: DeviceGaugeProps) {
  const hasReading = reading !== null && Number.isFinite(reading);
  const clamped = hasReading ? Math.min(FULL_RING, Math.max(0, reading)) : 0;
  const tone = toGaugeTone(hasReading ? reading : null, warnAt, errorAt);
  return (
    <span className="device_gauge" title={label}>
      <span className="device_gauge_ring">
        <svg
          width={RING_PX}
          height={RING_PX}
          viewBox={`0 0 ${RING_PX} ${RING_PX}`}
          aria-hidden="true"
        >
          <circle
            className="device_gauge_track"
            cx={RING_PX / 2}
            cy={RING_PX / 2}
            r={RADIUS}
            strokeWidth={STROKE_PX}
          />
          <circle
            className={`device_gauge_fill device_gauge_fill--${tone}`}
            cx={RING_PX / 2}
            cy={RING_PX / 2}
            r={RADIUS}
            strokeWidth={STROKE_PX}
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE * (1 - clamped / FULL_RING)}
          />
        </svg>
        <span className="device_gauge_value">
          {hasReading ? Math.round(reading) : "—"}
        </span>
        {count > 1 && <span className="device_gauge_count">×{count}</span>}
      </span>
      <span className="device_gauge_label">{label}</span>
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
