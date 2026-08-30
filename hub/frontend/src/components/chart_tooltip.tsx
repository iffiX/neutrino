import "./chart_tooltip.css";

/**
 * The shared tooltip for both dashboard charts.
 *
 * Recharts clones whatever element is handed to `content` and merges its own
 * props in, so the formatter passed at the call site survives alongside the
 * `active`/`payload`/`label` recharts supplies. That is what lets the live
 * rate chart and the 30-day totals chart share one tooltip while formatting
 * their numbers differently.
 */

interface ChartTooltipEntry {
  name?: string | number;
  value?: number | string | Array<number | string>;
  color?: string;
}

interface ChartTooltipProps {
  format: (value: number) => string;
  active?: boolean;
  label?: string | number;
  payload?: ChartTooltipEntry[];
}

export function ChartTooltip({
  format,
  active,
  label,
  payload,
}: ChartTooltipProps) {
  if (active !== true || payload === undefined || payload.length === 0) {
    return null;
  }

  return (
    <div className="chart_tooltip">
      <span className="chart_tooltip_label">{String(label ?? "")}</span>
      <div className="chart_tooltip_rows">
        {payload.map((entry, index) => (
          <div
            className="chart_tooltip_row"
            key={`${String(entry.name)}-${index}`}
          >
            <span className="chart_tooltip_name">
              <span
                className="chart_tooltip_swatch"
                style={{ background: entry.color ?? "var(--color-accent)" }}
              />
              {String(entry.name ?? "")}
            </span>
            <span className="chart_tooltip_value">
              {format(toNumber(entry.value))}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function toNumber(value: ChartTooltipEntry["value"]): number {
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}
