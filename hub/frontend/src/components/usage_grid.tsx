import {
  formatBucketLabel,
  monthLabel,
  toHeatLevel,
  toWeekGroups,
  tokensOf,
  weekdayLabels,
} from "../ai_usage";
import { formatCompact } from "../format_compact";
import { t, useLanguage } from "../i18n";
import type { AiUsageBucket, AiUsageRange } from "../api_types";

import "./usage_grid.css";

/**
 * The activity grid under the usage tiles, in two readings of the same
 * buckets: `tokens` shades each cell by volume, `health` colours it by
 * outcome.
 *
 * Each range gets the layout its span reads best in. Day and week are one
 * stretched row. A month is a wall calendar after the shape every calendar
 * uses — seven weekday columns across the card, one row per week — because
 * thirty days as week columns leave the card mostly empty. A year keeps the
 * columns, which is the only span with enough weeks to fill them. Wide grids
 * scroll inside their own box so the page never scrolls sideways.
 */

// Above this share of failures a cell turns red instead of amber.
const FAILING_SHARE = 0.5;

const HEAT_LEVEL_STEPS = [0, 1, 2, 3, 4] as const;

type UsageGridMode = "tokens" | "health";

interface UsageGridProps {
  series: AiUsageBucket[];
  range: AiUsageRange;
  mode: UsageGridMode;
}

export function UsageGrid({ series, range, mode }: UsageGridProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const hasTraffic = series.some((point) => point.requests > 0);
  if (series.length === 0 || !hasTraffic) {
    return <GridEmpty />;
  }

  const isSingleRow = range === "day" || range === "week";
  return (
    <div className="usage_grid">
      <div className="usage_grid_scroll">
        {isSingleRow ? (
          <SingleRow series={series} range={range} mode={mode} />
        ) : range === "month" ? (
          <MonthCalendar series={series} range={range} mode={mode} />
        ) : (
          <WeekColumns series={series} range={range} mode={mode} />
        )}
      </div>
      {mode === "tokens" ? <TokensLegend /> : <HealthLegend />}
    </div>
  );
}

function GridEmpty() {
  return (
    <div className="usage_grid_empty">
      <span>{t("ui.usage.grid_empty")}</span>
      <span className="faint">{t("ui.usage.grid_empty_hint")}</span>
    </div>
  );
}

interface RowProps {
  series: AiUsageBucket[];
  range: AiUsageRange;
  mode: UsageGridMode;
}

function SingleRow({ series, range, mode }: RowProps) {
  const highest = Math.max(...series.map(tokensOf));
  const columns = `repeat(${series.length}, minmax(14px, 1fr))`;
  return (
    <div className="usage_grid_strip">
      <div className="usage_grid_row" style={{ gridTemplateColumns: columns }}>
        {series.map((point) => (
          <Cell
            key={point.bucket}
            point={point}
            range={range}
            mode={mode}
            highest={highest}
          />
        ))}
      </div>
      <div
        className="usage_grid_labels"
        style={{ gridTemplateColumns: columns }}
      >
        {series.map((point, index) => (
          <span key={point.bucket} className="usage_grid_label">
            {range === "week" || index % 6 === 0
              ? formatBucketLabel(point.bucket, range)
              : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function MonthCalendar({ series, range, mode }: RowProps) {
  const highest = Math.max(...series.map(tokensOf));
  const weeks = toWeekGroups(series);
  return (
    <div className="usage_grid_calendar">
      <div className="usage_grid_weekdays">
        {weekdayLabels().map((weekday, index) => (
          <span key={index} className="usage_grid_label">
            {weekday}
          </span>
        ))}
      </div>
      <div className="usage_grid_month">
        {weeks.map((week, weekIndex) =>
          week.map((point, dayIndex) =>
            point === null ? (
              <span
                key={`${weekIndex}-${dayIndex}`}
                className="usage_cell usage_cell--void"
              />
            ) : (
              <Cell
                key={point.bucket}
                point={point}
                range={range}
                mode={mode}
                highest={highest}
              />
            ),
          ),
        )}
      </div>
    </div>
  );
}

function WeekColumns({ series, range, mode }: RowProps) {
  const highest = Math.max(...series.map(tokensOf));
  const columns = toWeekGroups(series);
  return (
    <div className="usage_grid_weeks">
      <div className="usage_grid_months">
        {columns.map((column, index) => (
          <span key={index} className="usage_grid_label">
            {monthLabelFor(column)}
          </span>
        ))}
      </div>
      <div className="usage_grid_matrix">
        {columns.map((column, columnIndex) => (
          <div key={columnIndex} className="usage_grid_week">
            {column.map((point, rowIndex) =>
              point === null ? (
                <span key={rowIndex} className="usage_cell usage_cell--void" />
              ) : (
                <Cell
                  key={point.bucket}
                  point={point}
                  range={range}
                  mode={mode}
                  highest={highest}
                />
              ),
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

interface CellProps {
  point: AiUsageBucket;
  range: AiUsageRange;
  mode: UsageGridMode;
  highest: number;
}

function Cell({ point, range, mode, highest }: CellProps) {
  const label = formatBucketLabel(point.bucket, range);
  if (mode === "tokens") {
    const tokens = tokensOf(point);
    const level = toHeatLevel(tokens, highest);
    return (
      <span
        className={`usage_cell usage_cell--heat${level}`}
        title={t("ui.usage.cell_tokens", {
          label,
          tokens: formatCompact(tokens),
        })}
      />
    );
  }
  const state = healthStateOf(point);
  return (
    <span
      className={`usage_cell usage_cell--${state}`}
      title={
        point.requests === 0
          ? t("ui.usage.cell_quiet", { label })
          : t("ui.usage.cell_health", {
              label,
              ok: point.requests - point.failed,
              failed: point.failed,
            })
      }
    />
  );
}

function TokensLegend() {
  return (
    <div className="usage_grid_legend">
      <span className="faint">{t("ui.usage.less")}</span>
      {HEAT_LEVEL_STEPS.map((level) => (
        <span key={level} className={`usage_cell usage_cell--heat${level}`} />
      ))}
      <span className="faint">{t("ui.usage.more")}</span>
    </div>
  );
}

function HealthLegend() {
  return (
    <div className="usage_grid_legend">
      <span className="usage_cell usage_cell--idle" />
      <span className="faint">{t("state.quiet")}</span>
      <span className="usage_cell usage_cell--ok" />
      <span className="faint">{t("state.healthy")}</span>
      <span className="usage_cell usage_cell--warn" />
      <span className="faint">{t("state.degraded")}</span>
      <span className="usage_cell usage_cell--error" />
      <span className="faint">{t("state.failing")}</span>
    </div>
  );
}

function healthStateOf(point: AiUsageBucket): string {
  if (point.requests === 0) {
    return "idle";
  }
  if (point.failed === 0) {
    return "ok";
  }
  return point.failed / point.requests > FAILING_SHARE ? "error" : "warn";
}

function monthLabelFor(column: (AiUsageBucket | null)[]): string {
  for (const point of column) {
    if (point === null) {
      continue;
    }
    const match = /^(\d{4})-(\d{2})-01/.exec(point.bucket);
    if (match !== null) {
      return monthLabel(Number(match[2]) - 1);
    }
  }
  return "";
}
