import "./meter.css";

/** The panel's tones, the same set the stat tiles are drawn in. */
export type MeterTone = "accent" | "secondary" | "ok" | "warn" | "error";

/** How full the bar is, and what the panel calls that. */
interface MeterProps {
  /** 0 to 100; anything outside is clamped rather than overflowing. */
  percent: number;
  tone: MeterTone;
  /** Shown beside the bar. Omitted leaves the bar on its own. */
  label?: string;
}

/**
 * A short bar for a value that has a full and an empty, beside a word for it.
 *
 * Small enough to sit on a field's own label line, which is where a reading
 * about that field belongs — under it would push the field around as the
 * reading changed.
 */
export function Meter({ percent, tone, label }: MeterProps) {
  const width = `${Math.min(100, Math.max(0, percent))}%`;
  return (
    <span className={`meter meter--${tone}`}>
      {label !== undefined && label !== "" && (
        <span className="meter_label">{label}</span>
      )}
      <span className="meter_track">
        <span className="meter_fill" style={{ width }} />
      </span>
    </span>
  );
}
