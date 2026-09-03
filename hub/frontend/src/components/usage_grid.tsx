import {
  MONTH_LABELS,
  formatBucketLabel,
  toHeatLevel,
  toWeekColumns,
  tokensOf,
} from "../ai_usage";
import { formatCompact } from "../format_compact";
import type { AiUsageBucket, AiUsageRange } from "../api_types";

import "./usage_grid.css";

/**
 * The activity grid under the usage tiles, in two readings of the same
 * buckets: `tokens` shades each cell by volume, `health` colours it by
 * outcome. Daily buckets lay out as weekday-aligned week columns; the day
 * range is a single row of hours. Wide grids scroll inside their own box so
 * the page never scrolls sideways.
 */

const WORDING = {
  empty: "No requests yet",
  emptyHint: "Cells fill in as machines talk to the gateway.",
  less: "Less",
  more: "More",
  quiet: "quiet",
  healthy: "healthy",
  degraded: "degraded",
  failing: "failing",
  noRequests: "no requests",
  tokensWord: "tokens",
  okWord: "ok",
  failedWord: "failed",
} as const;

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
      <span>{WORDING.empty}</span>
      <span className="faint">{WORDING.emptyHint}</span>
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

function WeekColumns({ series, range, mode }: RowProps) {
  const highest = Math.max(...series.map(tokensOf));
  const columns = toWeekColumns(series);
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
        title={`${label} · ${formatCompact(tokens)} ${WORDING.tokensWord}`}
      />
    );
  }
  const state = healthStateOf(point);
  const outcome =
    point.requests === 0
      ? WORDING.noRequests
      : `${point.requests - point.failed} ${WORDING.okWord} · ${point.failed} ${WORDING.failedWord}`;
  return (
    <span
      className={`usage_cell usage_cell--${state}`}
      title={`${label} · ${outcome}`}
    />
  );
}

function TokensLegend() {
  return (
    <div className="usage_grid_legend">
      <span className="faint">{WORDING.less}</span>
      {HEAT_LEVEL_STEPS.map((level) => (
        <span key={level} className={`usage_cell usage_cell--heat${level}`} />
      ))}
      <span className="faint">{WORDING.more}</span>
    </div>
  );
}

function HealthLegend() {
  return (
    <div className="usage_grid_legend">
      <span className="usage_cell usage_cell--idle" />
      <span className="faint">{WORDING.quiet}</span>
      <span className="usage_cell usage_cell--ok" />
      <span className="faint">{WORDING.healthy}</span>
      <span className="usage_cell usage_cell--warn" />
      <span className="faint">{WORDING.degraded}</span>
      <span className="usage_cell usage_cell--error" />
      <span className="faint">{WORDING.failing}</span>
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
      return MONTH_LABELS[Number(match[2]) - 1] ?? "";
    }
  }
  return "";
}
