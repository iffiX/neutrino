import { Icon } from "./icon";
import type { IconName } from "./icon";
import { useAnimatedNumber } from "../use_animated_number";
import "./stat_tile.css";

/**
 * One headline number on the dashboard.
 *
 * The tile owns the tween: it takes the raw number and a formatter rather than
 * a finished string, so the digits ease into their new value every time the
 * stats socket pushes a frame instead of flickering between two readings.
 */

export type StatTone = "accent" | "secondary" | "ok" | "warn" | "error";

interface StatTileProps {
  label: string;
  value: number;
  format: (value: number) => string;
  unit?: string;
  icon?: IconName;
  tone?: StatTone;
  detail?: string;
  meterPercent?: number;
}

export function StatTile({
  label,
  value,
  format,
  unit,
  icon,
  tone = "accent",
  detail,
  meterPercent,
}: StatTileProps) {
  const animatedValue = useAnimatedNumber(value);
  const meterWidth =
    meterPercent === undefined
      ? null
      : `${Math.min(100, Math.max(0, meterPercent))}%`;

  return (
    <div className={`stat_tile stat_tile--${tone}`}>
      <div className="stat_tile_head">
        {icon !== undefined && (
          <Icon name={icon} size={14} className="stat_tile_icon" />
        )}
        <span className="stat_tile_label">{label}</span>
      </div>
      <div className="stat_tile_value">
        <span>{format(animatedValue)}</span>
        {unit !== undefined && <span className="stat_tile_unit">{unit}</span>}
      </div>
      {meterWidth !== null && (
        <div className="stat_tile_meter">
          <div className="stat_tile_meter_fill" style={{ width: meterWidth }} />
        </div>
      )}
      {detail !== undefined && (
        <div className="stat_tile_detail mono">{detail}</div>
      )}
    </div>
  );
}
